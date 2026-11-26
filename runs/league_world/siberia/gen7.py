def _f(x):
    try:
        return float(x)
    except Exception:
        return 0.0

TDM = {'p': 1.0, 'f': 1.25, 'h': 1.5, 'm': 2.0}

def _afford(api, cost, reserve):
    if not cost: return False
    for k, v in cost.items():
        if k == 'res':
            if api.res - v < reserve: return False
        elif k in ('steel', 'oil', 'rare'):
            if api.stock.get(k, 0) < v: return False
    return True

PRI = ["farming", "conscription", "logistics", "industry", "mining", "art.weapons",
       "mec.weapons", "inf.protection", "staffwork", "medicine", "drill", "discipline",
       "mec.protection", "drilling", "refining", "inf.weapons", "fieldworks", "art.protection",
       "arm.weapons", "atg.weapons", "cav.mobility", "inf.mobility", "art.mobility", "atg.protection",
       "cav.weapons", "cav.protection", "mtn.weapons", "mtn.protection", "mec.mobility", "arm.protection"]

def _research(api, m):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    n = len(api.research)
    for line in PRI:
        if n >= 2: break
        if line in busy: continue
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open": continue
        if _afford(api, tl.get("cost"), 30):
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                n += 1
                api.count("research")

def _pick_victim(api, m):
    t = api.t
    if t < 650: return
    if m.get("victim") and t - m.get("vic_t", 0) < 300: return
    m["vic_t"] = t
    on = api.owner_name or {}
    adj = {}
    for p in api.border:
        pr = api.provs.get(p)
        if not pr: continue
        for n in pr.get("nbrs", []):
            f = on.get(n)
            if f and f != api.me:
                adj[f] = adj.get(f, 0) + 1
    if not adj: return
    sid = {}
    for p, e in api.enemy.items():
        f = on.get(p)
        if f:
            sid[f] = sid.get(f, 0.0) + _f(e.get("str", 0))
    best = None
    for f, c in adj.items():
        if c < 3: continue
        sc = c / (1.0 + sid.get(f, 0.0) / 300.0)
        if best is None or sc > best[0]:
            best = (sc, f)
    if best:
        m["victim"] = best[1]

