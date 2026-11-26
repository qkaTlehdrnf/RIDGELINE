**Strategy.** Siberia is huge, remote and mostly tundra. It has a defence bonus and slow units. Score at the end is territory yield first, so the plan is:

- **Grow fast.** Early on, rec scouts explore. Cheap, fast cavalry (no oil, good against slow-to-arrive rivals) grabs free land with the `expand` order. Expanders fall into the `front` order automatically when free land runs out.
- **Build economy first.** Research farming, conscription, industry, logistics and mining, then medicine, discipline and military lines. Dead ends are skipped. A reserve is kept so research never starves recruiting.
- **Build a defensive army.** Mostly infantry, plus artillery for counter-battery and breaking forts. Anti-tank guns are added once enemy armour is seen. Recruiting stops when income gets thin.
- **Attack only when the odds are good.** Each tick, score adjacent enemy provinces with the supplied logistic model. Use a prepared attack bonus estimate and count attack directions. If p > 0.6, pull fit units from the neighbouring provinces, leaving one per province. They `prepare` for 30–48 hours, then `move`. On capture or timeout they rejoin the front. At most two attacks run at once.
- **Grab undefended land.** Enemy provinces next to mine with no visible defenders get snatched by one unit.
- **Stay fast.** Everything is linear-time and wrapped defensively.

```python
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
        lr = feats[0]
        return _sig(1.2 * lr - 0.8 + 0.3 * (feats[7] - 1))

def _afford(api, cost, reserve):
    if not cost: return False
    st = api.stock
    for k, v in cost.items():
        have = st.get(k, 0) if k != 'res' else api.res
        if k == 'res':
            if have - v < reserve: return False
        elif k in ('steel', 'oil', 'rare'):
            if have < v: return False
    return True

def _research(api):
    if len(api.research) >= 2: return
    pri = ["farming", "conscription", "industry", "logistics", "mining", "medicine",
           "discipline", "inf.protection", "drill", "art.weapons", "inf.weapons",
           "fieldworks", "staffwork", "cav.weapons", "drilling", "refining", "atg.weapons"]
    busy = set(r[0] for r in api.research)
    n = len(api.research)
    for line in pri:
        if n >= 2: break
        if line in busy: continue
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open": continue
        if _afford(api, tl.get("cost"), 40):
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                n += 1

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
    while made < 4:
        if api.res < reserve + 10: break
        if inc < 1.0 and t > 100 and made > 0: break
        if inc < 0.3 and t > 100: break
        if cnt.get("rec", 0) < 3 and t < 800:
            ty = "rec"
        elif api.neutral_border and t < 1800 and (cnt.get("cav", 0) < 6 + t // 150):
            ty = "cav"
        else:
            k = m.get("rk", 0)
            m["rk"] = k + 1
            if armour_seen and k % 4 == 1:
                ty = "atg"
            elif k % 4 == 3:
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
        sel = ",".join(str(i) for i in ids)
        if not ids:
            continue
        if pr.get("owner") == "me" and tgt not in api.enemy:
            api.cmd("front " + sel)
            continue
        if a["st"] == "prep":
            bon = 0.0
            for i in ids:
                bon = max(bon, _f(byid[i].get("bonus", 0)))
            if t - a["t0"] >= 48 or (t - a["t0"] >= 24 and bon >= 35):
                api.cmd("move %s P%d" % (sel, tgt))
                a["st"] = "go"; a["t1"] = t
        else:
            alive = [i for i in ids if _f(byid[i]["str"]) >= 25]
            if t - a["t1"] > 96 or not alive:
                api.cmd("front " + sel)
                continue
        a["ids"] = ids
        keep.append(a)
    atks[:] = keep
    if t < 150 or len(atks) >= 2: return
    busy = set()
    for a in atks:
        busy.update(a["ids"]); busy.add(-a["tgt"])
    # units by province
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
                cands.add(n)
    best = None
    for tgt in cands:
        if -tgt in busy: continue
        q = provs.get(tgt, {})
        e = api.enemy.get(tgt)
        es = _f(e.get("str", 0)) if e else 0.0
        if not e and not q.get("visible"):
            es = 150.0
        pool = []; dirs = 0
        for n in q.get("nbrs", []):
            pn = provs.get(n)
            if not pn or pn.get("owner") != "me": continue
            us = [u for u in byprov.get(n, []) if _f(u["str"]) >= 60]
            if len(byprov.get(n, [])) > 1:
                us.sort(key=lambda u: -_f(u["str"]))
                us = us[:max(0, len(byprov.get(n, [])) - 1)]
            if us:
                dirs += 1
                pool.extend(us)
        if not pool: continue
        mys = sum(_f(u["str"]) for u in pool)
        if es <= 0 and e is None and q.get("visible"):
            # undefended: snatch with one unit
            u = max(pool, key=lambda u: _f(u["str"]))
            api.cmd("move %d P%d" % (u["id"], tgt))
            atks.append({"tgt": tgt, "ids": [u["id"]], "st": "go", "t0": t, "t1": t})
            busy.add(u["id"]); busy.add(-tgt)
            if len(atks) >= 2: return
            continue
        terr = str(q.get("terrain", "p"))[:1]
        tdf = TDM.get(terr, 1.0)
        heavy = sum(1 for u in pool if u["type"] in ("art", "eng", "arm")) / float(len(pool))
        rdy = sum(_f(u["rdy"]) for u in pool) / len(pool) / 100.0
        feats = [math.log((mys + 1) / (es + 1)), tdf, _f(q.get("fort", 0)),
                 1.0 if q.get("city") else 0.0, 0.4, rdy, heavy, float(dirs)]
        p = _model_p(api, feats)
        if mys < 1.8 * es: p *= 0.5
        if p > 0.6 and (best is None or p > best[0]):
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
        if u["type"] == "rec":
            if api.unexplored: scout_ids.append(u["id"])
            continue
        if api.neutral_border:
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
        _research(api)
    except Exception:
        pass
    try:
        _attacks(api, units, m)
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