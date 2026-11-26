"""Ablation of basic.py with PREPARE off (attacks at once, never plans). A pre-written faction policy: hold a continuous front, grow the army, attack where locally superior.

One entry point, tick(api). This is the 'orders written in advance' half of the control model; an agent can
replace it mid-game (Session.set_policy / POST /policy).
"""


PREPARE = False     # False = the old behaviour: attack the moment the numbers look good


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
        b = sum(u["bonus"] for u in us) / len(us); r = sum(u["rdy"] for u in us) / len(us)
        st = min(P[u["prov"]]["stock"] for u in us)
        if b >= 45 or (b >= 30 and r >= 75 and st >= 60) or api.t - t0.get(t, api.t) > 120:
            api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in us), t)); t0.pop(t, None)
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
    dfn = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
    targets = set(nb for b in by for nb in P[b]["nbrs"] if P[nb]["owner"] == "enemy")
    scored = []
    for t in targets:
        e = api.enemy.get(t)
        es = (e["str"] if e else 0) * (dfn[P[t]["terrain"]] + (0.25 if P[t]["city"] else 0)) * (1 + 0.3 * P[t]["fort"])
        near = [u for b in P[t]["nbrs"] if b in by for u in by[b][1:] if u["id"] not in used]   # one stays in each province
        mine = sum(u["str"] * (1.5 if u["type"] in ("art", "arm") else 1.0) for u in near)
        if near and mine > es * 1.25:
            bonus = P[t]["y"] * 20 + (300 if t == api.enemy_capital else 0) + (60 if P[t]["city"] else 0)
            scored.append((mine - es * 1.25 + bonus, t, near, es))
    for sc, t, near, es in sorted(scored, reverse=True):
        ids = []; got = 0.0
        for u in sorted(near, key=lambda u: -u["str"]):
            if u["id"] in used: continue
            ids.append(u["id"]); got += u["str"] * (1.5 if u["type"] in ("art", "arm") else 1.0)
            if got > es * 1.8 + 100: break                      # enough for this one; the rest can hit elsewhere
        if ids and got > es * 1.25:
            used.update(ids)
            if PREPARE and t not in prep: api.cmd("prepare %s P%d" % (",".join(map(str, ids)), t)); t0[t] = api.t
            else: api.cmd("move %s P%d" % (",".join(map(str, ids)), t))
