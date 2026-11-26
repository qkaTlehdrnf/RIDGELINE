"""Review-and-rewrite loop (복기 루프): play, review the games, let an LLM rewrite the faction policy, keep it if it wins.

  python tools/evolve.py --gens 3 --seeds 30 31 32 --model claude-sonnet-5-5

Each generation
  1. the champion policy plays the reference opponent on every seed FROM BOTH SIDES (starts are random and unequal,
     so only the paired result says anything about the policy),
  2. a review report is built from those games: results, timeline, and aggregates of every assault it launched,
  3. the reviewer model gets the rules, the policy API, the champion's code and the report, writes a short review and
     a complete new policy file,
  4. the candidate is checked (compiles, no crash, time budget) and plays the champion on the same seeds from both
     sides; it becomes the new champion only if its paired margin is positive.
Everything is saved under runs/evolve/. Battle episodes from every game are appended to runs/battles.jsonl, and
--refit re-trains policies/model.json on them, so the learned model follows the data too.

The reviewer writes code between games; it never commands units live. Fable is refused here as well.
"""
import json, os, re, subprocess, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from ridgeline.engine import small_game
from ridgeline.iface import PolicyApi, Session
from ridgeline.match import run_match

OUT = os.path.join(ROOT, "runs", "evolve")
DUEL = dict(factions=("aurum", "sable"), size="small")     # reviews are run as duels on the 300-province map (fast, and a paired
                                                           # two-seat comparison is the cleanest signal); the policies themselves run on any map


def play_pair(a, b, seed, model, max_ticks):
    """a and b play seed twice, swapping sides. Returns a's paired margin and the per-game detail (a's view)."""
    games = []
    for side in (0, 1):
        pol = (a, b) if side == 0 else (b, a)
        bl = []; tl = []
        r = run_match(policies=pol, models=(model, model), seed=seed, max_ticks=max_ticks, battle_log=bl, timeline=tl, **DUEL)
        games.append(dict(seed=seed, side=side, won=r["winner"] == side, ticks=r["ticks"],
                          prov=(r["provinces"][side], r["provinces"][1 - side]), units=(r["units"][side], r["units"][1 - side]),
                          kills=(r["kills"][side], r["kills"][1 - side]), start=r["start"], err=r["policy_errors"][side],
                          ms=r["policy_ms"][side], battles=[x for x in bl if x["side"] == side],
                          enemy_battles=[x for x in bl if x["side"] != side], timeline=tl, all_battles=bl))
    margin = sum(g["prov"][0] - g["prov"][1] for g in games) + 60 * sum((1 if g["won"] else -1) for g in games)
    return margin, games


def evaluate(a, b, seeds, model, max_ticks):
    total = 0; games = []
    for s in seeds:
        m, gs = play_pair(a, b, s, model, max_ticks); total += m; games += gs
    return total, games


def _rate(rows): return "%d/%d" % (sum(r["won"] for r in rows), len(rows)) if rows else "-"


def _bins(rows, key, edges, fmt="%s"):
    out = []
    for lo, hi in zip(edges, edges[1:]):
        rs = [r for r in rows if lo <= key(r) < hi]
        if rs: out.append("%s..%s %s (loss %d per assault)" % (fmt % lo, fmt % hi, _rate(rs), sum(r["att_loss"] for r in rs) / len(rs)))
    return "; ".join(out)


