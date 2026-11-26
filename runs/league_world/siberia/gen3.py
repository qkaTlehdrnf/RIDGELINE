def _f(x):
    try:
        return float(x)
    except Exception:
        return 0.0

TDM = {'p': 1.0, 'f': 1.25, 'h': 1.5, 'm': 2.0}

def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

def _model_p(api, feats):
    md = api.model or {}
    try:
        w = md["w"]; mu = md["mean"]; sd = md["std"]; b = md["b"]
        z = b
        for i in range(len(w)):
            z += w[i] * (feats[i] - mu[i]) / (sd[i] or 1.0)
        return _sig(z)
    except Exception:
        return _sig(1.2 * feats[0] - 0.8 + 0.3 * (feats[7] - 1))

def _afford(api, cost, reserve):
    if not cost: return False
    for k, v in cost.items():
        if k == 'res':
            if api.res - v < reserve: return False
        elif k in ('steel', 'oil', 'rare'):
            if api.stock.get(k, 0) < v: return False
    return True

PRI = ["farming", "conscription", "industry", "logistics", "mining", "inf.protection",
       "drill", "art.weapons", "inf.weapons", "medicine", "discipline", "fieldworks",
       "staffwork", "refining", "drilling", "atg.weapons", "art.protection",
       "inf.mobility", "art.mobility", "atg.protection", "cav.weapons", "cav.protection",
       "mtn.weapons", "mtn.protection"]

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    n = len(api.research)
    for line in PRI:
        if n >= 2: break
        if line in busy: continue
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open": continue
        if _afford(api, tl.get("cost"), 40):
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                n += 1

def _diplo(api, m):
    try:
        for o in api.offers_in:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
    except Exception:
        pass
    if api.t - m.get("dip_t", -999) < 48: return
    m["dip_t"] = api.t
    out = set()
    try:
        for o in api.offers_out:
            out.add(o.get("to"))
    except Exception:
        pass
    k = 0
    for f in api.met:
        if f in api.pacts or f in out: continue
        api.cmd("offer %s pact 720" % f)
        k += 1
        if k >= 4: break

