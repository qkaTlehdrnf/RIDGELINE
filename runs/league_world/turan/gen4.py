WEIGHTS = {"inf": 0.10, "mot": 0.22, "mil": 0.0, "mtn": 0.04, "arm": 0.22,
           "atg": 0.08, "art": 0.10, "eng": 0.04, "grn": 0.04, "cav": 0.02,
           "mec": 0.04, "rec": 0.02, "rkt": 0.0, "hvt": 0.0}
REAR_TYPES = ("rec", "art", "atg", "eng", "rkt")
HEAVY = ("art", "eng", "arm", "hvt", "rkt")
RESEARCH = ["arm.protection", "mot.mobility", "mot.protection", "farming",
            "medicine", "logistics", "arm.weapons", "mot.weapons", "industry",
            "drill", "discipline", "inf.protection", "mining", "drilling",
            "fieldworks", "staffwork", "refining", "mtn.weapons", "inf.weapons",
            "conscription"]
MAX_PLANS = 3
OFFER_GAP = 96
PLAN_TIMEOUT = 96


def _pid(x):
    if isinstance(x, int):
        return x
    d = ""
    for ch in str(x):
        if ch.isdigit():
            d += ch
    return int(d) if d else -1


def _ok(s):
    return isinstance(s, str) and s.startswith("ok")


def _ids(lst):
    return ",".join([str(i) for i in lst])


def _can(c, avail, keep):
    for k in ("res", "steel", "oil", "rare"):
        need = c.get(k, 0) or 0
        if need > 0 and avail.get(k, 0) - keep.get(k, 0) < need:
            return False
    return True


def _diplomacy(api):
    m = api.mem
    last = m.setdefault("dip", {})
    for o in api.offers_in:
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
    pending = set()
    for o in api.offers_out:
        pending.add(o.get("to"))
    sent = 0
    for f in api.met:
        if sent >= 3:
            break
        if f in api.pacts or f in pending:
            continue
        if api.t - last.get(f, -999) < OFFER_GAP:
            continue
        api.cmd("offer %s pact 240" % f)
        last[f] = api.t
        sent += 1


def _economy(api):
    if len(api.research) >= 2 or api.res < 120:
        return
    st = api.stock
    avail = {"res": api.res, "steel": st.get("steel", 0),
             "oil": st.get("oil", 0), "rare": st.get("rare", 0)}
    keep = {"res": 90, "steel": 20, "oil": 20, "rare": 0}
    for line in RESEARCH:
        tt = api.tech.get(line)
        if not tt or tt.get("status") != "open":
            continue
        c = tt.get("cost")
        if not c:
            continue
        if not _can(c, avail, keep):
            continue
        if _ok(api.cmd("research " + line)):
            return


def _recruit(api, units):
    if len(units) > 24 and api.income <= 0:
        return
    costs = api.unit_costs
    st = api.stock
    weights = dict(WEIGHTS)
    # spend idle special resources on heavy armour rather than hoarding them
    if st.get("rare", 0) >= 40 and st.get("steel", 0) >= 60 and "hvt" in costs:
        weights["hvt"] = 0.08
    avail = {"res": api.res, "steel": st.get("steel", 0),
             "oil": st.get("oil", 0), "rare": st.get("rare", 0)}
    mp = api.mp
    have = {}
    for u in units:
        have[u["type"]] = have.get(u["type"], 0) + 1
    made = 0
    for _ in range(4):
        n = len(units) + made + 1
        options = []
        if have.get("rec", 0) < 2 and api.t < 48 and "rec" in costs:
            options.append((1e9, "rec"))
        for typ, w in weights.items():
            if w <= 0 or typ not in costs:
                continue
            options.append((w * n - have.get(typ, 0), typ))
        options.sort(key=lambda x: x[0], reverse=True)
        cand = None
        for d, typ in options:
            c = costs[typ]
            if _can(c, avail, {"res": 60}) and (c.get("mp", 0) or 0) <= mp - 4:
                cand = typ
                break
        if cand is None:
            break
        c = costs[cand]
        r = api.cmd("recruit %s 1 P%d" % (cand, api.capital))
        if not _ok(r):
            break
        made += 1
        have[cand] = have.get(cand, 0) + 1
        for k in ("res", "steel", "oil", "rare"):
            avail[k] = avail[k] - (c.get(k, 0) or 0)
        mp -= (c.get("mp", 0) or 0)


