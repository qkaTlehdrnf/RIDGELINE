**Reasoning (summary):** The last war ended at 83 provinces, rank 18. Assaults never succeeded (0/53), mostly against forts at level 3-4. Stockpiles sat unused (4256 steel, 2818 oil, 1454 rare), and 266 units were still on outdated models. Unit count hit the 900 cap while manpower was plentiful, so quality per slot matters more than quantity. Neutral land ran out by about day 35.

Changes:
- Raise the cap to 1100 and bias recruitment toward armour, heavy armour, mechanised and rocket units when steel is plentiful, so the stockpile gets spent.
- Refit faster (cap 30 per tick, lower resource threshold) to clear the outdated models.
- Gate assaults on the fitted logistic model in `api.model`, with a ratio fallback. Skip pact partners.
- Keep the pact and trade logic, since peace protected units and the stalemate was costly.
- Expand less (45%) and hold more of the front once neutral land is gone.

I have not tested this against the engine, so the thresholds are estimates.

```python
RES_RESERVE = 120
MP_RESERVE = 40
MAX_UNITS = 1100

TYPE_MIX = {
    "inf": 0.16, "mil": 0.0, "art": 0.16, "atg": 0.05,
    "eng": 0.05, "arm": 0.07, "mot": 0.06, "rec": 0.02,
    "mtn": 0.06, "grn": 0.08, "rkt": 0.07, "hvt": 0.08, "mec": 0.09,
}

LINES = [
    "mining", "logistics", "conscription", "farming",
    "inf.weapons", "grn.weapons", "art.protection", "arm.weapons",
    "mot.weapons", "hvt.weapons", "mec.weapons", "arm.protection",
    "inf.protection", "mtn.weapons", "medicine", "industry", "discipline",
    "drill", "fieldworks", "staffwork", "drilling", "refining",
    "mot.mobility", "arm.mobility", "mec.protection", "hvt.protection",
    "atg.weapons", "art.weapons",
]

TERRAIN_DEF = {"hill": 1.5, "mountain": 2.0, "forest": 1.25}
BAD_STATE = ("routing", "digging", "refitting", "preparing", "pinned")
ATTACK_MIN_UNITS = 8
ATTACK_MIN_RDY = 65
P_GO = 0.6
REFIT_CAP = 30
REFIT_MIN_RES = 250
EXPAND_SHARE = 0.45


def _pick(api, counts, total, left, boost):
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
        s = share * boost.get(typ, 1.0)
        d = s * (total + 1) - counts.get(typ, 0)
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
    boost = {}
    if left["steel"] > 800:
        boost = {"arm": 1.5, "hvt": 1.6, "mec": 1.4, "rkt": 1.4}
    n = 2
    if left["res"] > 800:
        n = 5
    elif left["res"] > 400:
        n = 3
    for _ in range(n):
        if total >= MAX_UNITS or api.income <= 0:
            break
        typ = _pick(api, counts, total, left, boost)
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
                and api.stock.get("res", 0) >= c.get("res", 0) + 100:
            api.cmd("research %s" % line)
            return


def _refit(api):
    if api.stock.get("res", 0) < REFIT_MIN_RES:
        return
    old = [u for u in api.units
           if u.get("old") and not u.get("fighting") and u.get("supplied")
           and u.get("state") == "ready" and not u.get("path")
           and u.get("plan", -1) in (-1, None) and u.get("rdy", 0) >= 50]
    if not old:
        return
    left = {
        "res": api.stock.get("res", 0) - RES_RESERVE,
        "steel": api.stock.get("steel", 0),
        "oil": api.stock.get("oil", 0),
        "rare": api.stock.get("rare", 0),
    }
    ids = []
    for u in old:
        c = api.refit_cost.get(u["type"])
        if not c:
            continue
        if (c.get("res", 0) > left["res"] or c.get("steel", 0) > left["steel"]
                or c.get("oil", 0) > left["oil"] or c.get("rare", 0) > left["rare"]):
            continue
        left["res"] -= c.get("res", 0)
        left["steel"] -= c.get("steel", 0)
        left["oil"] -= c.get("oil", 0)
        left["rare"] -= c.get("rare", 0)
        ids.append(u["id"])
        if len(ids) >= REFIT_CAP:
            break
    if ids:
        api.cmd("refit %s" % ",".join(str(i) for i in ids))


def _diplomacy(api, m, t):
    for o in api.offers_in or []:
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
        elif o.get("kind") == "trade":
            give = sum((o.get("you_give") or {}).values())
            get = sum((o.get("they_give") or {}).values())
            if give <= get:
                api.cmd("accept %s" % o["id"])
    if t - m.get("pact_t", -999) < 96:
        return
    m["pact_t"] = t
    active = api.pacts or {}
    sent = 0
    for f in api.met:
        if f in active or sent >= 3:
            continue
        api.cmd("offer %s pact" % f)
        sent += 1


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


def _score(api, qv, e, mine, bonus):
    """Estimated probability that an assault from `mine` takes the province."""
    ms = sum(u.get("str", 0) for u in mine)
    exact = e.get("exact", False)
    es = max(e.get("str", 0), 1.0)
    if not exact:
        es *= 1.4
    model = api.model or {}
    feats = model.get("features")
    if feats and model.get("w") and model.get("std"):
        terr = str(qv.get("terrain", ""))
        tdef = 1.0
        for k, v in TERRAIN_DEF.items():
            if terr.startswith(k):
                tdef = v
        n = float(len(mine)) or 1.0
        x = {
            "log_ratio": math.log((ms + 1.0) / (es + 1.0)),
            "terrain_dfn": tdef,
            "fort": float(qv.get("fort") or 0),
            "city": 1.0 if qv.get("city") else 0.0,
            "bonus": bonus,
            "att_rdy": sum(u.get("rdy", 0) for u in mine) / n / 100.0,
            "heavy_share": sum(1 for u in mine
                               if u["type"] in ("art", "eng", "arm", "rkt")) / n,
            "dirs": 1.0,
        }
        z = float(model.get("b", 0.0))
        for i, f in enumerate(feats):
            std = model["std"][i] or 1.0
            z += model["w"][i] * (x.get(f, 0.0) - model["mean"][i]) / std
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))
    # fallback without a fitted model: strength ratio against need
    eff = _eff_def(qv, e, exact)
    need = 5.0 if (qv.get("fort") or 0) >= 2 else 3.0
    r = ms / max(eff, 1.0)
    if r >= need:
        return 0.8
    return 0.5 * r / need


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
        want_exp = min(len(idle), max(0, int(EXPAND_SHARE * nonrec) - n_exp))
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
        ids = plan["ids"]
        uids = set(plan["uids"])
        mine = [u for u in by_prov.get(p, []) if u["id"] in uids]
        e = api.enemy.get(q)
        qv = api.provs.get(q, {})
        ok = False
        if e is not None and e.get("n", 0) > 0 and mine:
            bonus = min(0.5, (t - t0) / 100.0)
            ok = _score(api, qv, e, mine, bonus) >= P_GO
        if t - t0 >= 8:
            if ok:
                api.cmd("move %s P%d" % (ids, q))
            else:
                api.cmd("hold %s" % ids)
            m["plan"] = None
        elif not ok:
            api.cmd("hold %s" % ids)
            m["plan"] = None
        return

    pacts = api.pacts or {}
    for p in list(api.border.keys()):
        pv = api.provs.get(p)
        if not pv:
            continue
        mine = [u for u in by_prov.get(p, [])
                if u.get("str", 0) >= 55 and u.get("rdy", 0) >= ATTACK_MIN_RDY
                and not u.get("path") and not u.get("expand")
                and u.get("state") not in BAD_STATE]
        if len(mine) < ATTACK_MIN_UNITS:
            continue
        best = None
        best_p = 0.0
        for q in pv.get("nbrs", []):
            e = api.enemy.get(q)
            if not e or e.get("n", 0) <= 0:
                continue
            qv = api.provs.get(q)
            if not qv or qv.get("owner") == "me":
                continue
            if api.owner_name.get(q) in pacts:
                continue
            pr = _score(api, qv, e, mine, 0.5)
            if pr > best_p:
                best_p = pr
                best = q
        if best is not None and best_p >= P_GO:
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
        _diplomacy(api, m, t)
    except Exception:
        pass

    try:
        _recruit(api, counts, total)
    except Exception:
        pass

    try:
        _research(api)
    except Exception:
        pass

    try:
        _refit(api)
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

```letters
to andea: Granada keeps every pact and will answer your trade offers promptly. Peace and fair trade suit us both.
to amazonia: Granada accepts your peace and fair trades; we will keep our side and expect the same.
```