"""Real-time AI commander on a fixed cadence: one batch of commands per command window (default every 5 s).

  python -m ridgeline.server --seed 7 --policy0 policies/basic.py --policy1 policies/basic.py &
  python agents/llm_agent.py --player 0 --model claude-haiku-5-5 --log runs/p0.log
  python agents/llm_agent.py --player 1 --backend openai --base-url http://localhost:8000/v1 --model <local model>

Units keep following their standing orders and the installed policy between turns; the agent only redirects.
Cost controls: the brief is a cached system prompt; each turn sends only results + delta; turns where nothing
changed are skipped without calling the model; the conversation is reset every --resync model calls.
"""
import argparse
import json
import subprocess
import time
import urllib.request

ROLE = """You command one side of a real-time strategy game through a text protocol. You get one turn every few seconds;
the game does not wait. Between your turns units keep executing their orders and your standing policy program.

Each message holds the results of your previous commands and a delta observation. Reply with command lines only, no prose.
An empty reply or 'pass' is fine when nothing needs changing. Optional extra lines:
  note <text>          one line of plan memory, returned to you after a context reset
  policy <name> <every_hours>
  def tick(api): ...   replace a standing-order program (python, no imports); end the block with a line 'end'
  policy <name> off
  candidate <name> [every_hours]
  def tick(api): ...   draft a strategy WITHOUT running it; end the block with a line 'end'
Testing strategies while the war goes on: 'trial <hours> <name> <name> ...' plays up to four strategies forward in a
private copy of the war built only from what you know, and returns the forecast for each (provinces, yield, strength
lost, enemy strength destroyed, assaults won). Names: 'current', your drafted candidates, or the ready-made ones listed
in the rules. 'adopt <name>' makes one your standing policy. A trial costs you nothing in the real war, so before a
big change of plan, draft it, trial it against 'current', and adopt it only if it forecasts better. Enemies in a trial
are assumed to play the stock policy, so treat forecasts as comparisons, not predictions.
Policy api: api.t, api.res, api.income, api.capital, api.enemy_capital, api.provs {id: {terrain, elev, y, city, nbrs,
owner 'me'|'enemy'|'neutral', visible, supplied, fort, stock}}, api.units [{id, type, prov, str, rdy, plan, bonus, dry, path, fighting, supplied, group, front}],
api.enemy {prov: {n, str, exact}}, api.mem (dict), api.cmd("move 3,4 P12"), api.q("front"), api.path(a, b).

"""


def http(url, data=None, timeout=120):
    req = urllib.request.Request(url, data=data.encode() if data is not None else None, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


class ClaudeCLI:
    """Persistent conversation via `claude -p --resume`; tools disabled, text only."""

    def __init__(self, model, system):
        self.model = model; self.system = system; self.sid = None
        self.usage = dict(calls=0, input=0, cache_read=0, cache_write=0, output=0, cost=0.0, secs=0.0)

    def reset(self): self.sid = None

    def ask(self, text):
        cmd = ["claude", "-p", "--tools", "", "--strict-mcp-config", "--output-format", "json", "--model", self.model]
        cmd += ["--resume", self.sid] if self.sid else ["--system-prompt", self.system]
        t0 = time.time()
        r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=300, cwd="/tmp")
        dt = time.time() - t0
        try: j = json.loads(r.stdout)
        except Exception: raise RuntimeError("claude cli failed: %s %s" % (r.stdout[:300], r.stderr[:300]))
        if j.get("is_error"): raise RuntimeError("claude cli error: %s" % str(j.get("result"))[:300])
        self.sid = j.get("session_id", self.sid); u = j.get("usage", {}); U = self.usage
        U["calls"] += 1; U["input"] += u.get("input_tokens", 0); U["cache_read"] += u.get("cache_read_input_tokens", 0)
        U["cache_write"] += u.get("cache_creation_input_tokens", 0); U["output"] += u.get("output_tokens", 0)
        U["cost"] += j.get("total_cost_usd", 0.0); U["secs"] += dt
        return j.get("result", ""), "%.1fs new-in %d cached %d out %d" % (
            dt, u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0), u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0))


class OpenAICompat:
    """Any OpenAI-compatible chat endpoint: vLLM, Ollama, llama.cpp server, LM Studio, ... (e.g. a local A100).

      vllm serve <model> --port 8000            ->  --backend openai --base-url http://localhost:8000/v1 --model <model>
      ollama serve (ollama pull <model>)        ->  --backend openai --base-url http://localhost:11434/v1 --model <model>

    The brief stays as the system message (servers with prefix caching reuse it); only the last `window`
    exchanges are kept so the prompt fits small context windows.
    """

    def __init__(self, model, system, base_url, api_key="", window=8, max_tokens=400, temperature=0.2):
        self.model = model; self.system = system; self.url = base_url.rstrip("/") + "/chat/completions"
        self.key = api_key; self.window = window; self.max_tokens = max_tokens; self.temperature = temperature
        self.hist = []
        self.usage = dict(calls=0, input=0, cache_read=0, cache_write=0, output=0, cost=0.0, secs=0.0)

    def reset(self): self.hist = []

    def ask(self, text):
        msgs = [{"role": "system", "content": self.system}] + self.hist[-2 * self.window:] + [{"role": "user", "content": text}]
        body = json.dumps(dict(model=self.model, messages=msgs, max_tokens=self.max_tokens, temperature=self.temperature))
        req = urllib.request.Request(self.url, data=body.encode(), method="POST", headers={"Content-Type": "application/json"})
        if self.key: req.add_header("Authorization", "Bearer " + self.key)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=300) as r: j = json.loads(r.read().decode())
        dt = time.time() - t0
        reply = j["choices"][0]["message"].get("content") or ""
        if "</think>" in reply: reply = reply.split("</think>")[-1]      # reasoning models: keep only the answer
        self.hist += [{"role": "user", "content": text}, {"role": "assistant", "content": reply}]
        u = j.get("usage") or {}; U = self.usage
        U["calls"] += 1; U["input"] += u.get("prompt_tokens", 0); U["output"] += u.get("completion_tokens", 0); U["secs"] += dt
        return reply, "%.1fs prompt %d out %d" % (dt, u.get("prompt_tokens", 0), u.get("completion_tokens", 0))


