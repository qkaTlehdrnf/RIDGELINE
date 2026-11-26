PREF = {"inf": 4.0, "mot": 4.0, "cav": 1.5, "atg": 2.0, "art": 1.5, "arm": 2.0,
        "mtn": 1.0, "eng": 1.0, "grn": 1.0, "mec": 1.0, "hvt": 0.8, "rkt": 0.5}
BACK = ("art", "atg", "eng", "hvt", "rkt")
LINES = ["mining", "farming", "mot.mobility", "arm.weapons", "inf.weapons",
         "logistics", "medicine", "industry", "mot.weapons", "arm.protection",
         "conscription", "drill", "discipline", "staffwork", "fieldworks",
         "refining", "drilling", "mtn.weapons", "inf.mobility"]
NEED = {"mining": "steel", "drilling": "oil", "refining": "rare"}
SCOUTS = 3


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _border_keys(api):
    b = api.border
    try:
        return list(b.keys())
    except Exception:
        return list(b)


def _tdfn(pr):
    t = str(pr.get("terrain", "plain"))
    if "mount" in t:
        return 2.0
    if "hill" in t:
        return 1.5
    if "forest" in t:
        return 1.25
    return 1.0


def _p_take(api, att, dfn, fort, tdfn, rdy, bonus):
    mdl = getattr(api, "model", None) or {}
    if "w" not in mdl:
        return None
    x = {"log_ratio": math.log((att + 1.0) / (dfn + 1.0)), "terrain_dfn": tdfn,
         "fort": fort, "city": 0.0, "bonus": bonus, "att_rdy": rdy / 100.0,
         "heavy_share": 0.2, "dirs": 1.0}
    s = mdl["b"]
    for i, f in enumerate(mdl["features"]):
        sd = mdl["std"][i] or 1.0
        s += mdl["w"][i] * (x.get(f, 0.0) - mdl["mean"][i]) / sd
    s = max(-30.0, min(30.0, s))
    return 1.0 / (1.0 + math.exp(-s))


def _alarm(api, ctx):
    cap = api.capital
    near = [cap] + list(api.provs.get(cap, {}).get("nbrs", []))
    if any(p in api.enemy for p in near if isinstance(p, int)):
        api.mem["alarm"] = api.t


def _diplo(api, ctx):
    m = api.mem
    t = api.t
    # accept any pact offered to us: fewer units lost, our land stays ours
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
    # offer pacts to met factions we are not already at peace with
    pacts = api.pacts or {}
    sent = m.setdefault("pact_t", {})
    for f in (api.met or []):
        if f in pacts or f == api.me:
            continue
        if t - sent.get(f, -999) < 72:
            continue
        sent[f] = t
        api.cmd("offer %s pact" % f)


def _recruit(api, ctx):
    m = api.mem
    if api.income_by.get("res", 0) < -2:
        return
    counts = {}
    for u in ctx["units"]:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    res = api.res
    mp = api.mp
    stock = api.stock
    reserve = 25
    cap = api.capital
    while counts.get("rec", 0) < SCOUTS:
        c = api.costs.get("rec")
        if not c or res - reserve < c[0] or mp < c[1]:
            break
        if not api.cmd("recruit rec P%d" % cap).startswith("ok"):
            break
        res -= c[0]
        mp -= c[1]
        counts["rec"] = counts.get("rec", 0) + 1
    pref = dict(PREF)
    if stock.get("oil", 0) > 500:
        pref["arm"] = 3.0
        pref["mot"] = 5.0
    if api.t - m.get("alarm", -999) <= 12:
        pref["inf"] = 8.0
        pref["atg"] = 3.0
    n = 0
    while n < 6:
        fight = sum(counts.get(k, 0) for k in pref)
        tw = sum(pref.values())
        ranked = sorted(((w / tw * (fight + 4) - counts.get(k, 0), k)
                         for k, w in pref.items()), reverse=True)
        pick = None
        for d, k in ranked:
            c = api.costs.get(k)
            uc = api.unit_costs.get(k, {})
            if not c:
                continue
            if res - reserve < c[0] or mp < c[1]:
                continue
            if any(stock.get(s, 0) < uc.get(s, 0) for s in ("steel", "oil", "rare")):
                continue
            pick = k
            break
        if pick is None:
            break
        if not api.cmd("recruit %s P%d" % (pick, cap)).startswith("ok"):
            break
        c = api.costs[pick]
        res -= c[0]
        mp -= c[1]
        counts[pick] = counts.get(pick, 0) + 1
        n += 1


