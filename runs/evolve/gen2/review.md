**Review:** We won 3 of 6 games, all as P1; as P0 we lost every seed. Our assaults succeed only 28 of 130 times, and the enemy takes 68 of its 175 assaults on us.

- Most of our attacks go in unprepared: 81 of the 130 had under 1% plan bonus and won 8.
- Attacks with 45% or more plan bonus won 11 of 27 and lost very little strength.
- Attackers' readiness averaged 36, and 17 of the 63 attacks below readiness 25 succeeded.
- Almost every attack came from one direction, and the model flags forts and multiple directions as important.
- Fort level 3 attacks lost 501 strength each.
- Attacks backed by under 30 supplies lost 441 per assault.

**Changes:**
- Attack only with rested units (readiness 60+, strength 70+).
- Always prepare first, and launch at 45%+ bonus or when the model is confident at the current bonus.
- Raise the attack thresholds, and skip fort 3 targets unless artillery or engineers are in the stack.
- Cancel a prepared attack if the model's odds fall.
- Cut mil and rec from recruiting in favour of inf, art, eng and mtn.
- Units idle on the front dig in and rest, which cuts losses to the enemy's assaults.

```python
DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
GO = 0.80
PLAN = 0.60


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
    mix = ["inf", "art", "inf", "eng", "inf", "art", "arm", "inf", "mot", "inf", "art", "eng"]
    if high >= 6: mix += ["mtn", "mtn", "mtn"]
    k = mem.get("k", 0); res = api.res; mp = api.mp
    cities = [i for i, pr in P.items() if pr["owner"] == "me" and pr["city"] and pr["supplied"]]
    while cities and api.income > -5:
        code = mix[k % len(mix)]; c, m = api.costs[code]
        if mp < m + 30:
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
            if u["str"] < 50 or P[u["plan"]]["owner"] == "me": api.cmd("hold %d" % u["id"])
            else: prep.setdefault(u["plan"], []).append(u)
    for t, us in prep.items():
        b = sum(u["bonus"] for u in us) / len(us); p = p_win(api, t, us, b); age = api.t - t0.get(t, api.t)
        ids = ",".join(str(u["id"]) for u in us)
        if p >= GO or (b >= 45 and p >= PLAN):
            api.cmd("move %s P%d" % (ids, t)); t0.pop(t, None)
        elif age > 96 or (b >= 20 and p < 0.3):
            api.cmd("front %s" % ids); t0.pop(t, None)
    by = {}
    for u in U:
        if (not u["path"] and not u["fighting"] and u["str"] >= 70 and u["rdy"] >= 60
                and u["plan"] < 0 and not u["dry"] and u["supplied"]):
            by.setdefault(u["prov"], []).append(u)
    used = set()
    for b, us in by.items():
        for nb in P[b]["nbrs"]:
            if P[nb]["owner"] == "neutral" and nb not in api.enemy and len(us) - sum(1 for u in us if u["id"] in used) >= 2:
                u = next(u for u in us if u["id"] not in used); used.add(u["id"])
                api.cmd("move %d P%d" % (u["id"], nb)); P[nb]["owner"] = "claimed"
    targets = set(nb for b in by for nb in P[b]["nbrs"] if P[nb]["owner"] == "enemy")
    scored = []
    for t in targets:
        if t in prep: continue
        near = [u for b in P[t]["nbrs"] if b in by for u in by[b][1:] if u["id"] not in used]
        if not near: continue
        if P[t]["fort"] >= 3 and not any(u["type"] in ("art", "eng") for u in near): continue
        near.sort(key=lambda u: -u["str"] * (1.5 if u["type"] in ("art", "arm") else 1.0))
        pp = p_win(api, t, near, 50)
        if pp < PLAN: continue
        value = P[t]["y"] + (15 if t == api.enemy_capital else 0) + (3 if P[t]["city"] else 0) + 1
        scored.append((pp * value, t, near))
    for sc, t, near in sorted(scored, key=lambda s: -s[0]):
        ids = [u for u in near if u["id"] not in used]
        if not ids: continue
        kk = len(ids)
        while kk > 1 and p_win(api, t, ids[:kk - 1], 50) >= 0.85: kk -= 1
        ids = ids[:kk]
        if p_win(api, t, ids, 50) < PLAN: continue
        used.update(u["id"] for u in ids); sel = ",".join(str(u["id"]) for u in ids)
        if p_win(api, t, ids, 0) >= 0.9: api.cmd("move %s P%d" % (sel, t))
        else:
            api.cmd("prepare %s P%d" % (sel, t)); t0[t] = api.t
```