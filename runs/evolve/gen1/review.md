**Review:** The same policy wins as P1 (3/3) but loses as P0 (0/3). P0's Aurum Compact is slower, so we lose the tempo war, and seed 31 collapsed to 13 provinces. Our assaults succeed only 28/130. They average 1.2 directions and readiness 36, and most have no plan bonus. Attacks with a plan bonus of 45% or more succeed 11/27 at a loss of 57 per assault. Attacks with 25% or less succeed 16/97. Attacks at a strength ratio under 1.5 almost always fail. We are bleeding strength into piecemeal, tired attacks, while the enemy wins its own assaults mostly at ratios of 2 or more.

**Changes:**
- Only rested units (readiness 55 or more, strength 70 or more) may start an attack.
- Attacks are almost always prepared first. They launch at a bonus of 45% or more, or at very high predicted odds.
- At most 4 prepared attacks run at once, so strength concentrates instead of spreading thin.
- Stale preparations stand down after 120 h.
- Unit mix: no more militia, with more infantry, artillery and engineers.
- Everything else stays under the `front` order, which digs in and rotates worn units.

```python
DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
GO = 0.85
PLAN = 0.55
LAUNCH = 0.50
MAXPREP = 4


def p_win(api, t, us, bonus):
    P = api.provs; e = api.enemy.get(t); es = e["str"] if e else 0.0
    mine = sum(u["str"] for u in us)
    m = api.model
    if not m or "w" not in m:
        return 0.9 if mine > es * DFN[P[t]["terrain"]] * (1 + 0.3 * P[t]["fort"]) * 1.5 else 0.1
    heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / max(1, len(us))
    x = [math.log((mine + 1.0) / (es + 1.0)), DFN[P[t]["terrain"]], P[t]["fort"], 1 if P[t]["city"] else 0, bonus / 100.0,
         sum(u["rdy"] for u in us) / max(1, len(us)) / 100.0, heavy, len(set(u["prov"] for u in us))]
    z = m["b"] + sum(w * (v - a) / s for w, v, a, s in zip(m["w"], x, m["mean"], m["std"]))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def tick(api):
    P = api.provs; U = api.units; mem = api.mem
    n = len(U); high = sum(1 for i, pr in P.items() if pr["owner"] == "me" and pr["terrain"] in ("hill", "mountain"))
    mix = ["inf", "inf", "art", "inf", "eng", "arm", "inf", "art", "mot", "inf", "rec" if n < 60 else "inf", "art"]
    if high >= 6: mix += ["mtn", "mtn", "mtn"]
    k = mem.get("k", 0); res = api.res; mp = api.mp
    cities = [i for i, pr in P.items() if pr["owner"] == "me" and pr["city"] and pr["supplied"]]
    while cities and api.income > -5:
        code = mix[k % len(mix)]
        if mp < api.costs[code][1] + 30:
            code = "arm" if res >= api.costs["arm"][0] + 10 and mp >= api.costs["arm"][1] + 30 else None
        if code is None or res < api.costs[code][0] + 10: break
        if not api.cmd("recruit %s P%d" % (code, cities[k % len(cities)])).startswith("ok"): break
        res -= api.costs[code][0]; mp -= api.costs[code][1]; k += 1
    mem["k"] = k
    loose = [u["id"] for u in U if not u["front"] and not u["path"] and not u["fighting"] and u["plan"] < 0]
    if loose: api.cmd("front %s" % ",".join(map(str, loose)))
    if api.t % 12: return
    prep = {}; t0 = mem.setdefault("prep_t", {})
    for u in U:
        if u["plan"] >= 0 and not u["path"] and not u["fighting"]:
            if u["str"] < 45 or P[u["plan"]]["owner"] == "me": api.cmd("hold %d" % u["id"])
            else: prep.setdefault(u["plan"], []).append(u)
    for t, us in list(prep.items()):
        b = sum(u["bonus"] for u in us) / len(us); p = p_win(api, t, us, b); age = api.t - t0.get(t, api.t)
        ids = ",".join(str(u["id"]) for u in us)
        if p >= GO or (b >= 45 and p >= LAUNCH):
            api.cmd("move %s P%d" % (ids, t)); t0.pop(t, None)
        elif age > 120:
            api.cmd("front %s" % ids); t0.pop(t, None)
    by = {}
    for u in U:
        if not u["path"] and not u["fighting"] and u["str"] >= 70 and u["rdy"] >= 55 and u["plan"] < 0:
            by.setdefault(u["prov"], []).append(u)
    used = set()
    for b, us in by.items():
        for nb in P[b]["nbrs"]:
            if P[nb]["owner"] == "neutral" and nb not in api.enemy and len(us) - sum(1 for u in us if u["id"] in used) >= 2:
                u = next(u for u in us if u["id"] not in used); used.add(u["id"])
                api.cmd("move %d P%d" % (u["id"], nb)); P[nb]["owner"] = "claimed"
    slots = MAXPREP - len(prep)
    if slots <= 0: return
    targets = set(nb for b in by for nb in P[b]["nbrs"] if P[nb]["owner"] == "enemy")
    scored = []
    for t in targets:
        if t in prep: continue
        near = [u for b in P[t]["nbrs"] if b in by for u in by[b][1:] if u["id"] not in used]
        if len(near) < 2: continue
        near.sort(key=lambda u: -u["str"] * (1.5 if u["type"] in ("art", "arm") else 1.0))
        pp = p_win(api, t, near, 50)
        if pp < PLAN: continue
        value = P[t]["y"] + (15 if t == api.enemy_capital else 0) + (3 if P[t]["city"] else 0) + 1
        scored.append((pp * value, t, near))
    for sc, t, near in sorted(scored, key=lambda s: -s[0]):
        if slots <= 0: break
        ids = [u for u in near if u["id"] not in used]
        if len(ids) < 2: continue
        kk = len(ids)
        while kk > 2 and p_win(api, t, ids[:kk - 1], 50) >= 0.8: kk -= 1
        ids = ids[:kk]
        if p_win(api, t, ids, 50) < PLAN: continue
        used.update(u["id"] for u in ids); sel = ",".join(str(u["id"]) for u in ids)
        if p_win(api, t, ids, 0) >= GO: api.cmd("move %s P%d" % (sel, t))
        else:
            api.cmd("prepare %s P%d" % (sel, t)); t0[t] = api.t
        slots -= 1
```