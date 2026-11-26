Last war we came 4th with 231 provinces. That matters because the final score is territory yield. The war data points to a few fixes.

- **Assaults:** we won 0 of 66. Sixty of them hit fort-3 provinces, mostly from the one-unit "snatch" moves into provinces that only looked empty. Snatches now need a visible, unfortified, empty province.
- **Attack launch:** units started with low readiness and almost no plan bonus. Attacks now need readiness of at least 75 and a +35 bonus (or +25 after 72 h). They need two directions or two artillery/engineer units, and at least 3x the defender's adjusted strength.
- **Victim:** we made pacts with everyone, so after the land grab ran out we never gained anything. From about hour 650 we pick one neighbour: the faction with the most land touching ours and the least visible strength. We stop renewing or accepting pacts with it and break an open-ended pact once. Prepared, artillery-heavy attacks then go only at that victim. Taking its capital would give us all its land.
- **Recruitment:** we ended with 4,000+ unused steel and oil but almost no res. The mix now leans on artillery and mechanised infantry once that stock exists. Recruiting also stops while daily net income is low, so research can keep going.
- **Kept:** expansion, exploring, the front order, research and refits.

```python
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

PRI = ["farming", "conscription", "industry", "logistics", "mining", "art.weapons",
       "inf.protection", "drill", "staffwork", "inf.weapons", "medicine", "discipline",
       "cav.mobility", "refining", "drilling", "fieldworks", "atg.weapons", "art.protection",
       "mec.weapons", "inf.mobility", "art.mobility", "atg.protection", "cav.weapons", "cav.protection",
       "mec.protection", "mtn.weapons", "mtn.protection"]

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
    reserve = 25 if t < 400 else 120
    cap = 5 + int(api.res // 300)
    if cap > 16: cap = 16
    st = api.stock
    while made < cap:
        if api.res < reserve + 8: break
        if api.res < 600:
            if inc < 15 and t > 600 and made > 0: break
            if inc < 3 and t > 100: break
        if cnt.get("rec", 0) < (5 if t < 300 else 3) and t < 1200:
            ty = "rec"
        elif api.neutral_border and t < 1500 and cnt.get("cav", 0) < 12 + t // 20:
            ty = "cav"
        else:
            k = m.get("rk", 0)
            m["rk"] = k + 1
            r6 = k % 6
            rich = st.get("steel", 0) > 200
            oily = st.get("oil", 0) > 200
            if armour_seen and r6 == 1:
                ty = "atg"
            elif r6 in (2, 5) or (rich and r6 == 4):
                ty = "art"
            elif rich and oily and r6 in (0, 3):
                ty = "mec"
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
        inc -= uc.get("res", 9) * 0.01

def _refit(api, units, m):
    if api.t - m.get("rf_t", -999) < 24: return
    m["rf_t"] = api.t
    if not getattr(api, "old_units", 0): return
    if api.res < 300: return
    border = set(api.border.keys()) if isinstance(api.border, dict) else set(api.border)
    near = set(border)
    for p in border:
        pr = api.provs.get(p)
        if pr: near.update(pr.get("nbrs", []))
    busy = set()
    for a in m.get("atks", []):
        busy.update(a["ids"])
    ids = []
    budget = api.res - 250
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
        if len(ids) >= 60: break
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
            if t - a["t0"] >= 150 or _f(pr.get("fort", 0)) >= 2:
                api.cmd("front " + sel)
                continue
            if rd >= 75 and (bon >= 35 or (t - a["t0"] >= 72 and bon >= 25)):
                api.cmd("move %s P%d" % (sel, tgt))
                a["st"] = "go"; a["t1"] = t
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
    if t < 150 or len(big) >= 3: return
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
    best = None
    snatched = 0
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
            us = us[:max(0, len(here) - 1)]
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
        if fort >= 2: continue
        mys = sum(_f(u["str"]) for u in pool)
        nart = sum(1 for u in pool if u["type"] in ("art", "eng", "rkt"))
        terr = str(q.get("terrain", "p"))[:1]
        tdf = TDM.get(terr, 1.0) * (1.25 if q.get("city") else 1.0) * (1.0 + 0.25 * fort)
        need = 3.0 * es * tdf
        if mys < need: continue
        if fort >= 1 and nart < 3: continue
        if dirs < 2 and nart < 2: continue
        score = mys / (need + 1.0) + 0.3 * dirs + (0.5 if recnear else 0) + 0.2 * nart
        own = on.get(tgt)
        if vic and own == vic: score += 2.0
        if q.get("city"): score += 0.5
        if best is None or score > best[0]:
            best = (score, tgt, pool)
    if best:
        sc, tgt, pool = best
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
        _pick_victim(api, m)
    except Exception:
        pass
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
```

```letters
to turan: Siberia values our peace. We will keep offering and accepting pacts with Turan; let our border stay quiet.
to yamato: Siberia keeps faith with Yamato. Our pact stands; we seek nothing of yours.
to muscovy: Quiet borders suit Siberia too. We will renew our pact whenever offered.
```