def _recruit(api, units, m):
    t = api.t
    inc = _f(api.income_by.get("res", api.income)) if isinstance(api.income_by, dict) else _f(api.income)
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    armour_seen = False
    for e in api.enemy.values():
        ty = e.get("types") or {}
        try:
            if any(k in ty for k in ("arm", "hvt", "mec")): armour_seen = True
        except Exception:
            pass
    made = 0
    reserve = 25
    cap = 4 + int(api.res // 400)
    if cap > 14: cap = 14
    while made < cap:
        if api.res < reserve + 10: break
        if api.res < 600:
            if inc < 1.0 and t > 100 and made > 0: break
            if inc < 0.3 and t > 100: break
        if cnt.get("rec", 0) < 3 and t < 800:
            ty = "rec"
        elif api.neutral_border and t < 1800 and (cnt.get("cav", 0) < 6 + t // 150):
            ty = "cav"
        else:
            k = m.get("rk", 0)
            m["rk"] = k + 1
            r6 = k % 6
            if armour_seen and r6 == 1:
                ty = "atg"
            elif r6 in (2, 5):
                ty = "art"
            else:
                ty = "inf"
        uc = api.unit_costs.get(ty) or {}
        if api.res - uc.get("res", 9) < reserve: break
        if api.mp < uc.get("mp", 9) + 5: break
        ok = True
        for k in ("steel", "oil", "rare"):
            if uc.get(k, 0) > api.stock.get(k, 0): ok = False
        if not ok:
            ty = "inf"
            uc = api.unit_costs.get(ty) or {}
            if api.res - uc.get("res", 9) < reserve or api.mp < uc.get("mp", 9) + 5: break
        r = api.cmd("recruit %s" % ty)
        if not r.startswith("ok"): break
        cnt[ty] = cnt.get(ty, 0) + 1
        made += 1
        inc -= uc.get("res", 9) * 0.01

def _refit(api, units, m):
    if api.t - m.get("rf_t", -999) < 24: return
    m["rf_t"] = api.t
    if not getattr(api, "old_units", 0): return
    if api.res < 500: return
    border = set(api.border.keys()) if isinstance(api.border, dict) else set(api.border)
    near = set(border)
    for p in border:
        pr = api.provs.get(p)
        if pr: near.update(pr.get("nbrs", []))
    busy = set()
    for a in m.get("atks", []):
        busy.update(a["ids"])
    ids = []
    budget = api.res - 400
    for u in units:
        if not u.get("old") or u["id"] in busy: continue
        if u.get("fighting") or not u.get("supplied"): continue
        if u["prov"] in near: continue
        if _f(u.get("rdy", 0)) < 60: continue
        pr = api.provs.get(u["prov"])
        if not pr or pr.get("owner") != "me": continue
        rc = (api.refit_cost or {}).get(u["type"]) or {}
        c = _f(rc.get("res", 5))
        if c > budget: break
        okk = True
        for k in ("steel", "oil", "rare"):
            if _f(rc.get(k, 0)) * (len(ids) + 1) > api.stock.get(k, 0): okk = False
        if not okk: continue
        budget -= c
        ids.append(u["id"])
        if len(ids) >= 40: break
    if ids:
        api.cmd("refit " + ",".join(map(str, ids)))

def _attacks(api, units, m):
    t = api.t
    atks = m.setdefault("atks", [])
    byid = dict((u["id"], u) for u in units)
    provs = api.provs
    keep = []
    for a in atks:
        ids = [i for i in a["ids"] if i in byid]
        tgt = a["tgt"]
        pr = provs.get(tgt, {})
        if not ids:
            continue
        sel = ",".join(str(i) for i in ids)
        if pr.get("owner") == "me" and tgt not in api.enemy:
            api.cmd("front " + sel)
            continue
        if a["st"] == "prep":
            bon = 0.0
            rd = 0.0
            for i in ids:
                bon = max(bon, _f(byid[i].get("bonus", 0)))
                rd += _f(byid[i].get("rdy", 0))
            rd /= len(ids)
            if t - a["t0"] >= 144:
                api.cmd("front " + sel)
                continue
            if (t - a["t0"] >= 72 or (t - a["t0"] >= 30 and bon >= 40)) and rd >= 72:
                api.cmd("move %s P%d" % (sel, tgt))
                a["st"] = "go"; a["t1"] = t
        else:
            alive = [i for i in ids if _f(byid[i]["str"]) >= 30 and _f(byid[i].get("rdy", 0)) >= 25]
            ard = sum(_f(byid[i].get("rdy", 0)) for i in ids) / float(len(ids))
            if t - a["t1"] > 96 or not alive or (len(ids) > 1 and ard < 30):
                api.cmd("front " + sel)
                continue
        a["ids"] = ids
        keep.append(a)
    atks[:] = keep
    big = [a for a in atks if len(a["ids"]) > 1]
    if t < 150 or len(big) >= 3: return
    busy = set()
    for a in atks:
        busy.update(a["ids"]); busy.add(-a["tgt"])
    byprov = {}
    for u in units:
        if u["type"] == "rec" or u["id"] in busy: continue
        if u.get("state") in ("routing", "shaken", "refitting"): continue
        byprov.setdefault(u["prov"], []).append(u)
    cands = set()
    for p in api.border:
        pr = provs.get(p)
        if not pr: continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if q and q.get("owner") == "enemy":
                own = api.owner_name.get(n)
                if own and own in api.pacts: continue
                cands.add(n)
    best = None
    snatched = 0
    for tgt in cands:
        if -tgt in busy: continue
        q = provs.get(tgt, {})
        e = api.enemy.get(tgt)
        es = _f(e.get("str", 0)) if e else 0.0
        if not e and not q.get("visible"):
            es = 200.0
        pool = []; dirs = 0
        for n in q.get("nbrs", []):
            pn = provs.get(n)
            if not pn or pn.get("owner") != "me": continue
            here = byprov.get(n, [])
            us = [u for u in here if _f(u["str"]) >= 60 and _f(u.get("rdy", 0)) >= 65
                  and u["id"] not in busy]
            us.sort(key=lambda u: -_f(u["str"]))
            us = us[:max(0, len(here) - 1)]
            if us:
                dirs += 1
                pool.extend(us)
        if not pool: continue
        if es <= 0 and e is None and q.get("visible"):
            if snatched >= 4: continue
            u = max(pool, key=lambda u: _f(u["str"]))
            api.cmd("move %d P%d" % (u["id"], tgt))
            atks.append({"tgt": tgt, "ids": [u["id"]], "st": "go", "t0": t, "t1": t})
            busy.add(u["id"]); busy.add(-tgt)
            snatched += 1
            continue
        mys = sum(_f(u["str"]) for u in pool)
        fort = _f(q.get("fort", 0))
        nart = sum(1 for u in pool if u["type"] in ("art", "eng"))
        if fort >= 3: continue
        if fort >= 2 and nart < 3: continue
        terr = str(q.get("terrain", "p"))[:1]
        tdf = TDM.get(terr, 1.0)
        heavy = sum(1 for u in pool if u["type"] in ("art", "eng", "arm")) / float(len(pool))
        rdy = sum(_f(u["rdy"]) for u in pool) / len(pool) / 100.0
        feats = [math.log((mys + 1) / (es + 1)), tdf, fort,
                 1.0 if q.get("city") else 0.0, 0.4, rdy, heavy, float(dirs)]
        p = _model_p(api, feats)
        if mys < 2.5 * es * tdf: p *= 0.5
        if p > 0.65 and (best is None or p > best[0]):
            best = (p, tgt, pool)
    if best:
        p, tgt, pool = best
        ids = [u["id"] for u in pool]
        sel = ",".join(str(i) for i in ids)
        r = api.cmd("prepare %s P%d" % (sel, tgt))
        if r.startswith("ok"):
            atks.append({"tgt": tgt, "ids": ids, "st": "prep", "t0": t, "t1": t})
        else:
            api.cmd("front " + sel)

def _assign(api, units, m):
    busy = set()
    for a in m.get("atks", []):
        busy.update(a["ids"])
    exp_ids = []; front_ids = []; scout_ids = []
    for u in units:
        if u["id"] in busy: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u.get("path") or u.get("plan", -1) not in (-1, None): continue
        if u.get("state") == "refitting": continue
        if u["type"] == "rec":
            if api.unexplored: scout_ids.append(u["id"])
            continue
        if api.neutral_border and u["type"] not in ("art", "atg"):
            exp_ids.append(u["id"])
        else:
            front_ids.append(u["id"])
    if scout_ids: api.cmd("explore " + ",".join(map(str, scout_ids)))
    if exp_ids: api.cmd("expand " + ",".join(map(str, exp_ids)))
    if front_ids: api.cmd("front " + ",".join(map(str, front_ids)))

def tick(api):
    m = api.mem
    units = api.units
    try:
        _diplo(api, m)
    except Exception:
        pass
    try:
        _research(api)
    except Exception:
        pass
    try:
        _attacks(api, units, m)
    except Exception:
        pass
    try:
        _refit(api, units, m)
    except Exception:
        pass
    try:
        _assign(api, units, m)
    except Exception:
        pass
    try:
        _recruit(api, units, m)
    except Exception:
        pass
