**Reasoning (for the Granada policy):**

Granada has +10% defence and -10% speed, so the policy plays a defensive, land-holding game. It takes free land early, holds the border, and attacks only when it has a clear local superiority.

- **Recruitment:** Units are drawn toward a target mix (mostly line infantry, with artillery, anti-tank guns, and some armour gated by steel). A local budget tracks what each recruit spends, so the bank isn't overdrawn in one tick. Recruiting stops if income is negative or the army hits the cap.
- **Research:** One project starts at a time from a priority list (economy first, then protection and weapons). Each only starts when the bank covers its cost plus a margin. Breakthroughs and dead ends are unknown, so I just work down the list.
- **Orders:** Scouts explore. Weak units fall back to the capital to refit. Healthy idle units expand into neutral land up to about 30% of the army, and the rest take the front. New front units join one named formation to build formation experience.
- **Attacks:** Where a border province holds at least five strong units and at least 2.5 times the visible enemy strength next door, the policy prepares an attack, waits about six hours for the bonus, then launches. It cancels if the odds fall.

Each section is wrapped so one failure does not lose the whole tick. Per-tick work is linear in unit count, which stays well within the time limit.

```python
RES_RESERVE = 60
MP_RESERVE = 30
MAX_UNITS = 500

TYPE_MIX = {
    "inf": 0.38, "mil": 0.04, "art": 0.16, "atg": 0.10,
    "eng": 0.06, "arm": 0.08, "mot": 0.06, "rec": 0.03, "mtn": 0.09,
}

LINES = [
    "farming", "conscription", "inf.protection", "inf.weapons",
    "art.weapons", "atg.weapons", "art.protection", "mining",
    "industry", "medicine", "drill", "logistics", "fieldworks",
    "discipline", "arm.protection", "arm.weapons", "drilling",
    "refining", "staffwork", "mtn.protection", "mtn.weapons",
]


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


def _orders(api, m, units):
    cap = api.capital
    recs, idle, weak = [], [], []
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
        idle.append(u)

    if recs:
        api.cmd("explore %s" % ",".join(str(i) for i in recs))

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


def _attack(api, m, t, by_prov):
    plan = m.get("plan")
    if plan:
        p, q, t0, ids = plan["p"], plan["q"], plan["t0"], plan["ids"]
        e = api.enemy.get(q)
        es = e.get("str", 0) if e else 0
        ms = sum(u.get("str", 0) for u in by_prov.get(p, []))
        ok = e is not None and ms >= 2.0 * max(es, 1)
        if t - t0 >= 6:
            if ok:
                api.cmd("move %s P%d" % (ids, q))
            else:
                api.cmd("hold %s" % ids)
            m["plan"] = None
        elif t - t0 > 30 or not ok:
            api.cmd("hold %s" % ids)
            m["plan"] = None
        return

    for p in list(api.border.keys()):
        mine = [u for u in by_prov.get(p, [])
                if u.get("str", 0) >= 60 and u.get("rdy", 0) >= 60
                and not u.get("path") and not u.get("expand")]
        if len(mine) < 5:
            continue
        pv = api.provs.get(p)
        if not pv:
            continue
        ms = sum(u.get("str", 0) for u in mine)
        best = None
        best_ratio = 0.0
        for q in pv.get("nbrs", []):
            e = api.enemy.get(q)
            if not e or e.get("n", 0) <= 0:
                continue
            qv = api.provs.get(q)
            if not qv or qv.get("owner") == "me":
                continue
            es = max(e.get("str", 0), 1)
            ratio = ms / es if e.get("exact", False) else ms / (es * 1.4)
            if ratio >= 2.5 and ratio > best_ratio:
                best_ratio = ratio
                best = q
        if best is not None:
            ids = ",".join(str(u["id"]) for u in mine)
            api.cmd("prepare %s P%d" % (ids, best))
            m["plan"] = {"p": p, "q": best, "t0": t, "ids": ids}
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
        _attack(api, m, t, by_prov)
    except Exception:
        pass

    m["calls"] = m.get("calls", 0) + 1
```