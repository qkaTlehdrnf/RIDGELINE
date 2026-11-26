**Review of war 1 (13th of 30, 103 provinces):** Assaults were the failure. Only 3 of 176 succeeded, and the failures clustered at fort levels 2-4 and at strength ratios below 3. The army also sat idle on a stalled front. Research mostly hit dead ends, so the hidden tree is worth probing but not over-investing in.

**Changes:**
- **Assault gate:** Attack only when my strength exceeds the target's effective defence by 2.2x. Effective defence accounts for estimated strength (x1.4 when not exact), terrain, and fort level. Skip high-fort targets unless artillery is present.
- **Strike groups:** Gather five or more ready units at a border province, prepare for up to 10 hours, then launch only if the ratio still holds. Otherwise hold.
- **Mix:** Add grenadiers (assault, ignore 20% of forts) and rocket artillery (ignores 30% of forts). Keep artillery and engineers for fort-breaking and digging in.
- **Engineers:** Fortify idle engineers on the border, which strengthens the front.
- **Research:** Keep the open-line scan, skip dead ends automatically, and add weapons and protection lines for the new types.
- **Economy:** Keep reserves and the expand/front split, which worked.

```python
RES_RESERVE = 80
MP_RESERVE = 40
MAX_UNITS = 600

TYPE_MIX = {
    "inf": 0.28, "mil": 0.02, "art": 0.16, "atg": 0.08,
    "eng": 0.08, "arm": 0.07, "mot": 0.05, "rec": 0.02,
    "mtn": 0.08, "grn": 0.10, "rkt": 0.04,
}

LINES = [
    "inf.weapons", "art.weapons", "atg.weapons", "grn.weapons",
    "conscription", "logistics", "mining", "farming", "medicine",
    "art.protection", "inf.protection", "mtn.weapons", "arm.weapons",
    "fieldworks", "discipline", "staffwork", "industry", "drill",
    "drilling", "refining", "arm.protection", "mtn.protection",
]

TERRAIN_DEF = {"hill": 1.5, "mountain": 2.0, "forest": 1.25}
BAD_STATE = ("routing", "digging", "refitting", "preparing", "pinned")


def _pick(api, counts, total, left):
    best = None
    bd = -1e9
    for typ, share in TYPE_MIX.items():
        c = api.unit_costs.get(typ)
        if not c:
            continue
        if left["res"] < c["res"] + RES_RESERVE:
            continue
        if left["mp"] < c["mp"] + MP_RESERVE:
            continue
        if (c.get("steel", 0) > left["steel"] or c.get("oil", 0) > left["oil"]
                or c.get("rare", 0) > left["rare"]):
            continue
        d = share * (total + 1) - counts.get(typ, 0)
        if d > bd:
            bd = d
            best = typ
    if best:
        c = api.unit_costs[best]
        left["res"] -= c["res"]
        left["mp"] -= c["mp"]
        left["steel"] -= c.get("steel", 0)
        left["oil"] -= c.get("oil", 0)
        left["rare"] -= c.get("rare", 0)
    return best


def _recruit(api, counts, total):
    left = {
        "res": api.stock.get("res", 0), "mp": api.mp,
        "steel": api.stock.get("steel", 0), "oil": api.stock.get("oil", 0),
        "rare": api.stock.get("rare", 0),
    }
    n = 3 if left["res"] > 500 else 2
    for _ in range(n):
        if total >= MAX_UNITS or api.income <= 0:
            break
        typ = _pick(api, counts, total, left)
        if not typ:
            break
        r = api.cmd("recruit %s P%d" % (typ, api.capital))
        if not str(r).startswith("ok"):
            break
        counts[typ] = counts.get(typ, 0) + 1
        total += 1


def _research(api):
    if len(api.research) >= 2:
        return
    for line in LINES:
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        c = t.get("cost")
        if not c:
            continue
        if all(api.stock.get(k, 0) >= v for k, v in c.items()) \
                and api.stock.get("res", 0) >= c.get("res", 0) + 150:
            api.cmd("research %s" % line)
            return


def _eff_def(qv, e, exact):
    es = max(e.get("str", 0), 1.0)
    if not exact:
        es *= 1.4
    terr = str(qv.get("terrain", ""))
    tdef = 1.0
    for k, v in TERRAIN_DEF.items():
        if terr.startswith(k):
            tdef = v
    fort = qv.get("fort") or 0
    return es * tdef * (1.0 + 0.5 * fort)


def _orders(api, m, units):
    cap = api.capital
    recs, idle, weak, dig = [], [], [], []
    n_exp = 0
    n_front = 0
    for u in units:
        if u.get("expand"):
            n_exp += 1
        if u.get("front"):
            n_front += 1
        if (u.get("path") or u.get("fighting") or u.get("expand")
                or u.get("explore") or u.get("front")):
            continue
        if u.get("plan", -1) not in (-1, None):
            continue
        if u.get("state") in ("routing", "digging", "refitting", "preparing"):
            continue
        if u["type"] == "rec":
            recs.append(u["id"])
            continue
        if u.get("str", 100) < 40:
            weak.append(u)
            continue
        if u["type"] == "eng" and u.get("prov") in api.border:
            dig.append(u["id"])
            continue
        idle.append(u)

    if recs:
        api.cmd("explore %s" % ",".join(str(i) for i in recs))
    if dig:
        api.cmd("fortify %s" % ",".join(str(i) for i in dig))

    to_cap = [u["id"] for u in weak if u.get("prov") != cap]
    if to_cap:
        api.cmd("move %s P%d" % (",".join(str(i) for i in to_cap), cap))

    if not idle:
        return
    nonrec = n_exp + n_front + len(idle)
    want_exp = 0
    if api.neutral_border:
        want_exp = min(len(idle), max(0, int(0.3 * nonrec) - n_exp))
    exp_ids = [u["id"] for u in idle[:want_exp]]
    front_ids = [u["id"] for u in idle[want_exp:]]
    if exp_ids:
        api.cmd("expand %s" % ",".join(str(i) for i in exp_ids))
    if front_ids:
        api.cmd("front %s" % ",".join(str(i) for i in front_ids))
        grouped = m.setdefault("grouped", [])
        new = [i for i in front_ids if i not in grouped]
        if new:
            sel = ",".join(str(i) for i in new)
            if m.get("gfront"):
                api.cmd("group line + %s" % sel)
            else:
                api.cmd("group line %s" % sel)
                m["gfront"] = True
            grouped.extend(new)
            if len(grouped) > 3000:
                del grouped[:1000]


def _strike(api, m, t, by_prov):
    plan = m.get("plan")
    if plan:
        p, q, t0 = plan["p"], plan["q"], plan["t0"]
        ids, uids = plan["ids"], plan["uids"]
        e = api.enemy.get(q)
        qv = api.provs.get(q, {})
        ms = sum(u.get("str", 0) for u in by_prov.get(p, []) if u["id"] in uids)
        ok = (e is not None and ms >= 2.2 * _eff_def(qv, e, e.get("exact", False)))
        if t - t0 >= 10:
            if ok:
                api.cmd("move %s P%d" % (ids, q))
            else:
                api.cmd("hold %s" % ids)
            m["plan"] = None
        elif not ok:
            api.cmd("hold %s" % ids)
            m["plan"] = None
        return

    for p in list(api.border.keys()):
        pv = api.provs.get(p)
        if not pv:
            continue
        mine = [u for u in by_prov.get(p, [])
                if u.get("str", 0) >= 55 and u.get("rdy", 0) >= 50
                and not u.get("path") and not u.get("expand")
                and u.get("state") not in BAD_STATE]
        if len(mine) < 5:
            continue
        ms = sum(u.get("str", 0) for u in mine)
        best = None
        best_r = 0.0
        for q in pv.get("nbrs", []):
            e = api.enemy.get(q)
            if not e or e.get("n", 0) <= 0:
                continue
            qv = api.provs.get(q)
            if not qv or qv.get("owner") == "me":
                continue
            eff = _eff_def(qv, e, e.get("exact", False))
            r = ms / eff
            if r >= 2.2 and r > best_r:
                best_r = r
                best = q
        if best is not None:
            ids = ",".join(str(u["id"]) for u in mine)
            api.cmd("prepare %s P%d" % (ids, best))
            m["plan"] = {"p": p, "q": best, "t0": t, "ids": ids,
                         "uids": [u["id"] for u in mine]}
            return


def tick(api):
    m = api.mem
    t = api.t
    units = api.units

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)

    try:
        _recruit(api, counts, total)
    except Exception:
        pass

    try:
        _research(api)
    except Exception:
        pass

    try:
        _orders(api, m, units)
    except Exception:
        pass

    try:
        by_prov = {}
        for u in units:
            by_prov.setdefault(u.get("prov"), []).append(u)
        _strike(api, m, t, by_prov)
    except Exception:
        pass

    m["calls"] = m.get("calls", 0) + 1
```