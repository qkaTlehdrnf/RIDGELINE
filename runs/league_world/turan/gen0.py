WEIGHTS = {"inf": 0.26, "mot": 0.12, "mil": 0.06, "mtn": 0.06, "arm": 0.10,
           "atg": 0.08, "art": 0.08, "eng": 0.05, "grn": 0.05, "cav": 0.03,
           "mec": 0.04, "rec": 0.03, "rkt": 0.0, "hvt": 0.0}
REAR_TYPES = ("rec", "art", "atg", "eng", "hvt", "rkt")
HEAVY = ("art", "eng", "arm", "hvt", "rkt")
RESEARCH = ["farming", "industry", "inf.weapons", "mot.weapons", "arm.weapons",
            "inf.protection", "logistics", "conscription", "arm.protection",
            "mot.mobility", "medicine", "drill", "discipline", "mining",
            "drilling", "fieldworks", "staffwork", "refining",
            "mtn.weapons", "mot.protection"]


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


def _economy(api):
    if len(api.research) >= 2 or api.res < 150:
        return
    st = api.stock
    avail = {"res": api.res, "steel": st.get("steel", 0),
             "oil": st.get("oil", 0), "rare": st.get("rare", 0)}
    keep = {"res": 120, "steel": 30, "oil": 30, "rare": 0}
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
    if len(units) > 20 and api.income <= 0:
        return
    costs = api.unit_costs
    avail = {"res": api.res, "steel": api.stock.get("steel", 0),
             "oil": api.stock.get("oil", 0), "rare": api.stock.get("rare", 0)}
    mp = api.mp
    have = {}
    for u in units:
        have[u["type"]] = have.get(u["type"], 0) + 1
    made = 0
    for _ in range(3):
        n = len(units) + made + 1
        options = []
        if have.get("rec", 0) < 2 and api.t < 48 and "rec" in costs:
            options.append((1e9, "rec"))
        for typ, w in WEIGHTS.items():
            if w <= 0 or typ not in costs:
                continue
            options.append((w * n - have.get(typ, 0), typ))
        options.sort(key=lambda x: x[0], reverse=True)
        cand = None
        for d, typ in options:
            c = costs[typ]
            if _can(c, avail, {"res": 90}) and (c.get("mp", 0) or 0) <= mp - 10:
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
    return (u["str"] >= 60 and u["rdy"] >= 55 and not u.get("path")
            and u.get("plan", -1) == -1 and i not in refit and i not in busy
            and u.get("state") in ("ready", "defending")
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
            "terrain_dfn": tdfn, "fort": fort, "city": city, "bonus": 0.06,
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

    for k in list(plans.keys()):
        tt, ids = plans[k]
        tgt = int(k)
        live = [i for i in ids if i in byid and byid[i].get("plan", -1) == tgt]
        if not live or t - tt > 72:
            if live:
                api.cmd("hold " + _ids(live))
            del plans[k]
            continue
        if t - tt >= 6:
            api.cmd("move %s P%d" % (_ids(live), tgt))
            del plans[k]

    if len(plans) >= 2 or t < 12:
        m["plans"] = plans
        return

    busy = set()
    for k in plans:
        busy.update(plans[k][1])

    cands = []
    seen = set()
    for tg, tp in api.provs.items():
        if tp.get("owner") != "enemy" or tg in seen:
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
        if ours < 2.0 * es + 40.0:
            continue
        if api.model and api.model.get("w"):
            if _prob(api, tg, atk, srcs, ours, es) < 0.55:
                continue
        cands.append((ours / (es + 40.0), tg, ids))

    cands.sort(key=lambda x: x[0], reverse=True)
    used = set()
    for margin, tg, ids in cands:
        if len(plans) >= 2:
            break
        if str(tg) in plans:
            continue
        ids2 = [i for i in ids if i not in used]
        if not ids2:
            continue
        r = api.cmd("prepare %s P%d" % (_ids(ids2), tg))
        if _ok(r):
            plans[str(tg)] = [t, ids2]
            used.update(ids2)
    m["plans"] = plans


def _assign(api, units, m):
    refit = set(m.get("refit", []))
    plans = m.get("plans", {})
    busy = set()
    for k in plans:
        busy.update(plans[k][1])
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
        _refit(api, units, m)
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
