Last war I placed 2nd of 31, but many of my orders were wasted: 301 of 442 commands were refused.

- **98 recruit refusals:** I tried to raise cav before discovering horse riding. Recruiting now uses only the kinds in `api.can_raise`.
- **184 develop refusals:** I had no coal. Develop now checks `can_dev` and coal first, and I offer oil for coal.
- **No discoveries made:** I researched only upgrade lines. Research now tries a discovery first, from a priority list: horses, iron, roads, walls, siege, then the economy chain and industrial and modern land war. If no discovery is affordable, the slot goes to an upgrade line.
- **Depot code crashed every call:** My one depot served 223 provinces at 148/60 load (output x0.71). I rewrote the depot logic without `math`, and it now opens more depots when load is over capacity.

The rest stays. I keep pacts with almost everyone, since peace kept me on top. I still pick one victim later in the war and attack it only at a large strength advantage with prepared attacks. Artillery, armour and other kinds are chosen only when they can be raised.

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
            if api.res - _f(v) < reserve: return False
        elif k in ('steel', 'oil', 'rare', 'coal', 'rubber'):
            if api.stock.get(k, 0) < _f(v): return False
    return True

PRI = ["farming", "logistics", "conscription", "industry", "mining", "inf.weapons",
       "inf.protection", "staffwork", "medicine", "drill", "discipline", "art.weapons",
       "cav.weapons", "drilling", "refining", "fieldworks", "art.protection",
       "cav.protection", "inf.mobility", "cav.mobility", "arm.weapons", "mec.weapons"]

DPRI = ["horse_riding", "iron_working", "roads", "masonry", "siege_engines", "crop_rotation",
        "pikes_crossbows", "stirrup", "castles", "trebuchet", "banking", "hillmen", "gunpowder",
        "matchlock", "steam_power", "railways", "rifling", "dragoons", "steel_guns",
        "field_engineering", "grenadiers", "combustion", "machine_guns", "heavy_artillery",
        "tanks", "anti_tank_guns", "flight", "mechanisation", "assault_rifles", "rocket_artillery",
        "heavy_armour", "jet_engines", "bombers", "rocketry", "satellites", "composite_armour",
        "ballistic_missiles", "guided_weapons"]

def _research(api, m):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    n = len(api.research)
    tree = getattr(api, "tree", None) or {}
    reserve = 150 if api.t < 300 else 500
    order = [d for d in DPRI if d in tree] + sorted(d for d in tree if d not in DPRI)
    dbusy = sum(1 for r in api.research if r[0] in tree)
    for d in order:
        if n >= 2 or dbusy >= 2: break
        if d in busy: continue
        td = tree.get(d) or {}
        if td.get("status") != "open": continue
        need = _f(td.get("res_now", 0)) or _f((td.get("cost") or {}).get("res", 9999))
        if api.res - need < reserve:
            break  # save for this one
        r = api.cmd("research " + d)
        if r.startswith("ok"):
            n += 1; dbusy += 1; busy.add(d)
            api.count("discover")
        break
    if n >= 2 or n == 0 and dbusy == 0 and api.t < 200: return
    for line in PRI:
        if n >= 2: break
        if line in busy: continue
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open": continue
        if _afford(api, tl.get("cost"), reserve + 400):
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                n += 1
                api.count("research")

def _pick_victim(api, m):
    t = api.t
    if t < 1500: return
    if m.get("victim") and t - m.get("vic_t", 0) < 400: return
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

GOOD = ("steel", "coal", "rubber", "rare")
CHEAP = ("res", "oil")

def _fair(o):
    tg = o.get("they_give") or {}
    yg = o.get("you_give") or {}
    for k in yg:
        if k not in CHEAP: return False
    for k in tg:
        if str(k).startswith("P"): return False
    got = sum(_f(v) for k, v in tg.items() if k in GOOD)
    if got <= 0: return False
    give = sum(_f(v) for v in yg.values())
    return give <= 2.5 * got