def _research(api, ctx):
    t = api.t
    maxp = 1 if t < 96 else 2
    running = [r[0] for r in api.research]
    slots = maxp - len(running)
    if slots <= 0:
        return
    avail = dict(api.stock)
    resv = 60 if len(ctx["units"]) < 8 else 25
    for line in LINES:
        if slots <= 0:
            break
        if line in running:
            continue
        info = api.tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost")
        if not cost:
            continue
        need = NEED.get(line)
        if need and api.income_by.get(need, 0) <= 0:
            continue
        good = True
        for k, v in cost.items():
            r = resv if k == "res" else 0
            if avail.get(k, 0) - r < v:
                good = False
                break
        if not good:
            continue
        if api.cmd("research %s" % line).startswith("ok"):
            for k, v in cost.items():
                avail[k] = avail.get(k, 0) - v
            slots -= 1
            running.append(line)


def _scouts(api, ctx):
    m = api.mem
    t = api.t
    ids = []
    for u in ctx["units"]:
        if u["type"] != "rec" or u.get("path") or u.get("explore"):
            continue
        key = str(u["id"])
        if t - m["xp"].get(key, -99) < 24:
            continue
        m["xp"][key] = t
        ids.append(u["id"])
    if ids:
        api.cmd("explore %s" % _sel(ids))


def _assign(api, ctx):
    nb = api.neutral_border or []
    front, expand = [], []
    planned = set()
    for key, plan in ctx["plans"].items():
        planned.update(plan[2])
    for u in ctx["units"]:
        if u["type"] == "rec" or u.get("path") or u["id"] in planned:
            continue
        if u.get("expand") or u.get("front") or u.get("explore") or u.get("fighting"):
            continue
        if u.get("state") != "ready" or u.get("plan", -1) != -1:
            continue
        if u.get("str", 0) < 60 or u.get("old"):
            continue
        if len(front) + len(expand) >= 60:
            break
        if u["type"] in BACK or not nb or u["id"] % 3 == 0:
            front.append(u["id"])
        else:
            expand.append(u["id"])
    if front:
        api.cmd("front %s" % _sel(front))
    if expand:
        api.cmd("expand %s" % _sel(expand))


def _refit(api, ctx):
    m = api.mem
    t = api.t
    if t - m.get("refit_t", -99) < 12:
        return
    if api.res < 200:
        return
    rc = getattr(api, "refit_cost", {}) or {}
    own = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    border = set(ctx["border"])
    spend = {}
    ids = []
    for u in ctx["units"]:
        if len(ids) >= 12:
            break
        if not u.get("old") or u.get("path") or u.get("fighting"):
            continue
        if u.get("state") != "ready" or u.get("prov") not in own or u.get("prov") in border:
            continue
        if not u.get("supplied", True):
            continue
        c = rc.get(u["type"])
        if not c:
            continue
        ok = True
        for k in ("res", "steel", "oil", "rare"):
            need = spend.get(k, 0) + c.get(k, 0)
            if need > api.stock.get(k, 0) - (200 if k == "res" else 0):
                ok = False
                break
        if not ok:
            continue
        for k in ("res", "steel", "oil", "rare"):
            spend[k] = spend.get(k, 0) + c.get(k, 0)
        ids.append(u["id"])
    if ids:
        m["refit_t"] = t
        api.cmd("refit %s" % _sel(ids))


def _retreat(api, ctx):
    m = api.mem
    t = api.t
    cap = api.capital
    if cap is None:
        return
    planned = set()
    for key, plan in ctx["plans"].items():
        planned.update(plan[2])
    ids = []
    for u in ctx["units"]:
        if u["type"] == "rec" or u.get("path") or u.get("front") or u["id"] in planned:
            continue
        if u.get("str", 100) >= 25 or u["prov"] == cap:
            continue
        key = str(u["id"])
        if t - m["retreat"].get(key, -99) < 12:
            continue
        m["retreat"][key] = t
        ids.append(u["id"])
    if ids:
        api.cmd("move %s P%d" % (_sel(ids), cap))


