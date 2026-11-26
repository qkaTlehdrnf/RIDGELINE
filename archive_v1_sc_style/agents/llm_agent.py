"""Real-time LLM commander. Talks to a running ridgeline.server over HTTP and to Claude through the `claude` CLI.

  python -m ridgeline.server --speed 1 --p1 bot &
  python agents/llm_agent.py --player 0 --model claude-fable-5-2 --log runs/live1.log

How it keeps tokens low
- The rules/map brief is the system prompt of one persistent conversation, so it is cached after turn 1.
- Each turn the model receives only: results of its last commands + a delta observation (changed lines, new events).
- The model picks its own wake-up time ("wait 20"); the server wakes it earlier only for important events.
- Fast reactions are delegated to reflex scripts that run inside the engine every few ticks.
- Every `--resync` turns the conversation restarts from a full observation plus the model's own one-line note.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request

ROLE = """You command one side of a real-time strategy game through a text protocol. The game keeps running while you think,
so be brief and decisive.

Each message you receive holds the results of your previous commands and a delta observation. Reply with command lines only,
no prose. Extra lines you may add:
  wait <seconds>      game seconds until your next turn (default 15). You are woken early if attacked or enemies appear.
  note <text>         one line of plan memory; it is given back to you after a context reset.
  script <name> <every_ticks>
  def tick(api): ...  python reflex code run inside the engine (no imports). End the block with a line 'end'.
                      api.t tick, api.ore, api.sup (used, cap), api.units / api.enemies (lists of dicts with id type x y hp
                      max_hp rng level struct; units also order cd group queue), api.mem (dict kept between calls),
                      api.cmd("amove 12,13 30 30"), api.q("near 30 30 6"), api.dist(a, b) where a, b are unit dicts or (x, y).
  script <name> off   remove a script.
Use scripts for things that need reaction speed you do not have (focus fire, retreating hurt units, kiting, scouting loops).
Use `auto wrk`, `auto sup`, `repeat` and `rally` so the economy runs without you. Use `q ...` when you need detail.

"""


def http(url, data=None, timeout=120):
    req = urllib.request.Request(url, data=data.encode() if data is not None else None, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode()


class ClaudeCLI:
    """Persistent conversation through `claude -p --resume`. Tools are disabled: the model can only emit text."""

    def __init__(self, model, system, effort=None):
        self.model = model; self.system = system; self.sid = None; self.effort = effort
        self.usage = dict(turns=0, input=0, cache_read=0, cache_write=0, output=0, cost=0.0, secs=0.0)

    def reset(self): self.sid = None

    def ask(self, text):
        cmd = ["claude", "-p", "--tools", "", "--strict-mcp-config", "--output-format", "json", "--model", self.model]
        if self.effort: cmd += ["--effort", self.effort]
        if self.sid: cmd += ["--resume", self.sid]
        else: cmd += ["--system-prompt", self.system]
        t0 = time.time()
        r = subprocess.run(cmd, input=text, capture_output=True, text=True, timeout=300, cwd="/tmp")
        dt = time.time() - t0
        try:
            j = json.loads(r.stdout)
        except Exception:
            raise RuntimeError("claude cli failed: %s %s" % (r.stdout[:300], r.stderr[:300]))
        if j.get("is_error"): raise RuntimeError("claude cli error: %s" % str(j.get("result"))[:300])
        self.sid = j.get("session_id", self.sid)
        u = j.get("usage", {}); U = self.usage
        U["turns"] += 1; U["input"] += u.get("input_tokens", 0); U["cache_read"] += u.get("cache_read_input_tokens", 0)
        U["cache_write"] += u.get("cache_creation_input_tokens", 0); U["output"] += u.get("output_tokens", 0)
        U["cost"] += j.get("total_cost_usd", 0.0); U["secs"] += dt
        return j.get("result", ""), dict(secs=round(dt, 1), inp=u.get("input_tokens", 0), cr=u.get("cache_read_input_tokens", 0),
                                         cw=u.get("cache_creation_input_tokens", 0), out=u.get("output_tokens", 0))


def parse_reply(text):
    """-> (command_text, wait_seconds, note, scripts[(name, every, code)])"""
    cmds = []; wait = 15.0; note = None; scripts = []
    lines = [l.rstrip() for l in text.replace("```python", "").replace("```", "").split("\n")]
    i = 0
    while i < len(lines):
        l = lines[i].strip(); i += 1
        if not l: continue
        w = l.split()
        if w[0] == "wait" and len(w) > 1:
            try: wait = max(2.0, min(120.0, float(w[1])))
            except ValueError: pass
        elif w[0] == "note": note = l[5:].strip()
        elif w[0] == "script" and len(w) >= 2:
            if len(w) >= 3 and w[2] == "off": scripts.append((w[1], 5, "")); continue
            every = int(w[2]) if len(w) >= 3 and w[2].isdigit() else 5
            body = []
            while i < len(lines) and lines[i].strip() != "end": body.append(lines[i]); i += 1
            i += 1
            scripts.append((w[1], every, "\n".join(body)))
        else: cmds.append(l)
    return "\n".join(cmds), wait, note, scripts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8765"); ap.add_argument("--player", type=int, default=0)
    ap.add_argument("--key", default=""); ap.add_argument("--model", default="claude-fable-5-2")
    ap.add_argument("--effort", default=None); ap.add_argument("--speed", type=float, default=1.0, help="server speed factor")
    ap.add_argument("--resync", type=int, default=40); ap.add_argument("--log", default=None)
    ap.add_argument("--max-turns", type=int, default=400)
    a = ap.parse_args()
    qs = "?p=%d%s" % (a.player, ("&key=" + a.key) if a.key else "")
    log = open(a.log, "w") if a.log else None

    def out(s):
        print(s, flush=True)
        if log: log.write(s + "\n"); log.flush()

    llm = ClaudeCLI(a.model, ROLE + http(a.url + "/brief" + qs), a.effort)
    msg = "Game start. Full observation:\n" + http(a.url + "/obs" + qs + "&mode=full")
    note = None; since = 0
    for turn in range(a.max_turns):
        out("---- turn %d  >> to model\n%s" % (turn, msg))
        try:
            reply, u = llm.ask(msg)
        except Exception as ex:
            out("!! %s" % ex); time.sleep(3); llm.reset()
            msg = "Context reset. Full observation:\n" + http(a.url + "/obs" + qs + "&mode=full"); continue
        out("<< model (%ss, in %d, cache read %d, cache write %d, out %d)\n%s" % (u["secs"], u["inp"], u["cr"], u["cw"], u["out"], reply))
        cmds, wait, n2, scripts = parse_reply(reply)
        note = n2 or note
        res = []
        try:
            for (name, every, code) in scripts:
                res.append(http(a.url + "/script" + qs + "&name=%s&every=%d" % (name, every), code))
            if cmds: res.append(http(a.url + "/act" + qs, cmds))
            delta = http(a.url + "/wait" + qs + "&timeout=%g&min=%g" % (wait / a.speed, 2.0 / a.speed))
        except OSError:
            out("server closed (game over)"); break
        if "GAME OVER" in delta: out(delta); break
        since += 1
        if since >= a.resync:
            llm.reset(); since = 0
            msg = "Context reset. Your note: %s\nFull observation:\n%s" % (note or "(none)", http(a.url + "/obs" + qs + "&mode=full"))
        else:
            msg = "\n".join(res + [delta])
    out("==== usage %s" % json.dumps(llm.usage))


if __name__ == "__main__":
    main()
