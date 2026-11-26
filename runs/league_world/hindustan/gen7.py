TERRAIN_DFN = (("forest", 1.25), ("hill", 1.5), ("mountain", 2.0), ("plain", 1.0))
PRI = {"farming": 0, "inf.weapons": 1, "inf.protection": 2, "industry": 3,
       "logistics": 4, "mining": 5, "art.weapons": 6, "arm.protection": 7,
       "arm.weapons": 8, "medicine": 9, "discipline": 10, "fieldworks": 11,
       "staffwork": 12, "drill": 13, "conscription": 14, "mot.mobility": 15,
       "drilling": 16, "refining": 17}
RES_RESERVE = 250
MP_RESERVE = 150
ARMY_CAP = 900
RECRUIT_PER_TICK = 12
ATTACK_RATIO = 2.2
ATTACK_P = 0.5
ATTACK_MIN_RDY = 60
ATTACK_MIN_STR = 70
ATTACK_MAX_FORT = 1
ATTACK_MIN_UNITS = 3
ATTACK_MAX_UNITS = 30
REFIT_RES_FLOOR = 400
REFIT_EVERY = 6
REFIT_MAX = 80
PACT_EVERY = 96
DEPOT_MAX = 8
DEPOT_LOAD = 30
DEPOT_RES = 800
COMBAT_OK = ("inf", "mil", "mtn", "mot", "arm", "art", "eng", "grn", "cav", "atg", "mec", "hvt", "rkt")
LAND_TYPES = ("inf", "mtn", "mot", "mec", "grn", "cav", "mil")


def _count(api, name):
    try:
        api.count(name, 1)
    except Exception:
        pass


def _sig(x):
    if x < -30:
        return 0.0
    if x > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def _ints(lst):
    out = []
    for x in lst:
        try:
            out.append(int(str(x).replace("~", "").replace("P", "").strip()))
        except Exception:
            pass
    return out


def _ik(k):
    try:
        return int(str(k).replace("P", "").replace("~", "").strip())
    except Exception:
        return None


def _nbrs(api, p):
    pr = api.provs.get(p)
    if not pr:
        return []
    return _ints(pr.get("nbrs", []))


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _terr_dfn(api, q):
    pr = api.provs.get(q) or {}
    tr = str(pr.get("terrain", "plain"))
    for name, d in TERRAIN_DFN:
        if name in tr:
            return d
    return 1.0


def _assault_p(api, att, dfn, terr, fort, city, rdy, heavy, dirs):
    m = api.model or {}
    if not m.get("w"):
        return 0.5
    feats = {"log_ratio": math.log((att + 1.0) / (dfn + 1.0)), "terrain_dfn": terr,
             "fort": fort, "city": city, "bonus": 0.0, "att_rdy": rdy,
             "heavy_share": heavy, "dirs": dirs}
    z = m.get("b", 0.0)
    for i, f in enumerate(m["features"]):
        sd = m["std"][i] or 1.0
        z += m["w"][i] * ((feats.get(f, 0.0) - m["mean"][i]) / sd)
    return _sig(z)


def _affordable(api, ut, left, mp_left):
    uc = api.unit_costs.get(ut)
    if not uc:
        return False
    if left.get("res", 0) - uc.get("res", 0) < RES_RESERVE:
        return False
    if mp_left - uc.get("mp", 0) < MP_RESERVE:
        return False
    for k in ("steel", "oil", "rare"):
        if left.get(k, 0) < uc.get(k, 0):
            return False
    return True


def _research(api, left):
    tech = api.tech or {}
    busy = len(api.research or [])
    if busy >= 2:
        return left
    cands = []
    for line, info in tech.items():
        if info.get("status") != "open":
            continue
        cost = info.get("cost")
        if not cost:
            continue
        cands.append((PRI.get(line, 50), line, cost))
    cands.sort(key=lambda c: c[0])
    for _, line, cost in cands:
        if busy >= 2:
            break
        if left.get("res", 0) - cost.get("res", 0) < RES_RESERVE:
            continue
        if any(left.get(k, 0) < cost.get(k, 0) for k in ("steel", "oil", "rare")):
            continue
        r = api.cmd("research %s" % line)
        if r.startswith("ok"):
            busy += 1
            for k in ("res", "steel", "oil", "rare"):
                left[k] = left.get(k, 0) - cost.get(k, 0)
    return left


