**Review:** We won only 3 of 6 games, all as P1. As P0 we lost every seed, and in seed 31 we were overrun (13 provinces vs 185).

- **Assaults:** 28 of 130 succeeded. Most were weak attacks: 63 had readiness under 25, 114 came from a single direction, and 81 had no plan bonus.
- **What worked:** attacks with plan bonus of 45% or more won 11 of 27 at very low loss (57 per assault), and high readiness cut losses. The current policy launches too many unprepared, low-readiness attacks. That bleeds units, which then lose to the enemy's larger stacks.
- **Defence:** enemy assaults won 68 of 175, mostly at ratios of 2 or more against our thin line.

**Changes:**
- Attack only with rested units (strength 70+, readiness 50+), and always prepare first.
- Launch only at a plan bonus of 45%+ and a model chance of 0.6+, or at 0.85+ with any bonus.
- Drop the plan after 120 hours if the model still says no.
- Raise the attack thresholds (GO 0.85, PLAN 0.6) and keep two units back in each province.
- Recruit more art, eng, mtn and inf, and fewer mil and rec.
- Units under 55 strength return to the front order, which has them dig in and rotate to rest.

```python
DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
GO = 0.85
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
    n = len(U)
    high = sum(1 for i, pr in P.items() if pr["owner"] == "me" and pr["terrain"] in ("hill", "mountain"))
    mix = ["inf", "art", "inf", "eng", "inf", "art", "mot", "inf", "arm", "inf", "art", "inf"]
    if high >= 6: mix += ["mtn", "mtn", "mtn"]
    k = mem.get("k", 0); res = api.res; mp = api.mp
    cities = [i for i, pr in P.items() if pr["owner"] == "me" and pr["city"] and pr["supplied"]]
    guard = 0
    while cities and api.income > -5 and guard < 20:
        guard += 1
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
            if u["str"] < 55 or P[u["plan"]]["owner"] == "me":
                api.cmd("front %d" % u["id"])
            else:
                prep.setdefault(u["plan"], []).append(u)
    for t, us in prep.items():
        b = sum(u["bonus"] for u in us) / len(us)
        p = p_win(api, t, us, b)
        age = api.t - t0.get(t, api.t)
        if (b >= 45 and p >= PLAN) or p >= GO:
            api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in us), t)); t0.pop(t, None)
        elif age > 120:
            api.cmd("front %s" % ",".join(str(u["id"]) for u in us)); t0.pop(t, None)
    by = {}
    for u in U:
        if not u["path"] and not u["fighting"] and u["str"] >= 70 and u["rdy"] >= 50 and u["plan"] < 0:
            by.setdefault(u["prov"], []).append(u)
    used = set()
    for b, us in by.items():
        for nb in P[b]["nbrs"]:
            if P[nb]["owner"] == "neutral" and nb not in api.enemy and len(us) - sum(1 for u in us if u["id"] in used) >= 3:
                u = next(u for u in us if u["id"] not in used); used.add(u["id"])
                api.cmd("move %d P%d" % (u["id"], nb)); P[nb]["owner"] = "claimed"
    targets = set(nb for b in by for nb in P[b]["nbrs"] if P[nb]["owner"] == "enemy")
    scored = []
    for t in targets:
        if t in prep: continue
        near = [u for b in P[t]["nbrs"] if b in by for u in by[b][2:] if u["id"] not in used]
        if not near: continue
        near.sort(key=lambda u: -u["str"] * (1.5 if u["type"] in ("art", "arm") else 1.0))
        p_plan = p_win(api, t, near, 50)
        if p_plan < PLAN: continue
        value = P[t]["y"] + (15 if t == api.enemy_capital else 0) + (3 if P[t]["city"] else 0) + 1
        scored.append((p_plan * value, t, near))
    for sc, t, near in sorted(scored, key=lambda s: -s[0]):
        ids = [u for u in near if u["id"] not in used]
        if not ids: continue
        kk = len(ids)
        while kk > 1 and p_win(api, t, ids[:kk - 1], 50) >= 0.85: kk -= 1
        ids = ids[:kk]
        if p_win(api, t, ids, 50) < PLAN: continue
        used.update(u["id"] for u in ids); sel = ",".join(str(u["id"]) for u in ids)
        api.cmd("prepare %s P%d" % (sel, t)); t0[t] = api.t
```