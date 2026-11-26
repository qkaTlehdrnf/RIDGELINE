The policy runs three loops each call. It researches economy lines first, then recruits toward a unit mix that scales with income. It sends scouts to explore, expands into neutral land while any is reachable, and otherwise holds the border with front orders. It attacks only when visible enemy strength is clearly outmatched, using prepare and then move. Nusantara's +10% attack favours assaults, so the thresholds are set to attack when the odds are clearly good, not to play for a stalemate. Each loop is wrapped in its own try/except so one failure does not lose the whole call. The code uses no imports and stays well within the time budget. Doctrine and research outcomes are unknown in advance, so research picks are a sensible economy-first gamble, not a fixed plan.

```python
# Nusantara standing orders. Economy first, border holding, opportunistic
# assaults when visible strength clearly outmatches the target.

MIX = [
    ("inf", 0.40), ("grn", 0.06), ("cav", 0.10), ("mtn", 0.05),
    ("art", 0.10), ("eng", 0.05), ("atg", 0.04), ("mot", 0.08),
    ("arm", 0.08), ("mec", 0.04),
]

RESEARCH = [
    "farming", "conscription", "inf.weapons", "inf.protection",
    "mining", "drill", "logistics", "arm.weapons", "art.weapons",
    "medicine", "fieldworks", "mot.mobility", "inf.mobility",
    "industry", "discipline", "drilling", "refining",
]

TERR_DEF = [("mountain", 2.0), ("hill", 1.5), ("forest", 1.25), ("plain", 1.0)]

MAX_WAVES = 3
WAVE_CAP = 14


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _research(api):
    if len(api.research) >= 2:
        return
    for line in RESEARCH:
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        cost = t.get("cost")
        if not cost:
            continue
        ok = True
        for k, v in cost.items():
            have = api.res if k == "res" else api.stock.get(k, 0)
            if have < v + 80:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research %s" % line)
        if r.startswith("ok"):
            return


def _recruit(api):
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    nonrec = sum(v for k, v in counts.items() if k != "rec")

    res_left = api.res
    mp_left = api.mp
    stock_left = dict(api.stock)

    def can(typ, reserve):
        c = api.costs.get(typ)
        if not c:
            return False
        if res_left - c[0] < reserve or mp_left < c[1]:
            return False
        uc = api.unit_costs.get(typ, {})
        for k in ("steel", "oil", "rare"):
            if stock_left.get(k, 0) < uc.get(k, 0):
                return False
        return True

    def spend(typ):
        c = api.costs.get(typ)
        uc = api.unit_costs.get(typ, {})
        for k in ("steel", "oil", "rare"):
            stock_left[k] = stock_left.get(k, 0) - uc.get(k, 0)
        return c[0], c[1]

    # Scouts first, a small fixed number.
    if counts.get("rec", 0) < 3 and can("rec", 40):
        dr, dm = spend("rec")
        res_left -= dr
        mp_left -= dm
        r = api.cmd("recruit rec P%d" % api.capital)
        counts["rec"] = counts.get("rec", 0) + 1
        if not r.startswith("ok"):
            return

    for _ in range(4):
        best, bestv = None, -1e9
        for typ, share in MIX:
            if not can(typ, 60):
                continue
            deficit = share * (nonrec + 1) - counts.get(typ, 0)
            if deficit > bestv:
                best, bestv = typ, deficit
        if best is None or bestv < 0:
            break
        dr, dm = spend(best)
        res_left -= dr
        mp_left -= dm
        r = api.cmd("recruit %s P%d" % (best, api.capital))
        if not r.startswith("ok"):
            break
        counts[best] = counts.get(best, 0) + 1
        nonrec += 1


def _orders(api, mem):
    waves_ids = set()
    for w in mem.get("waves", {}).values():
        waves_ids.update(w["ids"])

    scouts = []
    idle = []
    nonrec = 0
    expanding = 0
    for u in api.units:
        if u["type"] == "rec":
            if not u.get("path") and not u.get("explore") and u["id"] not in waves_ids:
                scouts.append(u["id"])
            continue
        nonrec += 1
        if u.get("expand"):
            expanding += 1
        if u.get("path") or u["id"] in waves_ids:
            continue
        if u.get("plan", -1) >= 0:
            continue
        if u.get("front") or u.get("expand") or u.get("explore"):
            continue
        idle.append(u["id"])

    if scouts:
        api.cmd("explore %s" % _sel(scouts))

    if idle:
        if api.neutral_border and expanding < 0.6 * max(1, nonrec):
            batch = idle[:max(1, len(idle))]
            api.cmd("expand %s" % _sel(batch))
        else:
            api.cmd("front %s" % _sel(idle))


def _attacks(api, mem):
    t = api.t
    waves = mem.setdefault("waves", {})
    alive = {u["id"]: u for u in api.units}

    # Advance existing waves.
    for n in list(waves.keys()):
        w = waves[n]
        ids = [i for i in w["ids"] if i in alive]
        pv = api.provs.get(int(n), {})
        if not ids or pv.get("owner") == "me":
            del waves[n]
            continue
        w["ids"] = ids
        if w["stage"] == "prep":
            bonus_ok = all(alive[i].get("bonus", 0) >= 15 for i in ids)
            if bonus_ok or t - w["t0"] >= 12:
                api.cmd("move %s P%d" % (_sel(ids), int(n)))
                w["stage"] = "move"
                w["t0"] = t
        else:
            if all(not alive[i].get("path") for i in ids) and t - w["t0"] >= 6:
                del waves[n]

    if len(waves) >= MAX_WAVES:
        return

    committed = set()
    for w in waves.values():
        committed.update(w["ids"])

    by_prov = {}
    for u in api.units:
        if u["type"] == "rec" or u["id"] in committed:
            continue
        if u.get("path") or u.get("state") != "ready":
            continue
        by_prov.setdefault(u["prov"], []).append(u)

    if api.res < 40:
        return

    best = None
    bestv = 0.0
    for p, lst in by_prov.items():
        pv = api.provs.get(p)
        if not pv or pv.get("owner") != "me":
            continue
        s_total = sum(u.get("str", 0) for u in lst)
        if len(lst) < 2 or s_total < 120:
            continue
        avg_rdy = sum(u.get("rdy", 0) for u in lst) / float(len(lst))
        if avg_rdy < 55:
            continue
        for n in pv.get("nbrs", []):
            if n in waves:
                continue
            nv = api.provs.get(n)
            if not nv or nv.get("owner") != "enemy":
                continue
            info = api.enemy.get(n)
            e = info.get("str", 0) if info else 0
            if not info and s_total < 250:
                continue
            terr = str(nv.get("terrain", ""))
            dm = 1.0
            for k, v in TERR_DEF:
                if k in terr:
                    dm = v
                    break
            if nv.get("city"):
                dm += 0.25
            fort = nv.get("fort", 0) or 0
            e_eff = e * dm * (1.0 + 0.25 * fort)
            elev = (nv.get("elev", 0) or 0) - (pv.get("elev", 0) or 0)
            s_eff = s_total * (0.9 ** max(0, elev)) * (1.08 ** max(0, -elev))
            if s_eff < 1.6 * e_eff + 40:
                continue
            v = s_eff / (e_eff + 1.0)
            if v > bestv:
                best, bestv = (p, n, lst), v

    if best is None:
        return
    p, n, lst = best
    lst = sorted(lst, key=lambda u: -u.get("str", 0))[:WAVE_CAP]
    ids = [u["id"] for u in lst]
    sel = _sel(ids)
    api.cmd("group w%d %s" % (int(n), sel))
    r = api.cmd("prepare %s P%d" % (sel, int(n)))
    if r.startswith("ok"):
        waves[n] = {"ids": ids, "stage": "prep", "t0": t}


def tick(api):
    mem = api.mem
    try:
        _research(api)
    except Exception:
        pass
    try:
        _recruit(api)
    except Exception:
        pass
    try:
        _attacks(api, mem)
    except Exception:
        pass
    try:
        _orders(api, mem)
    except Exception:
        pass
    mem["calls"] = mem.get("calls", 0) + 1
```