def review_report(games):
    L = []; wins = sum(g["won"] for g in games)
    L.append("GAMES (your policy's view; each seed is played from both starts): %d wins of %d" % (wins, len(games)))
    for g in games:
        st = g["start"]; me = g["side"]
        L.append(" seed %d as P%d: %s after %d h. provinces %d vs %d, units %d vs %d, destroyed %d lost %d. start: provinces %d vs %d, "
                 "units %d vs %d.%s" % (g["seed"], me, "WON" if g["won"] else "lost/behind", g["ticks"], g["prov"][0], g["prov"][1],
                                         g["units"][0], g["units"][1], g["kills"][0], g["kills"][1], st["provs"][me], st["provs"][1 - me],
                                         st["units"][me], st["units"][1 - me], (" POLICY ERROR: %s" % g["err"]) if g["err"] else ""))
        tl = g["timeline"][::max(1, len(g["timeline"]) // 6)]
        L.append("   day:provinces(me/enemy):units(me/enemy):active assaults  " + "  ".join(
            "%d:%d/%d:%d/%d:%d" % (t["t"] // 24, t["prov"][me], t["prov"][1 - me], t["units"][me], t["units"][1 - me], t["assaults"]) for t in tl))
    mine = [b for g in games for b in g["battles"]]; theirs = [b for g in games for b in g["enemy_battles"]]
    ratio = lambda r: (r["att_str"] + 1.0) / (r["def_str"] + 1.0)
    L.append("YOUR ASSAULTS: %s succeeded. average attackers %.1f units from %.1f directions, readiness %d, plan bonus %d%%, "
             "strength lost %d per assault, %d h each." % (
                 _rate(mine), sum(r["att_n"] for r in mine) / max(1, len(mine)), sum(r["dirs"] for r in mine) / max(1, len(mine)),
                 sum(r["att_rdy"] for r in mine) / max(1, len(mine)), sum(r["att_bonus"] for r in mine) / max(1, len(mine)),
                 sum(r["att_loss"] for r in mine) / max(1, len(mine)), sum(r["hours"] for r in mine) / max(1, len(mine))))
    L.append(" by strength ratio (attackers:defenders): " + _bins(mine, ratio, [0, 1, 1.5, 2, 3, 5, 1e9], "%g"))
    L.append(" by attackers' readiness: " + _bins(mine, lambda r: r["att_rdy"], [0, 25, 50, 75, 101], "%d"))
    L.append(" by plan bonus %: " + _bins(mine, lambda r: r["att_bonus"], [0, 1, 25, 45, 76], "%d"))
    L.append(" by fort level: " + _bins(mine, lambda r: r["fort"], [0, 1, 2, 3, 4], "%d"))
    L.append(" by directions: " + _bins(mine, lambda r: r["dirs"], [1, 2, 3, 9], "%d"))
    L.append(" by share of art/arm/eng among attackers: " + _bins(
        mine, lambda r: sum(r["att_types"].get(k, 0) for k in ("art", "arm", "eng")) / max(1, r["att_n"]), [0, 0.01, 0.25, 0.5, 1.01], "%.2f"))
    L.append(" by supply stock behind the attackers: " + _bins(mine, lambda r: r["att_stock"], [0, 30, 100, 1e9], "%g"))
    L.append("ENEMY ASSAULTS on you: %s succeeded; by ratio: %s" % (_rate(theirs), _bins(theirs, ratio, [0, 1, 1.5, 2, 3, 5, 1e9], "%g")))
    return "\n".join(L)


SYSTEM = """You are the staff of one faction in Ridgeline, a province-based war game. Between games you review what happened and rewrite your faction's standing orders: a Python policy `def tick(api)` that the engine runs every 6 game hours for your side. You never command units live.

Think at every level, not only single attacks: where the main effort goes, how many units hold the line versus rest in reserve behind it, when to rotate, which sectors to give up or fortify, how to cut enemy supply lines, what to recruit. You may keep state in api.mem (army groups, sectors, phases). You may use the learned battle model in api.model or ignore it.

Rules for the code: one file, no imports (the name `math` is available), only plain Python builtins, must define tick(api), keep it fast (a few ms per call) and robust (a crash removes the policy for the rest of the game). Orders go through api.cmd("...") using the command language in the rules.

Reply with a review of at most 200 words (what the evidence shows and what you change), then the COMPLETE new policy file in one ```python block. Nothing after the block."""


def ask(model, prompt):
    if "fable" in model.lower():
        raise SystemExit("refusing %s: the war-side agents run on a cheaper model (user rule)" % model)
    cmd = ["claude", "-p", "--tools", "", "--strict-mcp-config", "--output-format", "json", "--model", model, "--system-prompt", SYSTEM]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=900, cwd="/tmp")
    j = json.loads(r.stdout)
    if j.get("is_error"): raise RuntimeError(str(j.get("result"))[:400])
    u = j.get("usage", {})
    return j.get("result", ""), dict(cost=j.get("total_cost_usd", 0.0), out=u.get("output_tokens", 0),
                                     inp=u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0))


def check(path, model):
    """Compiles, survives 400 hours on a seed, stays inside the time budget."""
    try: compile(open(path, encoding="utf-8").read(), path, "exec")
    except SyntaxError as e: return "syntax error: %s" % e
    try: r = run_match(policies=(path, path), models=(model, model), seed=99, max_ticks=400, **DUEL)
    except Exception as e: return "could not start: %s" % e
    if any(r["policy_errors"]): return "crashed: %s" % [e for e in r["policy_errors"] if e][0]
    if max(m or 0 for m in r["policy_ms"]) > 25: return "too slow: %.1f ms per call" % max(r["policy_ms"])
    return None


def main():
    a = sys.argv[1:]
    def opt(k, d, many=False):
        if k not in a: return d
        i = a.index(k); vals = []
        for v in a[i + 1:]:
            if v.startswith("--"): break
            vals.append(v)
        return vals if many else vals[0]
    gens = int(opt("--gens", 2)); seeds = [int(s) for s in opt("--seeds", ["30", "31", "32"], True)]
    model = opt("--model", "claude-sonnet-5-5"); max_ticks = int(opt("--max-ticks", 3000))
    champ = opt("--start", os.path.join(ROOT, "policies", "learned.py")); ref = opt("--ref", os.path.join(ROOT, "policies", "basic.py"))
    bmodel = opt("--battle-model", os.path.join(ROOT, "policies", "model.json")); refit = "--refit" in a
    os.makedirs(OUT, exist_ok=True)
    rules = Session(small_game(seeds[0]), 0).brief()
    log = dict(seeds=seeds, model=model, gens=[], cost=0.0)
    opponent = ref
    history = []
    if os.path.exists(os.path.join(OUT, "log.json")) and "--resume" in a:
        old = json.load(open(os.path.join(OUT, "log.json"), encoding="utf-8")); history = old["gens"]; log["cost"] = old["cost"]; log["gens"] = history
    failed = [e for e in history if e["result"] != "accepted"]
    for gen in range(len(history) + 1, len(history) + gens + 1):
        t0 = time.time()
        margin, games = evaluate(champ, opponent, seeds, bmodel, max_ticks)
        with open(os.path.join(ROOT, "runs", "battles.jsonl"), "a", encoding="utf-8") as f:
            for g in games[::2] + games[1::2]:
                for b in g["all_battles"]: f.write(json.dumps(b) + "\n")
        report = review_report(games)
        prompt = "\n\n".join(x for x in [
            "RULES (the same briefing a live commander gets)\n" + rules,
            "POLICY API\n" + PolicyApi.__doc__,
            "api.model here: " + (json.dumps({k: v for k, v in json.load(open(bmodel)).items() if k != "holdout"}) if bmodel else "{}") +
            "\n(logistic regression fitted on earlier battles: p = sigmoid(b + sum(w*(x-mean)/std)); features in that order. "
            "log_ratio = ln((attacker strength+1)/(defender strength+1)), terrain_dfn = 1/1.25/1.5/2, bonus = plan bonus/100, att_rdy = readiness/100, "
            "heavy_share = share of art/eng/arm, dirs = attack directions.)",
            "REVIEW DATA: your current policy against `%s` (paired margin %+d; positive means you are ahead)\n%s" % (os.path.basename(opponent), margin, report),
            ("EARLIER REWRITES OF THIS SAME POLICY THAT WERE TRIED AND REJECTED (do not repeat them; find a different lever)\n" + "\n".join(
                "- attempt %d: %s\n  outcome against the current policy: %s" % (e["gen"], " ".join(e.get("review", "").split())[:900],
                    e.get("why") or "paired margin %+d, wins %s, assaults won %s" % (e["margin_vs_champion"], e["wins_vs_champion"], e["assaults"]))
                for e in failed)) if failed else "",
            "YOUR CURRENT POLICY\n```python\n%s\n```" % open(champ, encoding="utf-8").read(),
        ] if x)
        d = os.path.join(OUT, "gen%d" % gen); os.makedirs(d, exist_ok=True)
        open(os.path.join(d, "report.txt"), "w", encoding="utf-8").write(report)
        entry = dict(gen=gen, champion=os.path.relpath(champ, ROOT), vs=os.path.basename(opponent), margin_before=margin)
        cand = os.path.join(d, "policy.py"); err = "no reply"; text = ""
        for attempt in range(2):
            text, use = ask(model, prompt if attempt == 0 else prompt + "\n\nYour previous file was rejected: %s. Send a corrected complete file." % err)
            log["cost"] += use["cost"]
            m = re.search(r"```python\n(.*?)```", text, re.S)
            if not m: err = "no ```python block"; continue
            open(cand, "w", encoding="utf-8").write(m.group(1))
            err = check(cand, bmodel)
            if not err: break
        open(os.path.join(d, "review.md"), "w", encoding="utf-8").write(text)
        entry["review"] = text.split("```python")[0].strip()
        if err:
            entry.update(result="rejected", why=err)
        else:
            m2, g2 = evaluate(cand, champ, seeds, bmodel, max_ticks)
            entry.update(margin_vs_champion=m2, wins_vs_champion="%d/%d" % (sum(g["won"] for g in g2), len(g2)),
                         assaults="%s -> %s" % (_rate([b for g in games for b in g["battles"]]), _rate([b for g in g2 for b in g["battles"]])))
            with open(os.path.join(ROOT, "runs", "battles.jsonl"), "a", encoding="utf-8") as f:
                for g in g2:
                    if g["side"] == 0:
                        for b in g["all_battles"]: f.write(json.dumps(b) + "\n")
            if m2 > 0:
                entry["result"] = "accepted"; opponent = champ; champ = cand; failed[:] = []        # next generation must beat its parent
            else:
                entry["result"] = "kept champion"
        if refit and bmodel:
            subprocess.run([sys.executable, os.path.join(ROOT, "tools", "fit_battle_model.py"), os.path.join(ROOT, "runs", "battles.jsonl"), bmodel])
        entry["secs"] = round(time.time() - t0); entry["cost_so_far"] = round(log["cost"], 3)
        history.append(entry)
        if entry["result"] != "accepted": failed.append(entry)
        log["gens"] = history; log["champion"] = os.path.relpath(champ, ROOT)
        json.dump(log, open(os.path.join(OUT, "log.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print(json.dumps({k: v for k, v in entry.items() if k != "review"}, ensure_ascii=False), flush=True)
    print("champion:", champ, "cost $%.2f" % log["cost"])


if __name__ == "__main__":
    main()
