**Plan for Kongo (P19):** Kongo gets +10% attack, so I lean toward offence. The policy expands first, then builds a strike force and attacks only when the numbers look good.

- **Scouting:** two `rec` scouts early, then they keep exploring.
- **Recruitment:** one unit per tick, weighted toward infantry, mountain troops and motorised units early. Armour, artillery and assault troops wait until tick 96 and are limited by steel. A cash reserve protects upkeep.
- **Research:** attack and economy lines first (farming, weapons, mining, conscription), and only with cash to spare.
- **Land and front:** idle units expand to free land and otherwise join the front. Scouts explore. Idle engineers at the border dig in.
- **Attacks:** a `prepare` on a target next to my stack, launched after about 8 hours. It needs at least 1.5× the estimated defence and a win chance of 55% or more, using `api.model` when it is present. I keep at most two attacks pending.
- **Safety:** each step runs in its own try block, so one failure cannot drop the whole tick.

```python
W = {"inf": 0.35, "mil": 0.10, "mtn": 0.08, "mot": 0.08, "art": 0.09,
     "arm": 0.10, "eng": 0.05, "atg": 0.06, "grn": 0.06, "cav": 0.03}
HEAVY = ("arm", "art", "eng", "hvt", "rkt")
RESEARCH = ["farming", "inf.weapons", "arm.weapons", "art.weapons", "mining",
            "conscription", "inf.protection", "logistics", "medicine", "drill",
            "industry", "mot.mobility", "arm.protection", "grn.weapons"]
TDEF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}


def _nbs(pr):
    out = []
    for x in pr.get("nbrs", []) or []:
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, dict):
            if isinstance(x.get("id"), int):
                out.append(x["id"])
        else:
            digits = "".join(c for c in str(x) if c.isdigit())
            if digits:
                out.append(int(digits))
    return out


def _ok(api, t, keep):
    c = api.unit_costs.get(t)
    if not c:
        return False
    if api.res - c.get("res", 0) < keep:
        return False
    if api.mp < c.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) < c.get(k, 0):
            return False
    return True


def _recruit(api):
    if api.income < -5 and api.res < 300:
        return
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    keep = 40 + 3 * len(api.units)
    if counts.get("rec", 0) < 2 and api.t < 400 and _ok(api, "rec", keep):
        api.cmd("recruit rec P%d" % api.capital)
        return
    best = None
    bv = 1e18
    for t, w in W.items():
        if api.t < 96 and t in ("arm", "art", "atg", "grn", "cav"):
            continue
        if not _ok(api, t, keep):
            continue
        v = (counts.get(t, 0) + 1) / w
        if v < bv:
            bv = v
            best = t
    if best:
        api.cmd("recruit %s P%d" % (best, api.capital))


def _research(api):
    if len(api.research) >= 2 or api.res < 250:
        return
    busy = set(r[0] for r in api.research)
    for line in RESEARCH:
        if line in busy:
            continue
        st = api.tech.get(line)
        if not st or st.get("status") in ("dead end", "complete", "researching"):
            continue
        cost = st.get("cost") or {}
        good = True
        for k, v in cost.items():
            if k == "res":
                if api.res - v < 150:
                    good = False
            elif api.stock.get(k, 0) < v:
                good = False
        if good:
            api.cmd("research %s" % line)
            return


def _orders(api):
    n = 0
    for u in api.units:
        if n >= 30:
            break
        if u.get("path") or u.get("plan", -1) != -1:
            continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("fighting"):
            continue
        if u.get("state") not in ("ready", "digging", "refitting"):
            continue
        if u["type"] == "rec":
            api.cmd("explore %d" % u["id"])
        else:
            api.cmd("expand %d" % u["id"])
        n += 1


def _p_take(api, S, D, fort, tdef, rdy, hs, city):
    mdl = api.model or {}
    lr = math.log((S + 1.0) / (D + 1.0))
    if not mdl or "w" not in mdl:
        z = lr * 1.5 - 0.3
    else:
        vals = {"log_ratio": lr, "terrain_dfn": tdef, "fort": fort,
                "city": city, "bonus": 0.0, "att_rdy": rdy / 100.0,
                "heavy_share": hs, "dirs": 1.0}
        z = mdl["b"]
        for i, f in enumerate(mdl["features"]):
            z += mdl["w"][i] * (vals.get(f, 0.0) - mdl["mean"][i]) / mdl["std"][i]
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _attack(api):
    prep = api.mem.setdefault("prep", {})
    for src in list(prep.keys()):
        tgt, t0 = prep[src]
        if api.t - t0 >= 8:
            api.cmd("move @P%d P%d" % (src, tgt))
            del prep[src]
            return
        if api.t - t0 > 40:
            del prep[src]
    if len(prep) >= 2 or api.res < 80:
        return
    byprov = {}
    for u in api.units:
        byprov.setdefault(u["prov"], []).append(u)
    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    best = None
    bp = 0.0
    for p, us in byprov.items():
        if p not in mine or p in prep:
            continue
        us = [u for u in us if u.get("state") not in ("routing", "shaken", "pinned")]
        if not us:
            continue
        S = sum(u.get("str", 0) * (0.4 + 0.6 * u.get("rdy", 50) / 100.0) for u in us)
        rdy = sum(u.get("rdy", 50) for u in us) / len(us)
        hs = sum(1 for u in us if u["type"] in HEAVY) / float(len(us))
        for nb in _nbs(api.provs[p]):
            pr2 = api.provs.get(nb)
            if not pr2 or nb in mine or pr2.get("owner") != "enemy":
                continue
            e = api.enemy.get(nb, {}).get("str", 0) or 60.0
            fort = pr2.get("fort") or 0
            tdef = TDEF.get(pr2.get("terrain"), 1.0)
            city = 1 if pr2.get("city") else 0
            D = e * tdef * (1.25 ** fort)
            prob = _p_take(api, S, D, fort, tdef, rdy, hs, city)
            if S >= 1.5 * D and prob >= 0.55 and prob > bp:
                best = (p, nb)
                bp = prob
    if best:
        p, nb = best
        prep[p] = (nb, api.t)
        api.cmd("prepare @P%d P%d" % (p, nb))


def _engineers(api):
    n = 0
    for u in api.units:
        if n >= 10:
            break
        if u["type"] != "eng" or u.get("path") or u.get("fighting") or u.get("state") == "digging":
            continue
        p = u["prov"]
        if p in api.border and (api.provs.get(p, {}).get("fort") or 0) < 3:
            api.cmd("fortify %d" % u["id"])
            n += 1


def tick(api):
    for f in (_recruit, _research, _orders, _attack, _engineers):
        try:
            f(api)
        except Exception:
            pass
```