def _busy_ids(m):
    busy = set(m.get("refit", []))
    for k in m.get("plans", {}):
        busy.update(m["plans"][k][1])
    return busy


def _refit_old(api, units, m):
    if api.old_units <= 0 or api.t < 6:
        return
    busy = _busy_ids(m)
    avail = {"res": api.res, "steel": api.stock.get("steel", 0),
             "oil": api.stock.get("oil", 0), "rare": api.stock.get("rare", 0)}
    cost_by_type = api.refit_cost or {}
    batch = {}
    total = 0
    for u in units:
        if total >= 8:
            break
        if not u.get("old") or u["id"] in busy or u.get("path"):
            continue
        if u.get("state") != "ready" or not u.get("supplied") or u.get("dry"):
            continue
        if u.get("str", 0) < 60:
            continue
        typ = u["type"]
        c = cost_by_type.get(typ)
        if not c or not _can(c, avail, {"res": 150}):
            continue
        for k in ("res", "steel", "oil", "rare"):
            avail[k] = avail[k] - (c.get(k, 0) or 0)
        batch.setdefault(typ, []).append(u["id"])
        total += 1
    for typ, ids in batch.items():
        api.cmd("refit " + _ids(ids))


def _refit(api, units, m):
    rs = set(m.get("refit", []))
    cap = api.capital
    for u in units:
        i = u["id"]
        if u.get("path"):
            continue
        if i in rs:
            if u["str"] >= 85:
                api.cmd("front %d" % i)
                rs.discard(i)
        else:
            if u["str"] < 45 and u["prov"] != cap:
                api.cmd("move %d P%d" % (i, cap))
                rs.add(i)
    m["refit"] = list(rs)


def _eligible(u, refit, busy):
    i = u["id"]
    return (u["str"] >= 45 and u["rdy"] >= 50 and not u.get("path")
            and u.get("plan", -1) == -1 and i not in refit and i not in busy
            and u.get("state") in ("ready", "defending", "pinned")
            and not u.get("dry") and u["type"] != "rec")


def _prob(api, tg, atk, srcs, ours, es):
    md = api.model
    feats = md.get("features", [])
    w = md.get("w", [])
    mean = md.get("mean", [])
    std = md.get("std", [])
    z = md.get("b", 0.0)
    pr = api.provs.get(tg, {})
    terr = str(pr.get("terrain", "plain"))
    tdfn = 1.0
    if "forest" in terr:
        tdfn = 1.25
    elif "hill" in terr:
        tdfn = 1.5
    elif "mount" in terr:
        tdfn = 2.0
    fort = float(pr.get("fort", 0) or 0)
    city = 1.0 if pr.get("city") else 0.0
    n = float(len(atk)) if atk else 1.0
    heavy = 0.0
    rdy = 0.0
    for u in atk:
        rdy += u["rdy"]
        if u["type"] in HEAVY:
            heavy += 1.0
    heavy = heavy / n
    rdy = rdy / n / 100.0
    vals = {"log_ratio": math.log((ours / 100.0 + 1.0) / (es / 100.0 + 1.0)),
            "terrain_dfn": tdfn, "fort": fort, "city": city, "bonus": 0.5,
            "att_rdy": rdy, "heavy_share": heavy, "dirs": float(len(set(srcs)))}
    for j, f in enumerate(feats):
        if j >= len(w) or j >= len(mean) or j >= len(std):
            break
        x = vals.get(f, 0.0)
        sd = std[j] if std[j] else 1.0
        z += w[j] * (x - mean[j]) / sd
    if z > 30:
        z = 30.0
    if z < -30:
        z = -30.0
    return 1.0 / (1.0 + math.exp(-z))