def _pick(api, counts, total, left, mp_left):
    tot = max(total, 1)
    inc = api.income_by or {}
    order = []
    if counts.get("rec", 0) < 3:
        order.append("rec")
    if counts.get("art", 0) < 0.20 * tot:
        order.append("art")
    if counts.get("eng", 0) < 0.05 * tot:
        order.append("eng")
    if inc.get("steel", 0) > 0 and inc.get("oil", 0) > 0 and counts.get("arm", 0) < 0.12 * tot:
        order.append("arm")
    if counts.get("atg", 0) < 0.05 * tot:
        order.append("atg")
    order.append("inf")
    if inc.get("oil", 0) > 0:
        order.append("mot")
    order += ["cav", "mil"]
    for ut in order:
        if _affordable(api, ut, left, mp_left):
            return ut
    return None


def _recruit(api, left):
    units = api.units or []
    if len(units) >= ARMY_CAP:
        return
    if api.income < -50 and api.res < 1000:
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)
    mp_left = api.mp
    for _ in range(RECRUIT_PER_TICK):
        if total >= ARMY_CAP:
            break
        ut = _pick(api, counts, total, left, mp_left)
        if ut is None:
            break
        r = api.cmd("recruit %s P%d" % (ut, api.capital))
        if not r.startswith("ok"):
            break
        uc = api.unit_costs[ut]
        left["res"] = left.get("res", 0) - uc.get("res", 0)
        mp_left -= uc.get("mp", 0)
        for k in ("steel", "oil", "rare"):
            left[k] = left.get(k, 0) - uc.get(k, 0)
        counts[ut] = counts.get(ut, 0) + 1
        total += 1


def _refit(api, left):
    if api.t % REFIT_EVERY != 0:
        return
    spare = left.get("res", 0) - REFIT_RES_FLOOR
    if spare <= 0:
        return
    rc = api.refit_cost or {}
    old = [u for u in (api.units or [])
           if u.get("old") and u.get("state") == "ready" and not u.get("path")
           and u.get("supplied") and not u.get("fighting")]
    ids = []
    for u in old:
        c = (rc.get(u["type"]) or {}).get("res", 0)
        if c > spare or len(ids) >= REFIT_MAX:
            continue
        spare -= c
        ids.append(u["id"])
    if ids:
        api.cmd("refit %s" % _sel(ids))


def _depots(api, mem):
    if api.t % 24 != 0 or api.t < 48:
        return
    dep = api.depots or {}
    if len(dep) >= DEPOT_MAX or api.res < DEPOT_RES:
        return
    loaded = [v for v in dep.values() if (v.get("load", 0) or 0) > DEPOT_LOAD]
    if not loaded:
        return
    if api.t - mem.get("depot_try", -1000) < 48:
        return
    have = set()
    pos = []
    for k in dep:
        q = _ik(k)
        if q is None:
            continue
        have.add(q)
        pr = api.provs.get(q) or {}
        pos.append((pr.get("x", 0) or 0, pr.get("y0", 0) or 0))
    if not pos:
        return
    border = set(_ints(list((api.border or {}).keys())))
    best = None
    for q, pr in api.provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied") or pr.get("harsh"):
            continue
        if q in have:
            continue
        x, y = pr.get("x", 0) or 0, pr.get("y0", 0) or 0
        d = min((x - px) ** 2 + (y - py) ** 2 for px, py in pos)
        if q in border:
            d *= 1.3
        if pr.get("city"):
            d *= 1.5
        if best is None or d > best[0]:
            best = (d, q)
    if best:
        mem["depot_try"] = api.t
        api.cmd("depot P%d 1" % best[1])


def _diplomacy(api, mem):
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
    if api.t % PACT_EVERY != 0:
        return
    pacts = api.pacts or {}
    last = mem.setdefault("pact_offer", {})
    sent = 0
    for f in (api.met or []):
        if f in pacts or sent >= 2:
            continue
        if api.t - last.get(f, -10000) < PACT_EVERY * 2:
            continue
        api.cmd("offer %s pact 240" % f)
        last[f] = api.t
        sent += 1