def _diplo(api, m):
    vic = m.get("victim")
    try:
        for o in api.offers_in:
            if o.get("kind") == "pact" and o.get("frm") != vic:
                api.cmd("accept %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
    except Exception:
        pass
    if vic and vic in api.pacts:
        pc = api.pacts.get(vic) or {}
        if pc.get("ends") is None and api.t > 900 and not m.get("broke_" + vic):
            m["broke_" + vic] = 1
            api.cmd("break %s" % vic)
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
        if f == vic: continue
        if f in api.pacts or f in out: continue
        api.cmd("offer %s pact 720" % f)
        k += 1
        if k >= 5: break

def _depots(api, m):
    t = api.t
    if t < 36 or t - m.get("dp_t", -999) < 24: return
    deps = api.depots or {}
    if len(deps) >= 8: return
    over = False
    for p, d in deps.items():
        if _f(d.get("opens_in", 0)) > 0: return
        cap = _f(d.get("capacity", 30)) or 30.0
        if _f(d.get("load", 0)) > 0.9 * cap:
            over = True
    if not over: return
    cost = _f(getattr(api, "depot_cost", 150) or 150)
    if api.res < cost + 20: return
    m["dp_t"] = t
    provs = api.provs
    danger = set()
    for p in api.border:
        danger.add(p)
        pr = provs.get(p)
        if pr: danger.update(pr.get("nbrs", []))
    dpos = []
    for p in deps:
        pr = provs.get(p)
        if pr: dpos.append((_f(pr.get("x", 0)), _f(pr.get("y0", 0))))
    if not dpos: return
    best = None
    for i, pr in provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied"): continue
        if i in deps or i in danger: continue
        if pr.get("harsh"): continue
        x = _f(pr.get("x", 0)); y = _f(pr.get("y0", 0))
        dm = min(math.hypot(x - a, y - b) for a, b in dpos)
        if dm < 18: continue
        nb = sum(1 for n in pr.get("nbrs", []) if (provs.get(n) or {}).get("owner") == "me")
        sc = min(dm, 60) * (2.0 if pr.get("city") else 1.0) + nb
        if best is None or sc > best[0]:
            best = (sc, i)
    if best:
        r = api.cmd("depot P%d" % best[1])
        if r.startswith("ok"): api.count("depot")

def _recruit(api, units, m):
    t = api.t
    inc = _f(api.income_by.get("res", api.income)) if isinstance(api.income_by, dict) else _f(api.income)
    if t > 500 and inc < 25: 
        api.count("rec_stop_inc"); return
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
    if t < 250: reserve = 25
    elif t < 600: reserve = 200
    else: reserve = 400
    cap = 4 + int(max(0, api.res - reserve) // 150)
    if t > 500 and inc < 60: cap = min(cap, 2)
    if cap > 14: cap = 14
    st = api.stock
    while made < cap:
        if api.res < reserve + 8: break
        if cnt.get("rec", 0) < (5 if t < 300 else 3) and t < 1200:
            ty = "rec"
        elif api.neutral_border and t < 1200 and cnt.get("cav", 0) < 12 + t // 20:
            ty = "cav"
        else:
            k = m.get("rk", 0)
            m["rk"] = k + 1
            r6 = k % 6
            rich = st.get("steel", 0) > 150
            oily = st.get("oil", 0) > 150
            if armour_seen and r6 == 1:
                ty = "atg"
            elif r6 in (2, 5):
                ty = "art"
            elif rich and oily and r6 in (0, 3):
                ty = "mec"
            elif rich and oily and r6 == 4:
                ty = "arm" if st.get("steel", 0) > 600 else "grn"
            elif rich:
                ty = "grn"
            else:
                ty = "inf"
        uc = api.unit_costs.get(ty) or {}
        if api.res - uc.get("res", 9) < reserve: break
        if api.mp < uc.get("mp", 9) + 5: break
        ok = True
        for k in ("steel", "oil", "rare"):
            if uc.get(k, 0) > st.get(k, 0): ok = False
        if not ok:
            ty = "inf"
            uc = api.unit_costs.get(ty) or {}
            if api.res - uc.get("res", 9) < reserve or api.mp < uc.get("mp", 9) + 5: break
        r = api.cmd("recruit %s" % ty)
        if not r.startswith("ok"): break
        cnt[ty] = cnt.get(ty, 0) + 1
        made += 1

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
    used = {"steel": 0.0, "oil": 0.0, "rare": 0.0}
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
            if used[k] + _f(rc.get(k, 0)) > api.stock.get(k, 0): okk = False
        if not okk: continue
        for k in ("steel", "oil", "rare"):
            used[k] += _f(rc.get(k, 0))
        budget -= c
        ids.append(u["id"])
        if len(ids) >= 40: break
    if ids:
        api.cmd("refit " + ",".join(map(str, ids)))

def _pwin(api, mys, es, tdf, fort, city, rdy, heavy, dirs):
    md = api.model or {}
    w = md.get("w"); mu = md.get("mean"); sd = md.get("std")
    if not w or not mu or not sd: return None
    x = [math.log((mys + 1.0) / (es + 1.0)), tdf, fort, 1.0 if city else 0.0, 0.4, rdy, heavy, dirs]
    z = _f(md.get("b", 0))
    for i in range(min(len(w), len(x))):
        s = sd[i] if sd[i] else 1.0
        z += w[i] * (x[i] - mu[i]) / s
    if z > 30: return 1.0
    if z < -30: return 0.0
    return 1.0 / (1.0 + math.exp(-z))

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
            if a["st"] == "go": api.count("taken")
            continue
        if a["st"] == "prep":
            bon = 0.0
            rd = 0.0
            for i in ids:
                bon = max(bon, _f(byid[i].get("bonus", 0)))
                rd += _f(byid[i].get("rdy", 0))
            rd /= len(ids)
            if t - a["t0"] >= 150 or _f(pr.get("fort", 0)) >= 3:
                api.cmd("front " + sel)
                continue
            if rd >= 70 and (bon >= 32 or (t - a["t0"] >= 60 and bon >= 25)):
                api.cmd("move %s P%d" % (sel, tgt))
                a["st"] = "go"; a["t1"] = t
                api.count("launch")
        else:
            alive = [i for i in ids if _f(byid[i]["str"]) >= 30 and _f(byid[i].get("rdy", 0)) >= 20]
            ard = sum(_f(byid[i].get("rdy", 0)) for i in ids) / float(len(ids))
            if t - a["t1"] > 72 or not alive or (len(ids) > 1 and ard < 25):
                api.cmd("front " + sel)
                continue
        a["ids"] = ids
        keep.append(a)
    atks[:] = keep
    big = [a for a in atks if len(a["ids"]) > 1]
    MAXB = 10
    if t < 150 or len(big) >= MAXB: return
    vic = m.get("victim")
    busy = set()
    for a in atks:
        busy.update(a["ids"]); busy.add(-a["tgt"])
    byprov = {}
    for u in units:
        if u["id"] in busy: continue
        if u.get("state") in ("routing", "shaken", "refitting"): continue
        byprov.setdefault(u["prov"], []).append(u)
    cands = set()
    on = api.owner_name or {}
    for p in api.border:
        pr = provs.get(p)
        if not pr: continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if q and q.get("owner") == "enemy":
                own = on.get(n)
                if own and own in api.pacts: continue
                cands.add(n)
    snatched = 0
    started = 0
    used = set()
    scored = []
    for tgt in cands:
        if -tgt in busy: continue
        q = provs.get(tgt, {})
        if not q.get("visible"): continue
        fort = _f(q.get("fort", 0))
        e = api.enemy.get(tgt)
        es = _f(e.get("str", 0)) if e else 0.0
        pool = []; dirs = 0; recnear = False
        for n in q.get("nbrs", []):
            pn = provs.get(n)
            if not pn or pn.get("owner") != "me": continue
            here = byprov.get(n, [])
            if any(u["type"] == "rec" for u in here): recnear = True
            here = [u for u in here if u["type"] != "rec"]
            us = [u for u in here if _f(u["str"]) >= 60 and _f(u.get("rdy", 0)) >= 65]
            us.sort(key=lambda u: -_f(u["str"]))
            us = us[:max(0, len(here) - 2)]
            if us:
                dirs += 1
                pool.extend(us)
        if not pool: continue
        if es <= 0 and e is None:
            if snatched >= 4 or fort >= 1: continue
            u = max(pool, key=lambda u: _f(u["str"]))
            api.cmd("move %d P%d" % (u["id"], tgt))
            atks.append({"tgt": tgt, "ids": [u["id"]], "st": "go", "t0": t, "t1": t})
            busy.add(u["id"]); busy.add(-tgt)
            snatched += 1
            continue
        if fort >= 3: continue
        mys = sum(_f(u["str"]) for u in pool)
        nart = sum(1 for u in pool if u["type"] in ("art", "eng", "rkt"))
        if fort >= 2 and nart < 6: continue
        terr = str(q.get("terrain", "p"))[:1]
        tdf = TDM.get(terr, 1.0) * (1.25 if q.get("city") else 1.0) * (1.0 + 0.25 * fort)
        need = 2.6 * es * tdf
        if mys < need: continue
        if fort >= 1 and nart < 3: continue
        if dirs < 2 and nart < 2: continue
        rdy = sum(_f(u.get("rdy", 0)) for u in pool) / (100.0 * len(pool))
        heavy = sum(1 for u in pool if u["type"] in ("art", "eng", "arm")) / float(len(pool))
        p = _pwin(api, mys, es, TDM.get(terr, 1.0), fort, q.get("city"), rdy, heavy, dirs)
        if p is not None and p < 0.45: continue
        score = mys / (need + 1.0) + 0.3 * dirs + (0.5 if recnear else 0) + 0.2 * nart
        if p is not None: score += 2.0 * p
        own = on.get(tgt)
        if vic and own == vic: score += 2.0
        if q.get("city"): score += 0.5
        score += 0.05 * _f(q.get("y", 0))
        scored.append((score, tgt, pool))
    scored.sort(key=lambda s: -s[0])
    room = MAXB - len(big)
    for sc, tgt, pool in scored:
        if started >= min(3, room): break
        pool = [u for u in pool if u["id"] not in used]
        if len(pool) < 2: continue
        pool = pool[:40]
        ids = [u["id"] for u in pool]
        sel = ",".join(str(i) for i in ids)
        r = api.cmd("prepare %s P%d" % (sel, tgt))
        if r.startswith("ok"):
            atks.append({"tgt": tgt, "ids": ids, "st": "prep", "t0": t, "t1": t})
            used.update(ids)
            started += 1
            api.count("prepare")
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
    for fn in (_pick_victim, _diplo, _research, _depots):
        try:
            fn(api, m)
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
