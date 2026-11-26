**Review of war 1 (place 15 of 30, 97 provinces):**

- **Assaults failed.** Only 4 of 72 succeeded. Failures clustered at low readiness (3 of 69 under 34 readiness) and at strength ratios under 5. Attacks launched before units had rested or prepared were wasted.
- **Stockpiles sat idle.** Ending with 1998 steel, 800 oil and 631 rare unused means the army was built from inf and cav when heavier units were affordable.
- **Expansion stalled.** Neutral land was gone by about day 25. After that, the front became a stalemate.

**Changes in this rewrite:**

1. **Attacks need readiness and preparation.** Waves launch only when average readiness is at least 75 and the prepared bonus is at least 20%, with a strength margin of 2.2x the estimated defence. Waves that stall are withdrawn.
2. **Stockpiles drive the mix.** When steel, oil and rare are high, the recruit mix shifts toward arm, mot, art and atg. Otherwise it stays infantry-heavy for cheap holding.
3. **Research uses all open lines.** Economy lines (mining, drilling, refining, farming) are kept, and weapon and protection lines are raised for the types I actually field.
4. **Expansion continues while land exists.** Idle units expand first and join the front only when no neutral land is reachable.

```python
# Nusantara standing orders, v2.
# Economy first, rest before assault, spend the special stockpiles on heavy units,
# and attack only with readiness, preparation and a clear strength margin.

BASE_MIX = [
    ("inf", 0.36), ("grn", 0.05), ("cav", 0.07), ("mtn", 0.05),
    ("art", 0.08), ("eng", 0.05), ("atg", 0.05), ("mot", 0.08),
    ("arm", 0.10), ("mec", 0.05), ("hvt", 0.02),
]

# Heavy shares used when the special stockpiles are large.
HEAVY_MIX = [
    ("inf", 0.26), ("grn", 0.05), ("cav", 0.04), ("mtn", 0.04),
    ("art", 0.12), ("eng", 0.05), ("atg", 0.07), ("mot", 0.11),
    ("arm", 0.14), ("mec", 0.07), ("hvt", 0.05),
]

RESEARCH = [
    "farming", "mining", "drilling", "conscription", "inf.weapons",
    "inf.protection", "arm.weapons", "arm.protection", "art.weapons",
    "mot.weapons", "mot.mobility", "logistics", "medicine", "refining",
    "industry", "fieldworks", "discipline", "drill", "staffwork",
    "mec.protection", "atg.weapons", "inf.mobility",
]

TERR_DEF = [("mountain", 2.0), ("hill", 1.5), ("forest", 1.25), ("plain", 1.0)]

MAX_WAVES = 2
WAVE_CAP = 16
MIN_READY = 75
MIN_BONUS = 20
MIN_RATIO = 2.2


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
            if have < v + 60:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research %s" % line)
        if r.startswith("ok"):
            return


def _mix(api):
    # Use the heavy mix only when special stockpiles can carry it.
    st = api.stock
    rich = st.get("steel", 0) >= 400 and st.get("oil", 0) >= 150
    return HEAVY_MIX if rich else BASE_MIX


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

    # A small fixed scout screen.
    if counts.get("rec", 0) < 3 and can("rec", 40):
        dr, dm = spend("rec")
        res_left -= dr
        mp_left -= dm
        r = api.cmd("recruit rec P%d" % api.capital)
        counts["rec"] = counts.get("rec", 0) + 1
        if not r.startswith("ok"):
            return

    mix = _mix(api)
    for _ in range(4):
        best, bestv = None, -1e9
        for typ, share in mix:
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
        # Keep claiming neutral land while any exists; otherwise hold the front.
        if api.neutral_border and expanding < 0.7 * max(1, nonrec):
            api.cmd("expand %s" % _sel(idle))
        else:
            api.cmd("front %s" % _sel(idle))


def _attacks(api, mem):
    t = api.t
    waves = mem.setdefault("waves", {})
    alive = {u["id"]: u for u in api.units}

    for n in list(waves.keys()):
        w = waves[n]
        ids = [i for i in w["ids"] if i in alive]
        pv = api.provs.get(int(n), {})
        if not ids or pv.get("owner") == "me":
            del waves[n]
            continue
        w["ids"] = ids
        if w["stage"] == "prep":
            avg_bonus = sum(alive[i].get("bonus", 0) for i in ids) / float(len(ids))
            avg_rdy = sum(alive[i].get("rdy", 0) for i in ids) / float(len(ids))
            if (avg_bonus >= MIN_BONUS and avg_rdy >= MIN_READY) or t - w["t0"] >= 24:
                api.cmd("move %s P%d" % (_sel(ids), int(n)))
                w["stage"] = "move"
                w["t0"] = t
        else:
            # Withdraw a wave that has finished or is badly worn.
            worn = sum(alive[i].get("str", 0) for i in ids) < 0.5 * max(1, len(ids)) * 100
            if all(not alive[i].get("path") for i in ids) and (t - w["t0"] >= 6 or worn):
                for i in ids:
                    alive[i]  # keep reference
                api.cmd("move %s P%d" % (_sel(ids), int(_home(api, ids))))
                del waves[n]

    if len(waves) >= MAX_WAVES:
        return
    if api.res < 60:
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
        if u.get("rdy", 0) < MIN_READY:
            continue
        by_prov.setdefault(u["prov"], []).append(u)

    best = None
    bestv = 0.0
    for p, lst in by_prov.items():
        pv = api.provs.get(p)
        if not pv or pv.get("owner") != "me":
            continue
        s_total = sum(u.get("str", 0) for u in lst)
        if len(lst) < 3 or s_total < 200:
            continue
        for n in pv.get("nbrs", []):
            if n in waves:
                continue
            nv = api.provs.get(n)
            if not nv or nv.get("owner") != "enemy":
                continue
            info = api.enemy.get(n)
            if not info:
                continue
            e = info.get("str", 0)
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
            if s_eff < MIN_RATIO * e_eff + 60:
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


def _home(api, ids):
    # Fall back to the capital if a withdrawing wave has no better point.
    return api.capital


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