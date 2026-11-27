RES_RESERVE = 120
MP_RESERVE = 40
MAX_UNITS = 1600

TYPE_MIX = {
    "inf": 0.16, "mil": 0.03, "cav": 0.08, "art": 0.10, "atg": 0.04,
    "eng": 0.04, "arm": 0.05, "mot": 0.05, "rec": 0.02, "mtn": 0.05,
    "grn": 0.06, "rkt": 0.04, "hvt": 0.06, "mec": 0.08,
}

DISC_ORDER = [
    "iron_working", "roads", "horse_riding", "siege_engines", "masonry",
    "galleys", "stirrup", "pikes_crossbows", "hillmen", "trebuchet",
    "castles", "sailing", "crop_rotation", "gunpowder", "matchlock",
    "banking", "grenadiers", "dragoons", "navigation", "ships_of_the_line",
    "steam_power", "railways", "rifling", "steel_guns", "field_engineering",
    "ironclads", "combustion", "machine_guns", "tanks", "heavy_artillery",
    "anti_tank_guns", "dreadnoughts", "submarines", "flight", "bombers",
    "mechanisation", "heavy_armour", "rocket_artillery", "assault_rifles",
    "jet_engines", "carriers", "rocketry", "satellites", "ballistic_missiles",
    "guided_weapons", "composite_armour",
]

LINES = [
    "conscription", "farming", "mining", "logistics",
    "inf.weapons", "grn.weapons", "art.protection", "arm.weapons",
    "mot.weapons", "hvt.weapons", "mec.weapons", "arm.protection",
    "inf.protection", "mtn.weapons", "medicine", "industry", "discipline",
    "drill", "fieldworks", "staffwork", "drilling", "refining",
    "mot.mobility", "arm.mobility", "mec.protection", "hvt.protection",
    "atg.weapons", "art.weapons", "cav.weapons", "cav.protection",
    "cav.mobility", "mec.mobility", "mtn.protection", "eng.weapons",
]

TERRAIN_DEF = {"hill": 1.5, "mountain": 2.0, "forest": 1.25}
BAD_STATE = ("routing", "digging", "refitting", "preparing", "pinned")
ATTACK_MIN_UNITS = 6
ATTACK_MIN_RDY = 65
P_GO = 0.45
P_GO_RELAX = 0.35
RELAX_AFTER = 96
REFIT_CAP = 30
REFIT_MIN_RES = 250
EXPAND_SHARE = 0.6
SAVE_FROM_UNITS = 150

RES_RICH = 1500
MAX_DEPOTS = 6
DEPOT_LOAD = 20


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


def _recruit(api, counts, total, pend):
    left = {
        "res": api.stock.get("res", 0) - pend, "mp": api.mp,
        "steel": api.stock.get("steel", 0), "oil": api.stock.get("oil", 0),
        "rare": api.stock.get("rare", 0),
    }
    boost = {}
    if left["steel"] > 800:
        boost = {"arm": 1.5, "hvt": 1.6, "mec": 1.4, "rkt": 1.4}
    n = 3
    if left["res"] > 3000:
        n = 10
    elif left["res"] > 800:
        n = 6
    elif left["res"] > 400:
        n = 4
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


def _research(api, total):
    # One slot for the discovery tree (in order), the other for upgrades.
    # Returns the res to save for the next discovery (0 if none pending).
    tree = api.tree or {}
    slots = list(api.research or [])
    disc_busy = any(r[0] in tree for r in slots)
    pend = 0
    if not disc_busy:
        for d in DISC_ORDER:
            tr = tree.get(d)
            if not tr or tr.get("status") != "open":
                continue
            cost = tr.get("res_now") or (tr.get("cost") or {}).get("res", 0) or 0
            if api.stock.get("res", 0) >= cost + 60:
                api.cmd("research %s" % d)
                slots = list(api.research or [])
            elif total >= SAVE_FROM_UNITS:
                pend = cost
            break
    if len(slots) >= 2:
        return pend
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
            return pend
    return pend


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


def _diplomacy(api):
    for o in api.offers_in or []:
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
        elif o.get("kind") == "trade":
            give = sum((o.get("you_give") or {}).values())
            get = sum((o.get("they_give") or {}).values())
            if give <= get:
                api.cmd("accept %s" % o["id"])