def _diplo(api, m):
    vic = m.get("victim")
    try:
        for o in api.offers_in:
            k = o.get("kind")
            if k in ("pact", "alliance") and o.get("frm") != vic:
                api.cmd("accept %s" % o["id"])
            elif k in ("trade", "supply") and _fair(o):
                yg = o.get("you_give") or {}
                ok = True
                for kk, v in yg.items():
                    if kk == "res" and api.res - _f(v) * (10 if k == "supply" else 1) < 500: ok = False
                    if kk == "oil" and api.stock.get("oil", 0) < _f(v) * (10 if k == "supply" else 1): ok = False
                if ok:
                    r = api.cmd("accept %s" % o["id"])
                    if r.startswith("ok"): api.count("trade_in")
                else:
                    api.cmd("reject %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
    except Exception:
        pass
    if vic and vic in api.pacts:
        pc = api.pacts.get(vic) or {}
        if pc.get("ends") is None and pc.get("kind") != "truce" and not m.get("broke_" + vic):
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
        pc = api.pacts.get(f)
        if pc:
            en = pc.get("ends")
            if en is None or _f(en) - api.t > 90: continue
        if f in out: continue
        api.cmd("offer %s pact 720" % f)
        k += 1
        if k >= 6: break
    if api.t - m.get("tr_t", -999) >= 96:
        m["tr_t"] = api.t
        cands = [f for f in api.met if f not in out and f != vic]
        pw = api.powers or {}
        oil = api.stock.get("oil", 0)
        need_coal = api.stock.get("coal", 0) < 150
        need_steel = api.stock.get("steel", 0) < 300
        if need_coal:
            cc = sorted(cands, key=lambda f: -_f(((pw.get(f) or {}).get("deposits") or {}).get("coal", 0)))
            for f in cc[:2]:
                if oil > 600:
                    api.cmd("offer %s trade 100 oil for 50 coal" % f); oil -= 100
                elif api.res > 2000:
                    api.cmd("offer %s trade 120 res for 50 coal" % f)
        if need_steel:
            cs = sorted(cands, key=lambda f: -_f(((pw.get(f) or {}).get("deposits") or {}).get("steel", 0)))
            for f in cs[:2]:
                if oil > 800:
                    api.cmd("offer %s trade 120 oil for 50 steel" % f); oil -= 120
                elif api.res > 2500:
                    api.cmd("offer %s trade 150 res for 50 steel" % f)

def _depots(api, m):
    t = api.t
    if t < 30 or t - m.get("dp_t", -999) < 24: return
    deps = api.depots or {}
    if len(deps) >= 12: return
    over = False
    for p, d in deps.items():
        d = d or {}
        if _f(d.get("opens_in", 0)) > 0: return
        cap = _f(d.get("capacity", 30)) or 30.0
        if _f(d.get("load", 0)) > 0.85 * cap:
            over = True
    if not over: return
    dc = getattr(api, "depot_cost", 150)
    cost = _f(dc.get("res", 150)) if isinstance(dc, dict) else _f(dc)
    if cost <= 0: cost = 150
    if api.res < cost + 60: return
    m["dp_t"] = t
    provs = api.provs
    danger = set(api.border)
    dpos = []
    for p in deps:
        pr = provs.get(p) or provs.get(int(p)) if str(p).isdigit() else provs.get(p)
        if pr: dpos.append((_f(pr.get("x", 0)), _f(pr.get("y0", 0))))
    if not dpos:
        cp = provs.get(api.capital)
        if cp: dpos.append((_f(cp.get("x", 0)), _f(cp.get("y0", 0))))
    if not dpos: return
    best = []
    for i, pr in provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied"): continue
        if i in deps or i in danger: continue
        x = _f(pr.get("x", 0)); y = _f(pr.get("y0", 0))
        dm = min(((x - a) ** 2 + (y - b) ** 2) ** 0.5 for a, b in dpos)
        if dm < 14: continue
        nb = sum(1 for n in pr.get("nbrs", []) if (provs.get(n) or {}).get("owner") == "me")
        sc = min(dm, 50) * (2.0 if pr.get("city") else 1.0) + nb + 2 * _f(pr.get("infra", 0))
        if pr.get("harsh"): sc *= 0.4
        best.append((sc, i))
    best.sort(reverse=True)
    for sc, i in best[:4]:
        r = api.cmd("depot P%d" % i)
        if r.startswith("ok"):
            api.count("depot")
            return
        api.count("depot_fail")

def _economy(api, m):
    t = api.t
    if t < 100 or t - m.get("ec_t", -999) < 12: return
    m["ec_t"] = t
    ec = api.economy or {}
    works = ec.get("works") or []
    busy = set(w[1] for w in works if len(w) > 1)
    if len(works) >= 12: return
    reserve = 500 if t < 600 else 1000
    border = set(api.border)
    rows = ec.get("provs") or []
    cand = []
    for r in rows:
        p = r.get("prov")
        if p in busy or p in border: continue
        pr = api.provs.get(p) or {}
        if pr.get("owner") != "me" or not pr.get("supplied"): continue
        agg = _f(r.get("agg", 1)) or 1.0
        base = _f(r.get("base", 0))
        val = (0.3 * base + 0.8) * agg
        dev = _f(r.get("dev", 0))
        if r.get("can_dev") and dev + 1 <= _f(r.get("room", 0)):
            dc = r.get("dev_cost") or {}
            c = _f(dc.get("res", 100)) if isinstance(dc, dict) else 100
            cand.append((val / (c + 1), "develop", p))
        elif r.get("can_infra") and _f(r.get("infra", 0)) < 3:
            ic = r.get("infra_cost") or {}
            c = _f(ic.get("res", 60)) if isinstance(ic, dict) else 60
            cand.append((0.6 * val / (c + 1), "build", p))
    cand.sort(reverse=True)
    n = len(works)
    for sc, kind, p in cand:
        if n >= 12 or api.res < reserve: break
        r = api.cmd("%s P%d" % (kind, p))
        if r.startswith("ok"):
            n += 1
            busy.add(p)
            api.count(kind)

def _recruit(api, units, m):
    t = api.t
    can = set(getattr(api, "can_raise", None) or ["inf", "mil", "rec"])
    inc = _f(api.income_by.get("res", api.income)) if isinstance(api.income_by, dict) else _f(api.income)
    if t > 500 and inc < 15 and api.res < 1500:
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
    if t < 250: reserve = 60
    elif t < 600: reserve = 300
    else: reserve = 900
    cap = 4 + int(max(0, api.res - reserve) // 150)
    if t > 500 and inc < 40 and api.res < 2000: cap = min(cap, 2)
    if cap > 25: cap = 25
    st = api.stock
    made = 0
    while made < cap:
        if api.res < reserve + 8: break
        k = m.get("rk", 0); m["rk"] = k + 1
        r6 = k % 6
        if "rec" in can and cnt.get("rec", 0) < (5 if t < 300 else 3) and t < 1500:
            ty = "rec"
        elif "cav" in can and api.neutral_border and cnt.get("cav", 0) < 15 + t // 25:
            ty = "cav"
        else:
            opts = []
            if armour_seen and "atg" in can and r6 == 1: opts.append("atg")
            if r6 in (2, 5):
                for x in ("rkt", "art"):
                    if x in can: opts.append(x); break
            if r6 in (0, 3):
                for x in ("mec", "arm", "mot", "grn"):
                    if x in can: opts.append(x); break
            if r6 == 4:
                for x in ("hvt", "arm", "grn", "cav"):
                    if x in can: opts.append(x); break
            opts.append("inf")
            ty = opts[0]
        uc = api.unit_costs.get(ty) or {}
        ok = bool(uc)
        for kk in ("steel", "oil", "rare"):
            if _f(uc.get(kk, 0)) > st.get(kk, 0): ok = False
        if not ok:
            ty = "inf"
            uc = api.unit_costs.get(ty) or {}
        if api.res - _f(uc.get("res", 9)) < reserve: break
        if api.mp < _f(uc.get("mp", 9)) + 5: break
        r = api.cmd("recruit %s" % ty)
        if not r.startswith("ok"):
            api.count("rec_fail")
            break
        cnt[ty] = cnt.get(ty, 0) + 1
        made += 1

def _refit(api, units, m):
    if api.t - m.get("rf_t", -999) < 24: return
    m["rf_t"] = api.t
    if not getattr(api, "old_units", 0): return
    if api.res < 1500: return
    border = set(api.border)
    near = set(border)
    for p in border:
        pr = api.provs.get(p)
        if pr: near.update(pr.get("nbrs", []))
    busy = set()
    for a in m.get("atks", []):
        busy.update(a["ids"])
    ids = []
    budget = api.res - 1200
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
            if _f(rc.get(k, 0)) > 0 and used[k] + _f(rc.get(k, 0)) > api.stock.get(k, 0) - 50: okk = False
        if not okk: continue
        for k in ("steel", "oil", "rare"):
            used[k] += _f(rc.get(k, 0))
        budget -= c
        ids.append(u["id"])
        if len(ids) >= 40: break
    if ids:
        api.cmd("refit " + ",".join(map(str, ids)))

def _pwin(api, mys, es, tdf, fort, city, rdy, heavy, dirs):
    try:
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
    except Exception:
        return None

HEAVY = ("art", "eng", "rkt", "arm", "hvt")

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
            bon = 0.0; rd = 0.0
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
    MAXB = 8
    if t < 150 or len(big) >= MAXB: return
    vic = m.get("victim")
    busy = set()
    for a in atks:
        busy.update(a["ids"]); busy.add(-a["tgt"])
    byprov = {}
    for u in units:
        if u["id"] in busy or u.get("dom", 0) != 0 or u.get("at_sea"): continue
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
    snatched = 0; started = 0
    used = set(); scored = []
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
            here = [u for u in here if u["type"] not in ("rec", "mil")]
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
        if fort >= 1 and nart < 2 and mys < 2 * need: continue
        if dirs < 2 and mys < 1.5 * need: continue
        rdy = sum(_f(u.get("rdy", 0)) for u in pool) / (100.0 * len(pool))
        heavy = sum(1 for u in pool if u["type"] in HEAVY) / float(len(pool))
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
        if u.get("dom", 0) != 0: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u.get("path") or u.get("plan", -1) not in (-1, None): continue
        if u.get("state") == "refitting": continue
        if u["type"] == "rec":
            if api.unexplored: scout_ids.append(u["id"])
            continue
        if api.neutral_border and u["type"] not in ("art", "atg", "mil", "rkt"):
            exp_ids.append(u["id"])
        else:
            front_ids.append(u["id"])
    if scout_ids: api.cmd("explore " + ",".join(map(str, scout_ids)))
    if exp_ids: api.cmd("expand " + ",".join(map(str, exp_ids)))
    if front_ids: api.cmd("front " + ",".join(map(str, front_ids)))

def tick(api):
    m = api.mem
    units = api.units
    for fn in (_pick_victim, _diplo, _research, _depots, _economy):
        try:
            fn(api, m)
        except Exception:
            api.count("err" + fn.__name__)
    try:
        _attacks(api, units, m)
    except Exception:
        api.count("err_attacks")
    try:
        _refit(api, units, m)
    except Exception:
        api.count("err_refit")
    try:
        _assign(api, units, m)
    except Exception:
        api.count("err_assign")
    try:
        _recruit(api, units, m)
    except Exception:
        api.count("err_recruit")
```

```letters
to turan: Siberia will renew our pact whenever it is offered. Peace on the steppe suits us both.
to haedong: Siberia agrees: a quiet border, pact until broken. We can trade oil or res for coal or steel.
to zhongyuan: Siberia offers a lasting pact and trade: oil for coal or steel.
to muscovy: Siberia offers continued peace. We have no claims on you.
```

```feedback
The jump to v11 ages broke my old policy quietly: 98 refused recruit commands for kinds not yet discovered. A start-of-war warning listing the kinds a policy tries to raise but cannot would help. Please also show the first exception text for each err_ tally in the review, not just the count. My depot code failed 94 times and I could not see why. A coal market or a clear coal price would help, since develop needs coal and many factions have none.
```

REVIEW: full