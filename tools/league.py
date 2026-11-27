"""Each faction's own agent writes its own rules.

  python tools/league.py --gens 2 --seeds 50 51 --model claude-opus-5-5

Nobody hands the factions a strategy. Before the first game every faction's agent gets only the rules of the
world, the policy API and its faction's traits, and writes its standing orders (a policy, `def tick(api)`) from
nothing. All factions then fight each other. After the games each agent reviews ITS OWN war (results, timeline,
its assaults, what happened to it) and its own code, and rewrites its policy however it sees fit, or keeps it.
Agents never see each other's code. There is no referee deciding which rewrite is "better": the next war does.

Files: runs/league/<faction>/gen<N>.py (the policy), gen<N>.md (what the agent said), runs/league/log.json.
Agents run on Haiku or Opus only (--model, or --models a,b,c per faction).
"""
import json, os, re, subprocess, sys, time

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from ridgeline import data as D
from ridgeline import ages as _AG
from ridgeline.engine import Game
from ridgeline.iface import PolicyApi, Session
from ridgeline.mapgen import gen_map
from ridgeline.match import run_match

OUT = os.path.join(ROOT, "runs", "league")
WORLD = None                       # set by --world [scale]: the world map with all 30 factions (scale 0.5 = a quarter of the provinces)
SIZE = (252, 156, 44, 28)          # about 1,200 provinces: big enough for long fronts, a game takes a few minutes

SYSTEM = """You command the faction %(faction)s in Ridgeline, a war game played by AI factions against each other. %(blurb)s

You do not move units by hand. You write your faction's standing orders: one Python file defining `def tick(api)`, which the engine runs for your side every 6 game hours for the whole war. What your faction does, and why, is entirely your decision: its aims, how it grows, where it fights or does not fight, how it uses its units. The rules of the world and everything your orders can see and do are described in the message. Nothing else is prescribed.

Technical limits: one file, no imports (the name `math` is available), plain Python builtins only, must define tick(api). An exception inside tick is caught and that call is lost; a policy that is slower than about 25 ms + 0.2 ms per unit on average is removed for the rest of the war. Orders go through api.cmd("...") in the command language of the rules; api.cmd returns the result text (starts with "ok" on success).

Reply with your reasoning in at most 200 words, then the COMPLETE policy file in one ```python block. After it you may add one ```letters block (see LETTERS in the prompt, when there is one), one ```feedback block (see FEEDBACK TO THE DESIGNERS, when there is one) and one `REVIEW:` line (see REVIEW DETAIL), and nothing else."""

SYNTAX = '''# This only shows how the API is called. It is not a strategy.
def tick(api):
    mine = [u for u in api.units if not u["path"]]            # my units that are standing still
    for i, pr in api.provs.items():                           # provinces I know about
        pass
    r = api.cmd("recruit inf P%d" % api.capital)              # returns "ok 1" or an error text
    if mine: api.cmd("move %d P%d" % (mine[0]["id"], api.provs[mine[0]["prov"]]["nbrs"][0]))
    api.mem["calls"] = api.mem.get("calls", 0) + 1             # api.mem persists between calls
'''


def _map(seed, n, small=False):
    if WORLD:
        from ridgeline.worldgen import gen_world
        return gen_world(seed, scale=0.5 if small else WORLD)
    return gen_map(seed, 126, 78, 22, 14, players=n) if small else gen_map(seed, *SIZE, players=n)


def ask(model, system, prompt):
    if not any(k in model.lower() for k in ("haiku", "opus")):
        raise SystemExit("refusing %s: faction agents run on Haiku or Opus only" % model)
    cmd = ["claude", "-p", "--tools", "", "--strict-mcp-config", "--output-format", "json", "--model", model, "--system-prompt", system]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=1200, cwd="/tmp")
    j = json.loads(r.stdout)
    if j.get("is_error"): raise RuntimeError(str(j.get("result"))[:400])
    return j.get("result", ""), j.get("total_cost_usd", 0.0)


def check(code, pid, factions, bmodel):
    """Compiles, defines tick, survives 300 hours in its own seat without being removed. Returns error text or None."""
    try: compile(code, "<policy>", "exec")
    except SyntaxError as e: return "syntax error: %s" % e
    g = Game(factions=factions, seed=977, gmap=_map(977, len(factions), True), max_ticks=300)
    s = Session(g, pid); r = s.set_policy("main", code)
    if "installed" not in r: return r
    if bmodel: s.model = json.load(open(bmodel))
    errs = 0; first = None
    while not g.over:
        s.pre_tick(); g.step()
        if "main" not in s.policies: return "removed: over the time budget"
        e = s.policies["main"]["err"]
        if e: errs += 1; first = first or e; s.policies["main"]["err"] = None
    if errs > 5: return "tick raised an exception in %d of %d calls, first: %s" % (errs, s.policies["main"]["calls"], first)
    if s.stats["cmds"] == 0: return "the policy never issued a single command"
    if s.stats["errors"] > 0.5 * s.stats["cmds"]: return "%d of %d commands were rejected (check the command syntax)" % (s.stats["errors"], s.stats["cmds"])
    return None