def _trade(api, m, t):
    # "trade A X for B Y" = partner gives A X, we give B Y
    if t - m.get("trade_t", -999) < 12:
        return
    if len(api.offers_out or []) >= 3 or not api.met:
        return
    st = api.stock
    f = api.met[(t // 12) % len(api.met)]
    if st.get("steel", 0) < 150 and st.get("res", 0) > 600:
        m["trade_t"] = t
        api.cmd("offer %s trade 150 steel for 60 res" % f)
        return
    for what, keep in (("oil", 800), ("rubber", 600)):
        if st.get(what, 0) > keep + 200 and st.get("res", 0) < RES_RICH:
            m["trade_t"] = t
            api.cmd("offer %s trade 80 res for 200 %s" % (f, what))
            return


def _economy(api, m, t):
    if t - m.get("econ_t", -999) < 12:
        return
    res = api.stock.get("res", 0)
    if res < 700:
        return
    econ = api.economy or {}
    works = econ.get("works") or []
    if len(works) >= 4:
        return
    busy = set(w[1] for w in works if len(w) >= 2)
    provs = econ.get("provs") or []
    for pv in provs[:8]:
        p = pv.get("prov")
        if p is None or p in busy:
            continue
        dev = pv.get("dev", 0) or 0
        room = pv.get("room", 1)
        if room is not None and room <= 0:
            continue
        if dev >= 6:
            continue
        if (res >= 50 * (dev + 1) + RES_RESERVE
                and api.stock.get("coal", 0) >= 8 * (dev + 1)):
            r = api.cmd("develop P%d" % p)
            if str(r).startswith("ok"):
                m["econ_t"] = t
                return
    for pv in sorted(provs, key=lambda x: -(x.get("agg", 0) or 0))[:8]:
        p = pv.get("prov")
        if p is None or p in busy:
            continue
        inf = pv.get("infra", 0) or 0
        if inf >= 3:
            continue
        if (res >= 30 * (inf + 1) + RES_RESERVE
                and api.stock.get("steel", 0) >= 6 * (inf + 1)):
            r = api.cmd("build P%d" % p)
            if str(r).startswith("ok"):
                m["econ_t"] = t
                return


def _depots(api, m, t):
    if t - m.get("depot_t", -999) < 48:
        return
    dep = api.depots or {}
    if len(dep) >= MAX_DEPOTS or api.stock.get("res", 0) < 300:
        return
    busy = False
    for d in dep.values():
        if (d.get("load", 0) or 0) > DEPOT_LOAD:
            busy = True
    if not busy:
        return
    best = None
    best_d = -1.0
    for p in api.border:
        pv = api.provs.get(p)
        if not pv or p in dep or p == api.capital or not pv.get("supplied"):
            continue
        x = pv.get("x", 0) or 0
        y = pv.get("y0", 0) or 0
        dmin = 1e9
        for q in dep:
            qv = api.provs.get(q, {})
            dx = x - (qv.get("x", 0) or 0)
            dy = y - (qv.get("y0", 0) or 0)
            dd = math.sqrt(dx * dx + dy * dy)
            if dd < dmin:
                dmin = dd
        if dmin > best_d:
            best_d = dmin
            best = p
    if best is None:
        return
    m["depot_t"] = t
    api.cmd("depot P%d 1" % best)


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
                               if u["type"] in ("art", "eng", "arm", "rkt", "hvt")) / n,
            "dirs": 1.0,
        }
        z = float(model.get("b", 0.0))
        for i, f in enumerate(feats):
            std = model["std"][i] or 1.0
            z += model["w"][i] * (x.get(f, 0.0) - model["mean"][i]) / std
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))
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
    threshold = P_GO
    if t - m.get("last_att", 0) >= RELAX_AFTER:
        threshold = P_GO_RELAX
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
            ok = _score(api, qv, e, mine, bonus) >= threshold
        if t - t0 >= 8:
            if ok:
                api.cmd("move %s P%d" % (ids, q))
                m["last_att"] = t
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
        if best is not None and best_p >= threshold:
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
    pend = [0]

    def do_research():
        pend[0] = _research(api, total)

    def do_recruit():
        _recruit(api, counts, total, pend[0])

    for fn in (
        lambda: _diplomacy(api),
        lambda: _trade(api, m, t),
        do_research,
        lambda: _economy(api, m, t),
        lambda: _depots(api, m, t),
        do_recruit,
        lambda: _refit(api),
        lambda: _orders(api, m, units),
    ):
        try:
            fn()
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
