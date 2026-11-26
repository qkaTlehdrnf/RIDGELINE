**Review of war 1:** We finished 28th of 30 with 30 provinces. Land ran out by about day 25, then the map stalled. We won 0 of 31 assaults, mostly at low readiness and without a prepared bonus. Income went negative (-4 to -5 per day) while 600+ units sat in the front. We killed 416 units but lost many more of our own.

**Changes:**
- **Assaults:** attack only with a strength ratio of at least 2.5 to 1 against a known enemy garrison, using at least 4 units at readiness 60+. Use `prepare` and wait about 16 hours for the bonus, then re-check the odds before moving. Cancel if the odds have dropped.
- **Economy:** stop recruiting while income is negative unless the bank is large. Keep a reserve.
- **Mix:** more art and atg to break fortified defenders, a little armour and mechanised for breakthroughs, and the same infantry core for formation experience.
- **Research:** staffwork earlier, since it speeds up prepared attacks. Keep the rest of the priority list.
- **Expansion and scouting:** unchanged, since they worked. Explorers and expanders still run.

I have not tested this against the engine, so the thresholds are estimates to tune in the next war.

```python
MIX = {"inf": 0.40, "mtn": 0.08, "atg": 0.12, "art": 0.12,
       "eng": 0.05, "arm": 0.08, "mot": 0.07, "mec": 0.03, "cav": 0.02}
PREF_RES = ["farming", "inf.protection", "inf.weapons", "conscription",
            "medicine", "discipline", "staffwork", "drill", "atg.weapons",
            "art.weapons", "fieldworks", "logistics", "arm.protection",
            "inf.mobility", "industry", "mining", "drilling", "refining"]
EXPAND_TYPES = ("inf", "mil", "mtn", "mot", "cav")
CORE_TYPES = ("inf", "mtn", "mil", "atg", "mec")
MIN_RATIO = 2.5
PREP_HOURS = 16
MAX_STRIKE = 16


def _afford(api, t):
    uc = api.unit_costs.get(t)
    if not uc:
        return False
    if api.res < uc.get("res", 0) + 40:
        return False
    if api.mp < uc.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) < uc.get(k, 0):
            return False
    return True


def _ids(items):
    out = []
    for x in items:
        out.append(str(x["id"]) if isinstance(x, dict) else str(x))
    return ",".join(out)


def _enemy_str(api, p):
    e = api.enemy.get(p)
    if not e:
        return None
    return e.get("str", None)


def _attackers(api, tgt, units):
    nb = api.provs.get(tgt, {}).get("nbrs", [])
    out = []
    for u in units:
        if u.get("prov") not in nb:
            continue
        if api.provs.get(u.get("prov"), {}).get("owner") != "me":
            continue
        if u.get("path") or u.get("type") == "rec":
            continue
        if u.get("state") not in ("ready", "preparing"):
            continue
        if u.get("str", 0) < 60 or u.get("rdy", 0) < 60:
            continue
        out.append(u)
    return out


def _odds(att, es):
    if es is None:
        return 0.0
    s = sum(u.get("str", 0) for u in att)
    return s / max(float(es), 1.0)


def _strike(api, units):
    m = api.mem
    prep = m.get("prep")
    if prep:
        tgt, t0, ids = prep
        if api.provs.get(tgt, {}).get("owner") == "me":
            m["prep"] = None
            return
        if api.t - t0 < PREP_HOURS:
            return
        m["prep"] = None
        byid = dict((u["id"], u) for u in units)
        alive = [byid[i] for i in ids if i in byid]
        att = _attackers(api, tgt, alive)
        if not alive:
            return
        if len(att) >= 3 and _odds(att, _enemy_str(api, tgt)) >= MIN_RATIO * 0.8:
            api.cmd("move %s P%d" % (_ids(att), tgt))
        else:
            api.cmd("hold %s" % _ids(alive))
        return

    own = [p for p, pr in api.provs.items() if pr.get("owner") == "me"]
    cands = set()
    for p in own:
        for nb in api.provs[p].get("nbrs", []):
            pr = api.provs.get(nb)
            if pr and pr.get("owner") == "enemy":
                cands.add(nb)
    best = None
    for tgt in cands:
        es = _enemy_str(api, tgt)
        if es is None:
            continue
        att = _attackers(api, tgt, units)
        if len(att) < 4:
            continue
        r = _odds(att, es)
        if r >= MIN_RATIO and (best is None or r > best[0]):
            best = (r, tgt, att)
    if best:
        r, tgt, att = best
        att = att[:MAX_STRIKE]
        ids = [u["id"] for u in att]
        api.cmd("prepare %s P%d" % (_ids(ids), tgt))
        m["prep"] = (tgt, api.t, ids)


def tick(api):
    m = api.mem
    m["n"] = m.get("n", 0) + 1
    n = m["n"]
    units = api.units

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)

    # 1. Recruit: two scouts, then fill the mix by deficit, only while the economy can carry it.
    try:
        economy_ok = api.income >= 0 or api.res > 400
        if economy_ok:
            if counts.get("rec", 0) < 2 and "rec" in api.unit_costs and _afford(api, "rec"):
                r = api.cmd("recruit rec P%d" % api.capital)
                if r.startswith("ok"):
                    counts["rec"] = counts.get("rec", 0) + 1
                    total += 1
            for _ in range(2):
                pick = None
                best = -1e9
                tot = total + 1
                for t, w in MIX.items():
                    if t not in api.unit_costs or not _afford(api, t):
                        continue
                    d = w * tot - counts.get(t, 0)
                    if d > best:
                        best = d
                        pick = t
                if pick is None:
                    break
                r = api.cmd("recruit %s P%d" % (pick, api.capital))
                if not r.startswith("ok"):
                    break
                counts[pick] = counts.get(pick, 0) + 1
                total += 1
    except Exception:
        pass

    # 2. Research: one new project per tick if affordable and a slot is free.
    try:
        if len(api.research) < 2:
            busy = set(r[0] for r in api.research)
            for line in PREF_RES:
                if line in busy:
                    continue
                t = api.tech.get(line)
                if not t or t.get("status") != "open":
                    continue
                cost = t.get("cost") or {}
                ok = api.res >= cost.get("res", 0) + 60
                for k, v in cost.items():
                    if k != "res" and api.stock.get(k, 0) < v:
                        ok = False
                if ok:
                    api.cmd("research %s" % line)
                    break
    except Exception:
        pass

    # 3. Scouting.
    used = set()
    try:
        if api.unexplored:
            explorers = [u for u in units if u["type"] == "rec" and u["state"] == "ready"
                         and not u["path"] and not u["explore"]]
            if explorers:
                ids = [str(u["id"]) for u in explorers[:2]]
                api.cmd("explore " + ",".join(ids))
                used.update(u["id"] for u in explorers[:2])
    except Exception:
        pass

    # 4. Strikes: only at strong odds, prepared first, launched after the bonus builds.
    try:
        _strike(api, units)
        for u in units:
            if u["state"] == "preparing":
                used.add(u["id"])
    except Exception:
        pass

    idle = [u for u in units if u["state"] == "ready" and not u["path"]
            and not u["front"] and not u["expand"] and not u["explore"]
            and u["type"] != "rec" and u["id"] not in used]

    # 5. Land grabs on neutral ground.
    try:
        expanders = sum(1 for u in units if u["expand"])
        if api.neutral_border and expanders < 4:
            pick = [u for u in idle if u["type"] in EXPAND_TYPES][:2]
            for u in pick:
                r = api.cmd("expand %d" % u["id"])
                if r.startswith("ok"):
                    used.add(u["id"])
    except Exception:
        pass

    # 6. Everything else idle goes on the front, batched.
    try:
        rest = [str(u["id"]) for u in idle if u["id"] not in used]
        if rest:
            api.cmd("front " + ",".join(rest))
    except Exception:
        pass

    # 7. Core front units join one formation, to build formation experience.
    try:
        if n % 12 == 0:
            new = [str(u["id"]) for u in units if u["front"] and not u["group"]
                   and u["type"] in CORE_TYPES]
            if new:
                if not m.get("grp"):
                    api.cmd("group line " + ",".join(new))
                    m["grp"] = True
                else:
                    api.cmd("group line + " + ",".join(new))
    except Exception:
        pass

    m["calls"] = n
```