def _attacks(api, ctx):
    m = api.mem
    t = api.t
    plans = m["plan"]
    for key in list(plans.keys()):
        src, t0, ids = plans[key]
        q = int(key)
        pq = api.provs.get(q, {})
        alive = [u for u in ctx["units"]
                 if u["id"] in ids and u["prov"] == src and not u.get("path")]
        if pq.get("owner") == "me" or not alive or t - t0 > 48:
            del plans[key]
            continue
        if t - t0 >= 12 and len(alive) >= 3:
            ready_ids = [u["id"] for u in alive if u.get("rdy", 0) >= 65]
            if len(ready_ids) >= 3:
                g = "g%d_%d" % (q, t)
                api.cmd("group %s %s" % (g, _sel(ready_ids)))
                api.cmd("move %s P%d" % (g, q))
                del plans[key]
                continue
            if t - t0 > 36:
                del plans[key]
    if len(plans) >= 1:
        return
    busy = set(int(k) for k in plans)
    for p in ctx["border"]:
        pr = api.provs.get(p)
        if not pr or pr.get("owner") != "me":
            continue
        force = [u for u in ctx["byprov"].get(p, [])
                 if u["type"] != "rec" and u.get("state") in ("ready", "preparing")
                 and u.get("plan", -1) == -1 and not u.get("path")
                 and u.get("str", 0) >= 60 and u.get("rdy", 0) >= 65]
        if len(force) < 6:
            continue
        force.sort(key=lambda u: -u.get("str", 0))
        force = force[:12]
        mine = sum(u.get("str", 0) for u in force)
        avg_rdy = sum(u.get("rdy", 0) for u in force) / len(force)
        for q in pr.get("nbrs", []):
            if not isinstance(q, int) or q in busy:
                continue
            qp = api.provs.get(q)
            if not qp or qp.get("owner") != "enemy" or qp.get("harsh"):
                continue
            e = api.enemy.get(q)
            es = e.get("str", 0) if e else 60
            fort = qp.get("fort", 0) or 0
            # stricter: 0 of 82 assaults succeeded last war at lower odds
            if mine < 6 * es + 300 + 150 * fort:
                continue
            p_take = _p_take(api, mine, es, fort, _tdfn(qp), avg_rdy, 0.0)
            if p_take is not None and p_take < 0.85:
                continue
            ids = [u["id"] for u in force]
            api.cmd("prepare %s P%d" % (_sel(ids), q))
            plans[str(q)] = [p, t, ids]
            busy.add(q)
            break
        if len(plans) >= 1:
            return


def _fort(api, ctx):
    m = api.mem
    t = api.t
    for p in ctx["border"]:
        key = str(p)
        if t - m["fort"].get(key, -99) < 48:
            continue
        pr = api.provs.get(p, {})
        if (pr.get("fort", 0) or 0) >= 3:
            continue
        ids = [u["id"] for u in ctx["byprov"].get(p, [])
               if u["type"] == "eng" and not u.get("path") and u.get("state") != "digging"]
        if ids:
            m["fort"][key] = t
            api.cmd("fortify %s" % _sel(ids))


def tick(api):
    m = api.mem
    m.setdefault("plan", {})
    m.setdefault("retreat", {})
    m.setdefault("fort", {})
    m.setdefault("xp", {})
    m.setdefault("alarm", -999)
    m.setdefault("refit_t", -99)
    m.setdefault("pact_t", {})
    m.setdefault("err", 0)
    units = list(api.units)
    byprov = {}
    for u in units:
        byprov.setdefault(u["prov"], []).append(u)
    ctx = {"units": units, "byprov": byprov, "border": _border_keys(api),
           "plans": m["plan"]}
    for fn in (_alarm, _diplo, _recruit, _research, _scouts, _attacks, _assign,
               _refit, _retreat, _fort):
        try:
            fn(api, ctx)
        except Exception:
            m["err"] = m.get("err", 0) + 1