def _attack(api, mem, free, used):
    t = api.t
    plans = mem.setdefault("plans", {})
    all_units = {u["id"]: u for u in api.units}
    for q in list(plans.keys()):
        t0, ids = plans[q]
        ids2 = [i for i in ids if i in all_units]
        if not ids2 or t - t0 > 20:
            del plans[q]
            continue
        if t - t0 >= 8:
            r = api.cmd("move %s P%d" % (_sel(ids2), q))
            if r.startswith("ok"):
                _count(api, "assault_launched")
            used.update(ids2)
            del plans[q]
    if plans:
        return

    pacts = api.pacts or {}
    owners = api.owner_name or {}
    byprov = {}
    for u in free:
        if u["type"] == "rec":
            continue
        byprov.setdefault(u["prov"], []).append(u)

    best = None
    for q0, ed in (api.enemy or {}).items():
        try:
            q = int(q0)
        except Exception:
            continue
        if owners.get(q) in pacts:
            continue
        dfn = ed.get("str", 0) or 0
        if dfn <= 0:
            continue
        qpr = api.provs.get(q) or {}
        fort = qpr.get("fort", 0) or 0
        if fort > ATTACK_MAX_FORT:
            continue
        ulist = []
        adj = 0
        for p in _nbrs(api, q):
            got = [u for u in byprov.get(p, [])
                   if u["str"] >= ATTACK_MIN_STR and u["rdy"] >= ATTACK_MIN_RDY]
            if got:
                adj += 1
                ulist.extend(got)
        if len(ulist) < ATTACK_MIN_UNITS:
            continue
        att = sum(u["str"] for u in ulist)
        if att < ATTACK_RATIO * dfn:
            continue
        heavy = sum(1 for u in ulist if u["type"] in ("art", "eng", "arm")) / float(len(ulist))
        rdy = sum(u["rdy"] for u in ulist) / (100.0 * len(ulist))
        city = 1.0 if qpr.get("city") else 0.0
        p_take = _assault_p(api, att, dfn, _terr_dfn(api, q), fort, city, rdy, heavy, float(adj))
        if p_take < ATTACK_P:
            continue
        score = p_take * att / (dfn + 1.0)
        if best is None or score > best[0]:
            best = (score, q, [u["id"] for u in ulist][:ATTACK_MAX_UNITS])

    if best:
        _, q, ids = best
        r = api.cmd("prepare %s P%d" % (_sel(ids), q))
        if r.startswith("ok"):
            _count(api, "assault_prepared")
            plans[q] = (t, ids)
            used.update(ids)
            if len(ids) >= 3:
                api.cmd("group sk%d %s" % (t, _sel(ids)))


def _orders(api, mem):
    units = api.units or []
    free = [u for u in units if not u.get("path") and u.get("state") == "ready"]
    used = set()

    rec_idle = [u["id"] for u in free if u["type"] == "rec" and not u.get("explore")]
    if rec_idle:
        api.cmd("explore %s" % _sel(rec_idle[:8]))
        used.update(rec_idle)

    _attack(api, mem, free, used)

    combat = [u for u in free
              if u["type"] != "rec" and u["id"] not in used
              and not u.get("front") and not u.get("expand") and not u.get("explore")
              and u["str"] >= 40]

    neutral = api.neutral_border or []
    if neutral and combat:
        land = [u["id"] for u in combat if u["type"] in LAND_TYPES]
        k = min(len(combat) // 2, max(1, len(neutral)), 12)
        ids = land[:k]
        if ids:
            r = api.cmd("expand %s" % _sel(ids))
            if r.startswith("ok"):
                used.update(ids)

    rest = [u["id"] for u in combat if u["id"] not in used and u["type"] in COMBAT_OK]
    if rest:
        api.cmd("front %s" % _sel(rest))


def tick(api):
    mem = api.mem
    left = dict(api.stock)
    try:
        _diplomacy(api, mem)
    except Exception as e:
        mem["err_dip"] = str(e)
    try:
        left = _research(api, left)
    except Exception as e:
        mem["err_research"] = str(e)
    try:
        _refit(api, left)
    except Exception as e:
        mem["err_refit"] = str(e)
    try:
        _depots(api, mem)
    except Exception as e:
        mem["err_depots"] = str(e)
    try:
        _recruit(api, left)
    except Exception as e:
        mem["err_recruit"] = str(e)
    try:
        _orders(api, mem)
    except Exception as e:
        mem["err_orders"] = str(e)
    mem["calls"] = mem.get("calls", 0) + 1