def _attack(api, units, m):
    t = api.t
    byid = {}
    by_prov = {}
    for u in units:
        byid[u["id"]] = u
        by_prov.setdefault(u["prov"], []).append(u)
    refit = set(m.get("refit", []))
    plans = m.get("plans", {})
    pact_names = set(api.pacts.keys())

    for k in list(plans.keys()):
        rec = plans[k]
        tt, ids = rec[0], rec[1]
        wait = rec[2] if len(rec) > 2 else 40
        tgt = int(k)
        live = [i for i in ids if i in byid and byid[i].get("plan", -1) == tgt]
        if not live or t - tt > PLAN_TIMEOUT:
            if live:
                api.cmd("hold " + _ids(live))
            del plans[k]
            continue
        if api.owner_name.get(tgt) in pact_names:
            api.cmd("hold " + _ids(live))
            del plans[k]
            continue
        if t - tt >= wait:
            api.cmd("move %s P%d" % (_ids(live), tgt))
            del plans[k]

    if len(plans) >= MAX_PLANS or t < 12:
        m["plans"] = plans
        return

    busy = _busy_ids(m)
    cands = []
    seen = set()
    for tg, tp in api.provs.items():
        if tp.get("owner") != "enemy" or tg in seen:
            continue
        if api.owner_name.get(tg) in pact_names:
            continue
        srcs = []
        ids = []
        atk = []
        for nb in tp.get("nbrs", []):
            sp = _pid(nb)
            s_pr = api.provs.get(sp)
            if not s_pr or s_pr.get("owner") != "me":
                continue
            for u in by_prov.get(sp, []):
                if _eligible(u, refit, busy):
                    ids.append(u["id"])
                    atk.append(u)
                    srcs.append(sp)
        if not ids:
            continue
        seen.add(tg)
        ours = 0.0
        for u in atk:
            ours += u["str"]
        e = api.enemy.get(tg)
        if e:
            es = float(e.get("str", 0))
            if not e.get("exact", False):
                es *= 1.3
        else:
            es = 15.0
        fort = float(tp.get("fort", 0) or 0)
        # heavily fortified targets only when we clearly outnumber the defenders
        need = 2.0 if fort < 3 else 4.0
        if ours < need * es + 30.0:
            continue
        if api.model and api.model.get("w"):
            if _prob(api, tg, atk, srcs, ours, es) < 0.5:
                continue
        cands.append((ours / (es + 30.0), tg, ids))

    cands.sort(key=lambda x: x[0], reverse=True)
    used = set()
    for margin, tg, ids in cands:
        if len(plans) >= MAX_PLANS:
            break
        if str(tg) in plans:
            continue
        ids2 = [i for i in ids if i not in used]
        if not ids2:
            continue
        r = api.cmd("prepare %s P%d" % (_ids(ids2), tg))
        if _ok(r):
            # longer wait builds the prepared bonus (+1%/h, up to +50%)
            wait = 24 if margin >= 4.0 else 40
            plans[str(tg)] = [t, ids2, wait]
            used.update(ids2)
    m["plans"] = plans


def _assign(api, units, m):
    refit = set(m.get("refit", []))
    busy = _busy_ids(m)
    nb = len(api.neutral_border)
    for u in units:
        i = u["id"]
        if i in refit or i in busy:
            continue
        if u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
            continue
        if u.get("plan", -1) != -1:
            continue
        if u.get("state") in ("moving", "assault", "preparing", "routing", "digging"):
            continue
        typ = u["type"]
        if typ == "rec":
            api.cmd("explore %d" % i)
        elif typ in REAR_TYPES or nb == 0:
            api.cmd("front %d" % i)
        else:
            api.cmd("expand %d" % i)


def tick(api):
    m = api.mem
    m["n"] = m.get("n", 0) + 1
    units = api.units
    try:
        _diplomacy(api)
    except Exception:
        pass
    try:
        _refit(api, units, m)
    except Exception:
        pass
    try:
        _refit_old(api, units, m)
    except Exception:
        pass
    try:
        _attack(api, units, m)
    except Exception:
        pass
    try:
        _assign(api, units, m)
    except Exception:
        pass
    try:
        _recruit(api, units)
    except Exception:
        pass
    try:
        _economy(api)
    except Exception:
        pass
