"""Same skeleton as basic.py, but attack decisions come from a model learned from earlier battles (api.model,
fitted by tools/fit_battle_model.py on runs/battles.jsonl): attack where the predicted chance of taking the
province is high, prepare first where it is middling, leave the rest alone.

One entry point, tick(api). This is the 'orders written in advance' half of the control model; an agent can
replace it mid-game (Session.set_policy / POST /policy).
"""


DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
GO = 0.70          # predicted success at which we attack straight away
PLAN = 0.45        # predicted success (with a finished plan) worth preparing for


def p_win(api, t, us, bonus):
    """Model's chance that units `us` take province t. Falls back to a plain strength ratio without a model."""
    P = api.provs; e = api.enemy.get(t); es = e["str"] if e else 0.0
    mine = sum(u["str"] for u in us)
    m = api.model
    if not m or "w" not in m: return 0.9 if mine > es * DFN[P[t]["terrain"]] * (1 + 0.3 * P[t]["fort"]) * 1.25 else 0.1
    heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / max(1, len(us))
    x = [math.log((mine + 1.0) / (es + 1.0)), DFN[P[t]["terrain"]], P[t]["fort"], 1 if P[t]["city"] else 0, bonus / 100.0,
         sum(u["rdy"] for u in us) / max(1, len(us)) / 100.0, heavy, len(set(u["prov"] for u in us))]
    z = m["b"] + sum(w * (v - a) / s for w, v, a, s in zip(m["w"], x, m["mean"], m["std"]))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

PREPARE = True      # False = the old behaviour: attack the moment the numbers look good


def tick(api):
    P = api.provs; U = api.units; mem = api.mem
    # --- recruit: spend everything above a small reserve, limited by manpower. Mountain troops if we hold high ground.
    n = len(U); high = sum(1 for i, pr in P.items() if pr["owner"] == "me" and pr["terrain"] in ("hill", "mountain"))
    mix = ["inf", "inf", "art", "inf", "mil", "arm", "inf", "eng", "mot", "inf", "rec" if n < 120 else "inf", "art"]
    if high >= 6: mix += ["mtn", "mtn", "mtn"]
    k = mem.get("k", 0); res = api.res; mp = api.mp
    cities = [i for i, pr in P.items() if pr["owner"] == "me" and pr["city"] and pr["supplied"]]
    while cities and api.income > -5:
        code = mix[k % len(mix)]; c, m = api.costs[code]
        if mp < m + 30: code = "arm" if res >= api.costs["arm"][0] + 10 and mp >= api.costs["arm"][1] + 30 else None      # short of men: buy machines
        if code is None or res < api.costs[code][0] + 10: break
        if not api.cmd("recruit %s P%d" % (code, cities[k % len(cities)])).startswith("ok"): k += 1; break        # cannot afford this kind (maybe no steel or oil): try the next kind next time
        res -= api.costs[code][0]; mp -= api.costs[code][1]; k += 1
    mem["k"] = k
    # --- everyone idle and not yet on the front joins it (new recruits, units that finished an attack)
    loose = [u["id"] for u in U if not u["front"] and not u["path"] and not u["fighting"] and u["plan"] < 0]
    if loose: api.cmd("front %s" % ",".join(map(str, loose)))
    if api.t % 12: return
    # --- prepared attacks under way: launch when planned, rested and supplied; give up on worn-out units
    prep = {}; t0 = mem.setdefault("prep_t", {})
    for u in U:
        if u["plan"] >= 0 and not u["path"] and not u["fighting"]:
            if u["str"] < 45 or P[u["plan"]]["owner"] == "me": api.cmd("hold %d" % u["id"])
            else: prep.setdefault(u["plan"], []).append(u)
    for t, us in prep.items():
        b = sum(u["bonus"] for u in us) / len(us); p = p_win(api, t, us, b); age = api.t - t0.get(t, api.t)
        if p >= GO or (b >= 45 and p >= PLAN) or (age > 96 and p >= PLAN):
            api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in us), t)); t0.pop(t, None)
        elif age > 96:                                         # the model says it will not work: stand down
            api.cmd("front %s" % ",".join(str(u["id"]) for u in us)); t0.pop(t, None)
    by = {}
    for u in U:
        if not u["path"] and not u["fighting"] and u["str"] >= 60 and u["plan"] < 0: by.setdefault(u["prov"], []).append(u)
    used = set()
    # --- grab neutral neighbours with one unit each (keeps the front moving outwards)
    for b, us in by.items():
        for nb in P[b]["nbrs"]:
            if P[nb]["owner"] == "neutral" and nb not in api.enemy and len(us) - sum(1 for u in us if u["id"] in used) >= 2:
                u = next(u for u in us if u["id"] not in used); used.add(u["id"])
                api.cmd("move %d P%d" % (u["id"], nb)); P[nb]["owner"] = "claimed"
    # --- attack along the whole front: every enemy province where the units standing next to it outweigh the
    #     (terrain-adjusted, possibly only estimated) defenders. Many of these run at the same time.
    targets = set(nb for b in by for nb in P[b]["nbrs"] if P[nb]["owner"] == "enemy")
    scored = []
    for t in targets:
        if t in prep: continue
        near = [u for b in P[t]["nbrs"] if b in by for u in by[b][1:] if u["id"] not in used]   # one stays in each province
        if not near: continue
        near.sort(key=lambda u: -u["str"] * (1.5 if u["type"] in ("art", "arm") else 1.0))
        p_now = p_win(api, t, near, 0); p_plan = p_win(api, t, near, 50)
        if max(p_now, p_plan) < PLAN: continue
        value = P[t]["y"] + (15 if t == api.enemy_capital else 0) + (3 if P[t]["city"] else 0) + 1
        scored.append((max(p_now, p_plan) * value, t, near, p_now))
    for sc, t, near, p_now in sorted(scored, reverse=True):
        ids = [u for u in near if u["id"] not in used]
        if not ids: continue
        # take only as many as the model needs for a confident attack; the rest can hit elsewhere
        k = len(ids)
        while k > 1 and p_win(api, t, ids[:k - 1], 0) >= 0.9: k -= 1
        ids = ids[:k]; p_now = p_win(api, t, ids, 0)
        if max(p_now, p_win(api, t, ids, 50)) < PLAN: continue
        used.update(u["id"] for u in ids); sel = ",".join(str(u["id"]) for u in ids)
        if p_now >= GO or not PREPARE: api.cmd("move %s P%d" % (sel, t))
        else: api.cmd("prepare %s P%d" % (sel, t)); t0[t] = api.t