def parse_reply(text):
    """-> (command_text, note, policies[(name, every, code, is_candidate)])"""
    cmds = []; note = None; pols = []
    lines = [l.rstrip() for l in text.replace("```python", "").replace("```", "").split("\n")]
    i = 0
    while i < len(lines):
        l = lines[i].strip(); i += 1
        if not l or l == "pass": continue
        w = l.split()
        if w[0] == "note": note = l[5:].strip()
        elif w[0] in ("policy", "candidate") and len(w) >= 2:
            if len(w) >= 3 and w[2] == "off": pols.append((w[1], 6, "", False)); continue
            every = int(w[2]) if len(w) >= 3 and w[2].isdigit() else 6
            body = []
            while i < len(lines) and lines[i].strip() != "end": body.append(lines[i]); i += 1
            i += 1; pols.append((w[1], every, "\n".join(body), w[0] == "candidate"))
        else: cmds.append(l)
    return "\n".join(cmds), note, pols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765"); ap.add_argument("--player", type=int, default=0)
    ap.add_argument("--model", default="claude-haiku-5-5", help="claude-haiku-5-5 or claude-opus-5-5 (Opus costs far more per call: lower --max-calls)")
    ap.add_argument("--backend", default="claude-cli", choices=("claude-cli", "openai"),
                    help="openai = any OpenAI-compatible server (vLLM, Ollama, llama.cpp), e.g. a local GPU")
    ap.add_argument("--base-url", default="http://localhost:8000/v1"); ap.add_argument("--api-key", default="")
    ap.add_argument("--window", type=int, default=8, help="openai backend: exchanges kept in the prompt")
    ap.add_argument("--resync", type=int, default=30); ap.add_argument("--log", default=None)
    ap.add_argument("--max-calls", type=int, default=150, help="hard cap on model calls (cost guard)")
    a = ap.parse_args()
    qs = "?p=%d" % a.player
    log = open(a.log, "w") if a.log else None

    def out(s):
        print(s, flush=True)
        if log: log.write(s + "\n"); log.flush()

    if a.backend == "claude-cli" and not any(k in a.model.lower() for k in ("haiku", "opus")):
        raise SystemExit("refusing %s: commanders run on Haiku or Opus only (claude-haiku-5-5, claude-opus-5-5), "
                         "or on a local model with --backend openai." % a.model)
    system = ROLE + http(a.url + "/brief" + qs)
    llm = ClaudeCLI(a.model, system) if a.backend == "claude-cli" else OpenAICompat(a.model, system, a.base_url, a.api_key, a.window)
    msg = "Game start. Full observation:\n" + http(a.url + "/obs" + qs + "&mode=full")
    note = None; since = 0; skipped = 0; cmds = ""; pols = []
    while True:
        if msg is not None and llm.usage["calls"] < a.max_calls:
            out("---- >> to model\n%s" % msg)
            try:
                reply, u = llm.ask(msg)
            except Exception as ex:
                out("!! %s" % ex); llm.reset(); reply = ""; u = "failed"
            out("<< model (%s)\n%s" % (u, reply))
            cmds, n2, pols = parse_reply(reply); note = n2 or note; since += 1
        else:
            cmds, pols = "", []
        try:
            res = [http(a.url + "/policy" + qs + "&name=%s&every=%d&candidate=%d" % (n, e, k), c) for (n, e, c, k) in pols]
            turn = http(a.url + "/turn" + qs, cmds)          # blocks until the next command window
        except OSError:
            out("server closed (game over)"); break
        if "GAME OVER" in turn: out(turn); break
        body = "\n".join(res + [turn])
        quiet = not res and "\n" not in turn.strip() and not cmds        # header line only, nothing sent
        if quiet: skipped += 1; msg = None; continue
        if since >= a.resync:
            llm.reset(); since = 0
            msg = "Context reset. Your note: %s\nFull observation:\n%s" % (note or "(none)", http(a.url + "/obs" + qs + "&mode=full"))
        else: msg = body
    llm.usage["skipped_quiet_turns"] = skipped
    out("==== usage %s" % json.dumps(llm.usage))


if __name__ == "__main__":
    main()