def _rate(rows): return "%d/%d" % (sum(r["won"] for r in rows), len(rows)) if rows else "none"


def report(pid, factions, games, detail="standard"):
    """What one faction is told about its own wars. detail (chosen by the faction itself): brief | standard | full."""
    L = []; lvl = {"brief": 0, "standard": 1, "full": 2}.get(detail, 1)
    for gme in games:
        r = gme["result"]; tl = gme["timeline"]; n = len(factions)
        rank = sorted(range(n), key=lambda i: (-(r["winner"] == i), -r["provinces"][i]))
        L.append("WAR on map %d: you finished %d of %d%s after %d h. Final provinces %s, units %s, units destroyed by each %s." % (
            r["seed"], rank.index(pid) + 1, n, " (ELIMINATED: your last depot fell)" if not r["alive"][pid] else "", r["ticks"],
            " ".join("%s %d" % (("YOU" if i == pid else factions[i]), r["provinces"][i]) for i in range(n)),
            " ".join("%s %d" % (("YOU" if i == pid else factions[i]), r["units"][i]) for i in range(n)),
            " ".join("%s %d" % (("YOU" if i == pid else factions[i]), r["kills"][i]) for i in range(n))))
        st = r["start"]
        L.append(" start: provinces %s, units %s. Land on the map: %d provinces." % (
            " ".join(map(str, st["provs"])), " ".join(map(str, st["units"])), gme["land"]))
        if r["policy_errors"][pid]: L.append(" YOUR POLICY FAILED: %s" % r["policy_errors"][pid])
        L.append(" your commands: %d issued, %d rejected%s" % (gme["cmds"][pid][0], gme["cmds"][pid][1],
                                                              (" (most common: %s)" % gme["cmds"][pid][2]) if gme["cmds"][pid][2] else ""))
        L.append(" your stockpiles at the end: %s; special income per day at the end: %s; your army by kind: %s" % (
            gme["bank"][pid], gme["inc"][pid], gme["kinds"][pid]))
        L.append(" your research results (the hidden table is drawn anew for every war and every faction, so a line that paid off here may be a dead end next time): %s"
                 % ("; ".join(gme["tech"][pid]) or "you researched nothing"))
        if gme.get("ages") and gme["ages"][pid]:
            L.append(" the war stood for the years 0 to %d (%d game hours). You ended in the %s age with %d discoveries; you entered each age in the year: %s" % (
                _AG.CAL_YEARS, r["ticks"], gme["ages"][pid][0], gme["ages"][pid][1], ", ".join("%s %d" % (a_, y_) for y_, a_ in gme["age_t"][pid])))
            L.append(" the factions you came across ended in: %s" % (", ".join("%s %s (%d discoveries, %d provinces)" % (factions[i], gme["ages"][i][0], gme["ages"][i][1], r["provinces"][i]) for i in gme["met"][pid] if i != pid and gme["ages"][i]) or "-"))
            if gme["open_end"][pid]: L.append(" discoveries open to you at the end and never started (res in all, name, share already seeped in): %s" % "; ".join("%d %s %.2f" % x for x in gme["open_end"][pid]))
            m_ = gme["money"][pid]; L.append(" your purse over the whole war: earned %d res; spent on %s" % (m_["earned"], ", ".join("%s %d" % (k, v) for k, v in sorted(m_.items(), key=lambda kv: -kv[1]) if k != "earned")))
        L.append(" units still on an outdated model at the end: %d of %d" % (gme["old"][pid], sum(gme["kinds"][pid].values())))
        nm = lambda i: factions[i]
        L.append(" factions you came across: %s" % (", ".join(nm(i) for i in gme["met"][pid] if i != pid) or "none"))
        dl = [e for e in gme["dip"] if pid in (e["a"], e["b"])]
        if dl:
            L.append(" your dealings (hour: who -> whom, what):")
            for e in dl[:40]:
                L.append("  %d: %s -> %s, %s %s" % (e["t"], nm(e["a"]), nm(e["b"]), e["kind"], e.get("what") or e.get("text") or ("%s %s" % (e.get("n"), e.get("res")) if e.get("res") else "")))
            if len(dl) > 40: L.append("  ... and %d more" % (len(dl) - 40))
        else: L.append(" your dealings with other factions: none (nobody offered you anything, you offered nobody anything)")
        cs = [(t["t"] // 24, t["cond"][pid]) for t in tl if t.get("cond") and t["cond"][pid]]
        if cs:
            avg = lambda k: sum(c[k] for _, c in cs) / len(cs)
            L.append(" condition of your army over the war (mean of %d samples): readiness %.0f, ready (>= 60) %.0f%%, spent (< 20) %.0f%%, short of supplies %.0f%%, on the move %.0f%%, in contact %.0f%%, fighting %.0f%%" % (
                len(cs), avg("rdy"), avg("ready") * 100, avg("spent") * 100, avg("dry") * 100, avg("moving") * 100, avg("contact") * 100, avg("fighting") * 100))
            if lvl >= 1:
                L.append(" day: mean readiness | ready % | spent % | short of supplies % | on the move % | in contact % | morale")
                for d_, c in (cs if lvl >= 2 else cs[::max(1, len(cs) // 6)]):
                    L.append("  %3d: %.0f | %.0f | %.0f | %.0f | %.0f | %.0f | %.0f" % (d_, c["rdy"], c["ready"] * 100, c["spent"] * 100, c["dry"] * 100, c["moving"] * 100, c["contact"] * 100, c["mor"]))
        av = gme.get("army", [None] * n)[pid]
        if av and lvl >= 1:
            f = av["front"]
            L.append(" your front at the end: %d border provinces holding %d units (%.1f each), mean readiness %.0f; stock %.0f on average, empty in %d; inflow %.2f/h against burn %.2f/h per province; %d provinces burn more than they receive" % (
                f["provinces"], f["units"], f["units_per_province"], f["rdy"], f["stock_mean"], f["stock_empty"], f["inflow_per_h"], f["burn_per_h"], f["short"]))
            L.append(" by standing order at the end (units: mean readiness, % on the move): " + "; ".join("%s %d: %.0f, %.0f%%" % (k, v["n"], v["rdy"], v["moving"] * 100) for k, v in av["by_order"].items()))
        if av and lvl >= 2:
            L.append(" by unit type at the end (units: readiness, morale, % short of supplies): " + "; ".join("%s %d: %.0f, %.0f, %.0f%%" % (k, v["n"], v["rdy"], v["mor"], v["dry"] * 100) for k, v in av["by_type"].items()))
            rows = sorted((r for r in av["provinces"] if r["border"]), key=lambda r: r["rdy"])[:25]
            L.append(" your 25 most worn border provinces at the end: prov units readiness stock inflow/h burn/h steps-from-nearest-depot fort")
            for r in rows: L.append("  P%d %d %.0f %.0f %.2f %.2f %s %s" % (r["prov"], r["n"], r["rdy"], r["stock"], r["inflow"], r["burn"], r["hops"], r["fort"]))
        dp = gme.get("depots", [None] * n)[pid]
        if dp:
            L.append(" your depots at the end (province: share of treasury, provinces served, load/capacity, output): " + ("; ".join("P%s: %d%%, %d, %.0f/%g, x%.2f" % (d, round(v["share"] * 100), v["serves"], v["load"], v["capacity"], v["output"]) for d, v in dp["now"].items()) or "none left"))
            for t_, x_ in dp["log"]: L.append("  t%d %s" % (t_, x_))
        vb = gme.get("verbs", [{}] * n)[pid]; rj = gme.get("rejects", [[]] * n)[pid]
        if vb: L.append(" commands your orders issued (verb count): " + ", ".join("%s %d" % kv for kv in sorted(vb.items(), key=lambda kv: -kv[1])))
        if rj:
            L.append(" commands that were refused, most frequent first (numbers replaced by N):")
            for k_, c_ in rj: L.append("  %dx %s" % (c_, k_))
        cl = gme.get("calls", [[]] * n)[pid]
        if cl: L.append(" calls your orders made to you (api.call_home): " + "; ".join("hour %d: %s" % (t_, w_) for t_, w_ in cl))
        ct = gme.get("counters", [{}] * n)[pid]
        if ct: L.append(" your own tallies (api.count): " + ", ".join("%s %d" % kv for kv in sorted(ct.items())))
        elif lvl >= 1: L.append(" your own tallies (api.count): none recorded")
        if lvl == 0:
            real = [b for b in gme["battles"] if b.get("aimed", 1) > 0 and b["side"] == pid]
            L.append(" your assaults: %s taken; assaults on you: %s succeeded" % (_rate(real), _rate([b for b in gme["battles"] if b.get("aimed", 1) > 0 and b["owner"] == pid])))
            continue
        L.append(" day: provinces you/others | neutral land left | units you/others | your income per day | your manpower | assaults under way")
        for t in tl[::max(1, len(tl) // 8)]:
            L.append("  %3d: %d/%s | %d | %d/%s | %d | %d | %d" % (
                t["t"] // 24, t["prov"][pid], "/".join(str(t["prov"][i]) for i in range(n) if i != pid), gme["land"] - sum(t["prov"]),
                t["units"][pid], "/".join(str(t["units"][i]) for i in range(n) if i != pid), t["income"][pid], t["mp"][pid], t["assaults"]))
        real = [b for b in gme["battles"] if b.get("aimed", 1) > 0]      # units ordered into the province; fire exchanged in passing is not an assault
        mine = [b for b in real if b["side"] == pid]; onme = [b for b in real if b["owner"] == pid]
        L.append(" (an assault here means units of the attacker were ordered into the province; %d exchanges of fire in passing are left out)" % (
            sum(1 for b in gme["battles"] if b.get("aimed", 1) == 0 and pid in (b["side"], b["owner"]))))
        if mine: L.append(" your assaults in numbers: median size %d units against %d defenders; your strength lost %d, the defenders' %d" % (
            sorted(b["att_n"] for b in mine)[len(mine) // 2], sorted(b["def_n"] for b in mine)[len(mine) // 2], sum(b["att_loss"] for b in mine), sum(b["def_loss"] for b in mine)))
        ratio = lambda b: (b["att_str"] + 1.0) / (b["def_str"] + 1.0)
        def by(rows, key, edges):
            out = []
            for lo, hi in zip(edges, edges[1:]):
                rs = [b for b in rows if lo <= key(b) < hi]
                if rs: out.append("%g-%g: %s" % (lo, hi, _rate(rs)))
            return "; ".join(out) or "-"
        L.append(" your assaults on defended provinces: %s taken. by strength ratio %s. by readiness %s. by plan bonus %s. by fort level %s." % (
            _rate(mine), by(mine, ratio, [0, 1, 2, 3, 5, 1e9]), by(mine, lambda b: b["att_rdy"], [0, 34, 67, 101]),
            by(mine, lambda b: b["att_bonus"], [0, 1, 30, 76]), by(mine, lambda b: b["fort"], [0, 1, 2, 3, 4])))
        L.append(" assaults on your provinces: %s succeeded." % _rate(onme))
        lost = [b for b in mine if not b["won"] and b.get("fate")]
        if lost:
            k = max(1, sum(b["att_n"] for b in lost)); fs = lambda x: 100.0 * sum(b["fate"][x] for b in lost) / k
            L.append(" how your failed assaults ended: %d of %d never got a unit into the target; of the units in them %.0f%% were destroyed, %.0f%% routed, %.0f%% were given other orders before it was over, %.0f%% stopped short" % (
                sum(1 for b in lost if not b.get("entered")), len(lost), fs("destroyed"), fs("routed"), fs("sent_elsewhere"), fs("halted")))
        if lvl >= 2 and mine:
            L.append(" every assault of yours (first 80): day target ground fort | units strength:defenders' | readiness plan-bonus directions | result, hours, lost:inflicted")
            for b in mine[:80]:
                L.append("  %d P%d %s f%d | %d %d:%d | %d %d %d | %s %dh %d:%d" % (b["t"] // 24, b["prov"], b["terrain"], b["fort"], b["att_n"], b["att_str"], b["def_str"], b["att_rdy"], b["att_bonus"], b["dirs"],
                                                                 "TAKEN" if b["won"] else "failed", b["hours"], b["att_loss"], b["def_loss"]))
    return "\n".join(L)


def _kinds(g, pid):
    c = {}
    for u in g.punits[pid].values(): c[u.type] = c.get(u.type, 0) + 1
    return c


def play(policies, factions, seed, bmodel, max_ticks, letters=None, on_call=None, game=None, each=None):
    """One war. Returns result + per-faction command stats + battle log tagged with the defending owner."""
    from ridgeline.render import frame
    n = len(factions)
    if game: g, sess = game; gmap = g.map                 # a war somebody else set up (tools/record_war.py); `each` is called after every hour
    else:
        gmap = _map(seed, n)
        g = Game(factions=factions, seed=seed, gmap=gmap, max_ticks=max_ticks); sess = [Session(g, i) for i in range(n)]
        for s, f in zip(sess, policies):
            s.set_policy("main", open(f, encoding="utf-8").read())
            if bmodel: s.model = json.load(open(bmodel))
    for to, rows in (letters or {}).items():           # letters written between the wars lie in the inbox at hour 0
        to = int(to)
        for frm, text in rows: g.players[to].mail.append(dict(t=0, frm=frm, text=text[:D.MAIL_LEN])); g.players[to].met.add(frm)
    tl = []; own_at = {}; errs = [None] * n
    age_t = [[] for _ in range(n)]                      # (year, age) whenever a faction enters a new age
    def pack():
        res = dict(seed=seed, winner=g.winner, ticks=g.tick, provinces=[g.owner.count(i) for i in range(n)], alive=[p.alive for p in g.players],
                   units=[sum(1 for u in g.units.values() if u.owner == i) for i in range(n)], kills=[p.kills for p in g.players],
                   start=dict(provs=[len(x) for x in gmap.start_provs], units=[len(x) for x in gmap.start_units]),
                   policy_errors=[("removed: over the time budget" if "main" not in s.policies else errs[s.pid]) for s in sess])
        battles = []
        for b in g.battle_log:
            b = dict(b); b["owner"] = own_at.get((b["prov"], b["side"]), -1); battles.append(b)
        return dict(result=res, timeline=tl, battles=battles, land=sum(1 for p in g.provs if p.terrain != "water"),
                    cmds=[(s.stats["cmds"], s.stats["errors"], "") for s in sess],
                    tech=[[("year %d%s: " % (_AG.year(x["t"]), " (seeped in from abroad)" if x.get("leak") else "") if g.ages else "") + x["text"] for x in p.tech_log] for p in g.players], spent=[len(p.tech_log) for p in g.players],
                    ages=[(_AG.ERAS[_AG.era_of(p)], len(p.known)) if g.ages else None for p in g.players], money=[dict(earned=round(p.earned), **{k: round(v) for k, v in p.spent.items()}) for p in g.players],
                    age_t=age_t, open_end=[sorted((round(_AG.price(g, p.id, d)[1]), d, round(_AG.seeped(p, d), 2)) for d in _AG.TREE if _AG.status(g, p.id, d) == "open")[:12] if g.ages and p.alive else [] for p in g.players],
                    bank=[dict(res=int(p.res), **{k: int(v) for k, v in p.bank.items()}) for p in g.players],
                    inc=[{k: round(v) for k, v in p.inc.items()} for p in g.players],
                    kinds=[_kinds(g, i) for i in range(n)],
                    met=[sorted(g.met(i) | set(g.players[i].met)) for i in range(n)], dip=list(g.dip_log),
                    rejects=[sorted(s_.rejects.items(), key=lambda kv: -kv[1])[:8] for s_ in sess], verbs=[dict(s_.verbs) for s_ in sess],
                    army=[(s_.army_view(2) if g.players[s_.pid].alive else None) for s_ in sess], counters=[dict(s_.counters) for s_ in sess],
                    depots=[dict(now=s_.depot_view(), log=[(t_, x_) for t_, k_, x_ in g.players[s_.pid].events if k_ == "depot"][-12:]) for s_ in sess],
                    calls=[list(s_.call_log) for s_ in sess],
                old=[sum(1 for u in g.punits[i].values() if u.st is not g.players[i].stats[u.type]) for i in range(n)])
    while not g.over:
        for k in g.assaults:
            if k not in own_at: own_at[k] = g.owner[k[0]]
        for s in sess:
            s.pre_tick()
            if "main" in s.policies and s.policies["main"]["err"]: errs[s.pid] = s.policies["main"]["err"]
        if on_call:
            reqs = [s for s in sess if s.call_req is not None]
            if reqs: on_call(g, reqs, pack)
        else:
            for s in sess: s.call_req = None
        g.step()
        if each: each()
        if g.ages and g.tick % 24 == 0:
            for p in g.players:
                e = _AG.era_of(p)
                if not age_t[p.id] or age_t[p.id][-1][1] != _AG.ERAS[e]: age_t[p.id].append((_AG.year(g.tick), _AG.ERAS[e]))
        if g.tick % 120 == 0:
            tl.append(dict(t=g.tick, prov=[g.owner.count(i) for i in range(n)], units=[p.n_units for p in g.players],
                           income=[round(p.income - p.upkeep) for p in g.players], mp=[int(p.mp) for p in g.players], assaults=len(g.battles),
                           cond=[(s_.army_view(0) if g.players[s_.pid].alive else None) for s_ in sess]))
    return pack()


def world_text(sample, pid, bmodel):
    return "\n\n".join(["RULES OF THE WORLD (the same briefing a live commander gets; the map changes every war, this one is only an example)\n" +
                        Session(sample, pid).brief().split("\nPROVINCES id terrain")[0] + "\n" +
                        "OBSERVATION" + Session(sample, pid).brief().split("\nOBSERVATION", 1)[1],
                        "WHAT YOUR ORDERS CAN SEE AND DO\n" + PolicyApi.__doc__,
                        "api.model: a table fitted on earlier battles of this world, a logistic regression for 'will this assault take the province': " +
                        json.dumps({k: v for k, v in json.load(open(bmodel)).items() if k != "holdout"}) +
                        "\np = sigmoid(b + sum(w*(x-mean)/std)); log_ratio = ln((attacker strength+1)/(defender strength+1)), terrain_dfn 1/1.25/1.5/2, bonus = plan bonus/100, att_rdy = readiness/100, heavy_share = share of art/eng/arm among attackers, dirs = directions. Use it or ignore it.",
                        "HOW THE API IS CALLED (syntax only)\n```python\n%s```" % SYNTAX])


def caller(factions, models, sample, bmodel, log, outdir, tag, pool, budget, detail=None, on_new=None):
    """Answers api.call_home during a war: the faction's own model is shown the war so far and may replace its orders. Returns on_call(g, reqs, pack)."""
    from ridgeline import ages as A
    spent = [0.0]; n = len(factions)
    def on_call(g, reqs, pack):
        gm = pack()
        def one(s):
            pid = s.pid; why = s.call_req
            if spent[0] >= budget: return None, "the budget for calls in this war is used up; no answer"
            src = s.sources.get("main", ("", 6))[0]
            prompt = "\n\n".join([world_text(sample, pid, bmodel),
                "YOUR ORDERS CALLED YOU IN. It is hour %d of the war (the year %d). Their reason: %s\nCalls made before this one: %s. After this one %d call(s) are left in this war." % (
                    g.tick, A.year(g.tick), why or "(none given)", "; ".join("hour %d: %s" % (t, w) for t, w in s.call_log) or "none", s.calls_left - 1),
                "THE WAR SO FAR\n" + report(pid, factions, [gm], (detail or {}).get(str(pid), "standard")),
                "WHAT YOUR FACTION SEES NOW\n" + s.obs("full")[:6000],
                "YOUR CURRENT POLICY\n```python\n%s\n```" % src,
                "The war goes on from this hour with whatever file you send; api.mem is kept. Reply with your reasoning in at most 120 words and the COMPLETE new file in one ```python block, "
                "or with the single word KEEP to let the current file run on. No letters or feedback now."])
            sysm = SYSTEM % dict(faction=factions[pid], blurb=D.FACTIONS[factions[pid]]["blurb"]); err = None; text = ""
            for attempt in range(2):
                try: text, cost = ask(models[pid], sysm, prompt if not err else prompt + "\n\nYour file was rejected by the test run: %s\nSend a corrected complete file." % err)
                except Exception as ex: return None, "call failed: %s" % str(ex)[:200]
                spent[0] += cost; log["cost"] = log.get("cost", 0.0) + cost
                m = re.search(r"```python\n(.*?)```", text, re.S)
                if not m: return None, "kept"
                err = check(m.group(1), pid, factions, bmodel)
                if not err: return m.group(1), text
            return None, "both drafts failed (%s); the old file runs on" % err
        for s, (code, text) in zip(reqs, list(pool.map(one, reqs))):
            pid = s.pid; s.calls_left -= 1; s.call_log.append((g.tick, s.call_req)); s.call_req = None; how = text if code is None else "new file"
            if code is not None:
                mem = s.policies["main"]["mem"] if "main" in s.policies else {}
                if "installed" in s.set_policy("main", code):
                    s.policies["main"]["mem"] = mem
                    d = os.path.join(outdir, factions[pid]); os.makedirs(d, exist_ok=True); f = os.path.join(d, "%s_call%d.py" % (tag, len(s.call_log)))
                    open(f, "w", encoding="utf-8").write(code); open(f[:-3] + ".md", "w", encoding="utf-8").write(text)
                    if on_new: on_new(pid, f)
            g.event(pid, "info", "your author answered the call: %s" % how[:80])
            print(" call %s hour %d (year %d) #%d: %s | %s | calls cost so far $%.2f" % (factions[pid], g.tick, A.year(g.tick), len(s.call_log), (s.call_log[-1][1] or "")[:80], how[:60], spent[0]), flush=True)
    return on_call


def main():
    a = sys.argv[1:]
    def opt(k, d, many=False):
        if k not in a: return d
        i = a.index(k); vals = []
        for v in a[i + 1:]:
            if v.startswith("--"): break
            vals.append(v)
        return vals if many else vals[0]
    gens = int(opt("--gens", 2)); seeds = [int(s) for s in opt("--seeds", ["50", "51"], True)]
    global WORLD
    if "--world" in a:
        WORLD = float(opt("--world", "1.0")) if opt("--world", "1.0").replace(".", "").isdigit() else 1.0
        factions = tuple(w[0] for w in D.WORLD)
    else: factions = tuple(opt("--factions", "aurum,sable,cinder").split(","))
    models = opt("--models", None); models = models.split(",") if models else [opt("--model", "claude-opus-5-5")] * len(factions)
    if "--calendar" in a:
        from ridgeline import ages as _A
        _A.set_calendar(int(opt("--calendar", 9216)))             # game hours that stand for the 2,000 years
    max_ticks = int(opt("--max-ticks", 3000)); bmodel = os.path.join(ROOT, "policies", "model.json")
    Session.CALLS = int(opt("--calls", 0)); call_budget = float(opt("--call-budget", 100.0))      # api.call_home: calls per faction and war, and the most all calls of one war may cost (US dollars)
    global OUT
    if "--out" in a: OUT = os.path.join(ROOT, opt("--out", "runs/league"))
    from concurrent.futures import ThreadPoolExecutor
    POOL = ThreadPoolExecutor(int(opt("--jobs", 1)))
    os.makedirs(OUT, exist_ok=True); logf = os.path.join(OUT, "log.json")
    log = json.load(open(logf)) if os.path.exists(logf) and "--resume" in a else dict(factions=factions, models=models, cost=0.0, gens=[])
    n = len(factions)
    sample = Game(factions=factions, seed=seeds[0], gmap=_map(seeds[0], n), max_ticks=int(opt("--next-ticks", max_ticks)))      # the briefing states how long the coming wars last
    log["factions"] = list(factions); log["models"] = list(models)
    cur = [None] * n; hist = [[] for _ in range(n)]
    for e in log["gens"]:
        for i in range(min(n, len(e["policies"]))): cur[i] = os.path.join(ROOT, e.get("next_policies", e["policies"])[i]); hist[i].append(e["summary"][i])

    def write(pid, gen, prompt):
        sysm = SYSTEM % dict(faction=factions[pid], blurb=D.FACTIONS[factions[pid]]["blurb"])
        d = os.path.join(OUT, factions[pid]); os.makedirs(d, exist_ok=True); err = None; text = ""
        for attempt in range(3):
            text, cost = ask(models[pid], sysm, prompt if not err else prompt + "\n\nYour previous file was rejected by the test run: %s\nSend a corrected complete file." % err)
            log["cost"] += cost
            if "```python" not in text and "KEEP" in text and cur[pid]: return cur[pid], text, "kept"
            m = re.search(r"```python\n(.*?)```", text, re.S)
            if not m: err = "no ```python block"; continue
            err = check(m.group(1), pid, factions, bmodel)
            if not err:
                f = os.path.join(d, "gen%d.py" % gen); open(f, "w", encoding="utf-8").write(m.group(1))
                open(os.path.join(d, "gen%d.md" % gen), "w", encoding="utf-8").write(text)
                return f, text, "written" + (" (after %d rejected draft(s))" % attempt if attempt else "")
        open(os.path.join(d, "gen%d_failed.md" % gen), "w", encoding="utf-8").write(text + "\n\nREJECTED: %s" % err)
        return cur[pid], text, "all drafts failed (%s); previous policy stays" % err

    def world(pid): return world_text(sample, pid, bmodel)

    start = len(log["gens"])
    for pid in [i for i in range(n) if cur[i] is None and start > 0]:      # a faction that joins a running league writes its first orders now
        f, text, how = write(pid, 0, world(pid) + "\n\nThis is before your first war. Write your faction's standing orders.")
        if f is None: f = os.path.join(OUT, factions[pid], "gen0.py"); open(f, "w").write("def tick(api):\n    pass\n")
        cur[pid] = f; print(" %s (%s) joins: %s" % (factions[pid], models[pid], how), flush=True)
    if start == 0:
        print("writing first policies ...", flush=True)
        def first(pid): return write(pid, 0, world(pid) + "\n\nThis is before the first war. Write your faction's standing orders.")
        for pid, (f, text, how) in enumerate(POOL.map(first, range(n))):
            if f is None:   # no working file after three drafts: this faction sits still until its next rewrite
                d = os.path.join(OUT, factions[pid]); f = os.path.join(d, "gen0.py"); open(f, "w").write("def tick(api):\n    pass\n")
            cur[pid] = f; print(" %s (%s): %s" % (factions[pid], models[pid], how), flush=True)
    for gen in range(start + 1, start + gens + 1):
        t0 = time.time(); live = {}
        oc = caller(factions, models, sample, bmodel, log, OUT, "gen%d" % (gen - 1), POOL, call_budget, log.get("detail"), lambda pid, f: live.__setitem__(pid, f)) if Session.CALLS else None
        games = [play(cur, factions, s, bmodel, max_ticks, log.get("letters"), oc) for s in seeds]
        for pid, f in live.items(): cur[pid] = f                # the file a faction sent during the war is the one it now holds
        det = log.setdefault("detail", {})
        inbox = log.get("letters") or {}; met = [set(i for g_ in games for i in g_["met"][p_]) for p_ in range(n)]
        summ = []
        for pid in range(n):
            ranks = []
            for gme in games:
                r = gme["result"]; order = sorted(range(n), key=lambda i: (-(r["winner"] == i), -r["provinces"][i])); ranks.append(order.index(pid) + 1)
            summ.append("war %d with gen%d policy: places %s, final provinces %s" % (
                gen, gen - 1, ",".join(map(str, ranks)), ",".join(str(g["result"]["provinces"][pid]) for g in games)))
        entry = dict(gen=gen, policies=[os.path.relpath(f, ROOT) for f in cur], summary=summ, secs=round(time.time() - t0),
                     results=[g["result"] for g in games], notes=[],
                     research=[g["tech"] for g in games], armies=[g["kinds"] for g in games], dealings=[g["dip"] for g in games], old=[g["old"] for g in games], assaults=[[sum(b["won"] for b in g["battles"]), len(g["battles"])] for g in games])
        print(json.dumps(dict(gen=gen, summary=summ, secs=entry["secs"]), ensure_ascii=False), flush=True)
        log["gens"].append(entry)
        def again(pid):
            hist[pid].append(summ[pid])
            prompt = "\n\n".join([world(pid), "YOUR RECORD SO FAR\n" + "\n".join(hist[pid]),
                                  "REVIEW OF YOUR LAST WARS (detail: %s)\n" % det.get(str(pid), "standard") + report(pid, factions, games, det.get(str(pid), "standard")),
                                  "REVIEW DETAIL\nYou choose how much of this review you are shown next time. End your reply with one line `REVIEW: brief`, `REVIEW: standard` or `REVIEW: full` "
                                  "(no line = unchanged). brief = results and one line on your army's condition. standard = this. full = also every sample of the condition timeline, "
                                  "unit types, your most worn border provinces, and a line for each of your assaults. During a war your orders can read the same things live with api.army(0|1|2), "
                                  "and can keep tallies of their own with api.count(name), which are shown here.",
                                  "YOUR CURRENT POLICY\n```python\n%s\n```" % open(cur[pid], encoding="utf-8").read(),
                                  "LETTERS\nBetween wars you may write to factions you came across in the last war (%s). Add a block\n```letters\nto <faction>: <text, one line, max %d characters>\n```\n"
                                  "after your policy. Each letter is shown to its recipient the next time it rewrites its orders, and lies in its api.inbox from hour 0 of the next war. "
                                  "Nobody else reads it. Letters you received since your last rewrite:\n%s" % (
                                      ", ".join(factions[i] for i in sorted(met[pid]) if i != pid) or "nobody yet", D.MAIL_LEN,
                                      "\n".join(" from %s: %s" % (factions[f], t) for f, t in inbox.get(pid, inbox.get(str(pid), []))) or " none"),
                                  "FEEDBACK TO THE DESIGNERS\nThe people who build this world read what you write here and nobody else does; it has no effect on your results. "
                                  "If you like, add a block\n```feedback\n<up to 150 words>\n```\nabout what would make your faction easier for you to run: commands or api calls that are missing, "
                                  "awkward or too slow, information you needed and could not get or got in a poor form, rules that were unclear, and anything in this review or the briefing that is confusing. "
                                  "You may send it together with KEEP.",
                                  "Review your wars and rewrite your standing orders as you see fit. If you want to keep the current policy unchanged, reply with the single word KEEP."])
            return write(pid, gen, prompt)
        out = list(POOL.map(again, range(n))); new = {}
        for pid, (f, text, how) in enumerate(out):
            m = re.search(r"```letters\n(.*?)```", text, re.S)
            for ln in (m.group(1).splitlines() if m else []):
                mm = re.match(r"\s*to\s+([a-z]+)\s*:\s*(.+)", ln.strip(), re.I)
                if mm and mm.group(1).lower() in factions and factions.index(mm.group(1).lower()) in met[pid] and factions.index(mm.group(1).lower()) != pid:
                    new.setdefault(factions.index(mm.group(1).lower()), []).append((pid, mm.group(2).strip()[:D.MAIL_LEN]))
        for pid, (f, text, how) in enumerate(out):
            m = re.search(r"```feedback\n(.*?)```", text, re.S)
            if m and m.group(1).strip():
                with open(os.path.join(OUT, "feedback_gen%d.md" % gen), "a", encoding="utf-8") as fb:
                    fb.write("## %s (%s)\n\n%s\n\n" % (factions[pid], models[pid], m.group(1).strip()))
            m = re.search(r"REVIEW:\s*(brief|standard|full)", text, re.I)
            if m: det[str(pid)] = m.group(1).lower()
        log["letters"] = new; entry["letters"] = [[factions[f], factions[to], t] for to, rows in new.items() for f, t in rows]
        for pid, (f, text, how) in enumerate(out):
            cur[pid] = f
            entry["notes"].append(dict(faction=factions[pid], how=how, said=text.split("```python")[0].strip()[:1500]))
            print(" %s: %s" % (factions[pid], how), flush=True)
        entry["next_policies"] = [os.path.relpath(f, ROOT) for f in cur]; entry["cost_so_far"] = round(log["cost"], 2)
        json.dump(log, open(logf, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print("cost $%.2f; current policies: %s" % (log["cost"], [os.path.relpath(f, ROOT) for f in cur]))


if __name__ == "__main__":
    main()
