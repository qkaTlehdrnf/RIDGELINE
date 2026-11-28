Last war the army ate the economy. Over the war we earned 1.77M res and 1.72M went on upkeep. That left about 15 res a day net from day 300 on. Research waited for money 9,488 times. 10,400 of 10,564 units were on outdated models. Readiness averaged 35, and we never launched an assault. The army was huge but obsolete and worn out, and the score fell to 8th.

Changes:
- **Recruiting cap.** New units are raised only while unit upkeep stays under a share of gross income: 55% while expanding, 40% later. There is always a floor of about 6 units per border province, so the borders are never stripped. At most 12 units are raised per tick.
- **Economy first.** Discoveries that raise income (roads, crop_rotation, banking, steam_power, railways) now come first. Developing and building infrastructure starts at a much lower bank level and runs up to 4 works at once.
- **Refits.** With the surplus freed up, refits happen more often (up to 80 units a day, at a lower res threshold), so units actually carry the new models.
- **Kept as before.** Pacts, expansion and the cautious prepared-attack logic stay.
- **Calls home.** Two at most, around years 670 and 1330, and only if income is still poor or the army is still mostly outdated.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

DISC = ["roads", "crop_rotation", "iron_working", "horse_riding", "siege_engines", "masonry",
        "banking", "pikes_crossbows", "trebuchet", "steam_power", "railways", "castles", "hillmen", "stirrup",
        "gunpowder", "matchlock", "rifling", "steel_guns",
        "combustion", "machine_guns", "heavy_artillery", "field_engineering", "dragoons",
        "grenadiers", "tanks", "anti_tank_guns", "assault_rifles", "mechanisation",
        "rocket_artillery", "heavy_armour", "flight", "galleys", "jet_engines", "rocketry",
        "satellites", "composite_armour", "guided_weapons", "sailing", "navigation"]

RES_ORDER = ["farming", "industry", "conscription", "staffwork", "medicine", "inf.protection", "art.weapons",
             "logistics", "discipline", "inf.weapons", "drill", "mining", "drilling",
             "refining", "fieldworks", "art.protection", "grn.weapons", "art.mobility", "inf.mobility",
             "cav.mobility", "grn.protection", "cav.weapons", "atg.weapons"]

def _afford(api, cost):
    if not cost: return False
    st = api.stock
    for k, v in cost.items():
        if st.get(k, 0) < v: return False
    return True

def _discover(api, busy):
    tree = api.tree or {}
    res = api.stock.get("res", 0)
    reserve = 100
    names = list(DISC) + sorted(k for k in tree.keys() if k not in DISC)
    want = False
    for d in names:
        tr = tree.get(d)
        if not tr or d in busy or tr.get("status") != "open": continue
        want = True
        rn = tr.get("res_now")
        if rn is None:
            c = tr.get("cost") or {}
            rn = c.get("res", 0)
        if res - rn < reserve:
            api.count("disc_wait_res")
            return want
        r = api.cmd("research " + d)
        if r.startswith("ok"):
            busy.add(d); res -= rn
            api.count("disc_started")
            if len(busy) >= 2: return want
        else:
            api.count("disc_fail")
    return want

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    want = _discover(api, busy)
    if len(busy) >= 2: return
    tl_all = api.tech or {}
    nup = sum(1 for b in busy if b in tl_all)
    if want and nup >= 1: return
    if want and api.stock.get("res", 0) < 700: return
    lines = list(RES_ORDER) + sorted(k for k in tl_all.keys() if k not in RES_ORDER)
    for line in lines:
        tl = tl_all.get(line)
        if not tl or line in busy or tl.get("status") != "open": continue
        c = tl.get("cost")
        if c and _afford(api, c) and api.stock.get("res", 0) - c.get("res", 0) > 200:
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                busy.add(line)
                return

def _can_build(api, typ, reserve, mpres):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) - c.get("res", 0) < reserve: return False
    if api.mp < c.get("mp", 0) + mpres: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0): return False
    return True

def _neutrals(api, m):
    if api.t - m.get("nt_t", -99) < 6 and "nt" in m: return m["nt"]
    out = []
    for i, pr in api.provs.items():
        if pr.get("owner") == "neutral" and not pr.get("harsh"):
            out.append(i)
    m["nt"] = out; m["nt_t"] = api.t
    return out

def _overloaded(api):
    deps = api.depots or {}
    for d in deps.values():
        cap = d.get("capacity", 30) or 30
        if (d.get("load", 0) or 0) > 0.85 * cap: return True
    return False

def _depots(api, m):
    m["dep_save"] = False
    if api.t < 24: return
    deps = api.depots or {}
    if not deps or len(deps) >= 16: return
    for d in deps.values():
        if (d.get("opens_in", 0) or 0) > 0: return
    if not _overloaded(api): return
    cost = api.depot_cost or 150
    if api.stock.get("res", 0) < cost + 30:
        m["dep_save"] = True
        api.count("depot_wait_res")
        return
    if api.t % 24 != 6: return
    border = api.border or {}
    pts = []
    for p in deps:
        pr = api.provs.get(p)
        if pr: pts.append((pr.get("x", 0) or 0, pr.get("y0", 0) or 0))
    best = None
    for i, pr in api.provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied") or pr.get("harsh"): continue
        if i in deps or i in border: continue
        risky = False
        for n in pr.get("nbrs", []):
            if n in border or api.provs.get(n, {}).get("owner") == "enemy": risky = True; break
        if risky: continue
        x = pr.get("x", 0) or 0; y = pr.get("y0", 0) or 0
        dmin = min(math.sqrt((x - a) ** 2 + (y - b) ** 2) for a, b in pts) if pts else 100
        sc = dmin * (1.6 if pr.get("city") else 1.0)
        if best is None or sc > best[0]: best = (sc, i)
    if best and best[0] > 10:
        r = api.cmd("depot P%d" % best[1])
        if r.startswith("ok"): api.count("depot_opened")
        else: api.count("depot_rejected")
    else:
        api.count("depot_no_site")

def _cost_ok(api, c, reserve):
    if c is None: return False
    if isinstance(c, dict):
        for k, v in c.items():
            have = api.stock.get(k, 0)
            if k == "res":
                if have - v < reserve: return False
            elif have < v + 10: return False
        return True
    try:
        return api.stock.get("res", 0) - float(c) >= reserve
    except Exception:
        return False

def _economy(api, m):
    if api.t < 72 or api.t % 12 != 6: return
    if api.stock.get("res", 0) < 450: return
    eco = api.economy or {}
    works = eco.get("works") or []
    if len(works) >= 4: return
    busyp = set(w[1] for w in works)
    border = api.border or {}
    n = len(works)
    for p in (eco.get("provs") or [])[:60]:
        if n >= 4: break
        pid = p.get("prov")
        if pid in busyp or pid in border: continue
        pr = api.provs.get(pid) or {}
        if not pr.get("supplied", True): continue
        if (p.get("dev", 0) or 0) + 1 <= (p.get("room", 0) or 0) and (p.get("dev", 0) or 0) < 6:
            if _cost_ok(api, p.get("dev_cost"), 350):
                r = api.cmd("develop P%d" % pid)
                if r.startswith("ok"):
                    api.count("develop"); n += 1; busyp.add(pid); continue
        if (p.get("infra", 0) or 0) < 3:
            if _cost_ok(api, p.get("infra_cost"), 350):
                r = api.cmd("build P%d" % pid)
                if r.startswith("ok"):
                    api.count("build"); n += 1; busyp.add(pid)

def _recruit(api, m, neut):
    t = api.t
    if m.get("dep_save"): return
    b = api.budget or {}
    gross = b.get("income", 0) or 0
    uu = b.get("upkeep_units", 0) or 0
    net = b.get("net", api.income) or 0
    nu = len(api.units)
    border = api.border or {}
    floor = 20 + 6 * len(border)
    expanding = (api.neutral_border or len(neut) > 0) and t < 20000
    share = 0.55 if expanding else 0.40
    if nu >= floor:
        if t > 48 and net <= 2: api.count("rec_net_block"); return
        if uu > share * gross: api.count("rec_upkeep_block"); return
    nrec = 0
    for u in api.units:
        if u["type"] == "rec": nrec += 1
    armour_seen = m.get("armour", False)
    if not armour_seen:
        for e in api.enemy.values():
            ty = e.get("types") or {}
            if isinstance(ty, dict) and (ty.get("arm", 0) or ty.get("hvt", 0) or ty.get("mec", 0)):
                armour_seen = True; m["armour"] = True; break
    can = set(api.can_raise or [])
    reserve = 30 + (150 if t > 200 else 0)
    mpres = 20 + 0.05 * nu
    built = 0
    cap = 12
    steel = api.stock.get("steel", 0)
    reccap = 12 if t < 300 else 14
    est = uu
    while built < cap:
        if nu + built >= floor and est > share * gross: break
        rc = m.get("rc", 0)
        if nrec < reccap and api.unexplored:
            typ = "rec"
        elif expanding:
            typ = "cav" if rc % 4 != 3 else "inf"
            if "mot" in can and rc % 4 == 1: typ = "mot"
        else:
            k = rc % 10
            if armour_seen and k == 9 and "atg" in can: typ = "atg"
            elif k in (1, 4, 7) and "art" in can: typ = "art"
            elif k == 5 and "rkt" in can: typ = "rkt"
            elif k == 5 and "art" in can: typ = "art"
            elif k == 3 and "arm" in can and api.stock.get("oil", 0) > 100: typ = "arm"
            elif k == 8 and "grn" in can and steel > 80: typ = "grn"
            elif k == 6 and "mtn" in can: typ = "mtn"
            else: typ = "inf"
        if typ not in can: typ = "inf"
        if not _can_build(api, typ, reserve, mpres):
            if typ != "inf" and _can_build(api, "inf", reserve, mpres): typ = "inf"
            else: break
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): break
        m["rc"] = m.get("rc", 0) + 1
        if typ == "rec": nrec += 1
        built += 1
        est += 0.1
        api.count("recruited")

def _refit(api, m, inatk):
    if api.t % 12 != 0: return
    if api.stock.get("res", 0) < 400: return
    ids = []
    for u in api.units:
        if not u.get("old") or u.get("fighting") or u["id"] in inatk: continue
        if u["type"] not in ("art", "grn", "inf", "cav", "mtn", "arm", "mil", "mec", "atg", "rkt"): continue
        if not u.get("supplied", True): continue
        if u["state"] in ("routing", "shaken", "refitting", "moving", "assault", "preparing"): continue
        ids.append(u["id"])
        if len(ids) >= 40: break
    if ids:
        r = api.cmd("refit " + ",".join(str(i) for i in ids))
        if r.startswith("ok"): api.count("refit_ok")
        else: api.count("refit_fail")

def _diplo(api, m):
    t = api.t
    met = list(api.met or [])
    pacts = api.pacts or {}
    for o in api.offers_in or []:
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
        elif o.get("kind") == "trade":
            yg = o.get("you_give") or {}
            tg = o.get("they_give") or {}
            ok = True
            val_give = 0.0
            for k, v in yg.items():
                if k in ("res", "mp"): ok = False
                elif api.stock.get(k, 0) < v + 400: ok = False
                val_give += v
            if any(k[0] == "P" for k in yg.keys() if isinstance(k, str)): ok = False
            val_get = sum(v * (2.5 if k == "res" else 1.0) for k, v in tg.items() if isinstance(v, (int, float)))
            if ok and val_get >= val_give * 0.4: api.cmd("accept %s" % o["id"])
            else: api.cmd("reject %s" % o["id"])
    if t % 24 == 6:
        outp = set(o.get("to") for o in (api.offers_out or []) if o.get("kind") == "pact")
        for f in met:
            pa = pacts.get(f)
            if f in outp: continue
            if pa and pa.get("kind") != "truce":
                en = pa.get("ends")
                if en is None or en - t > 90: continue
            api.cmd("offer %s pact" % f)
    if t % 48 == 30 and met:
        outt = set(o.get("to") for o in (api.offers_out or []) if o.get("kind") == "trade")
        for f in met:
            if f in outt: continue
            for k in ("rubber", "coal", "rare", "oil", "steel"):
                lim = 300 if k == "rare" else 600
                if k in ("rubber", "coal"): lim = 2000
                if api.stock.get(k, 0) > lim + 200:
                    n = 150 if k == "rare" else 250
                    api.cmd("offer %s trade %d %s for %d res" % (f, n, k, 90 if k == "rare" else 100))
                    break
    gr = m.setdefault("greeted", [])
    for f in met:
        if f not in gr:
            gr.append(f)
            api.cmd("say %s Amazonia keeps every pact it signs. Peace and fair trade with all neighbours." % f)

TDF = {"m": 2.0, "h": 1.5, "f": 1.25}

def _eff_def(pr, d_str, art_share):
    ter = pr.get("terrain", "plain") or "plain"
    tdf = TDF.get(ter[0], 1.0)
    fort = pr.get("fort", 0) or 0
    fort_eff = fort * (1 - 0.6 * art_share)
    return tdf, fort, d_str * tdf * (1 + 0.25 * fort_eff) * (1.25 if pr.get("city") else 1.0)

def _attacks(api, m, byprov, uby):
    atks = m.setdefault("atk", {})
    t = api.t
    provs = api.provs
    pacts = api.pacts or {}
    own = api.owner_name or {}
    busy = set()
    for tg, a in list(atks.items()):
        tgi = int(tg)
        pr = provs.get(tgi)
        ids = [i for i in a["ids"] if i in uby]
        done = (pr and pr.get("owner") == "me") or len(ids) < 3 or own.get(tgi) in pacts
        if a.get("launch") is not None:
            el = t - a["launch"]
            if el > 72: done = True
            elif el >= 18:
                avs = sum(uby[i]["str"] for i in ids) / max(1, len(ids))
                if avs < 35: done = True
        elif t - a["start"] > 120: done = True
        if done:
            if ids: api.cmd("front " + ",".join(str(i) for i in ids))
            del atks[tg]; continue
        busy.update(ids)
        if a.get("launch") is None:
            pool = [uby[i] for i in ids]
            n = float(len(pool))
            avgb = sum(u.get("bonus", 0) for u in pool) / n
            avgr = sum(u.get("rdy", 0) for u in pool) / n
            ready = (avgb >= 45 and avgr >= 65) or (t - a["start"] >= 90 and avgr >= 55 and avgb >= 30)
            if not ready: continue
            e = api.enemy.get(tgi)
            ok = True
            if e and pr:
                art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / n
                d = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                _, fort, ed = _eff_def(pr, d, art)
                a_str = sum(u["str"] * (0.4 + 0.6 * u["rdy"] / 100.0) for u in pool)
                a_str *= 1 + avgb / 100.0
                if a_str < 2.2 * (ed + 1): ok = False
            if ok:
                api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgi))
                a["launch"] = t
                api.count("assault_launched")
            else:
                api.count("assault_called_off")
                if ids: api.cmd("front " + ",".join(str(i) for i in ids))
                del atks[tg]
    maxa = 2 + len(api.units) // 300
    if len(atks) >= maxa: return
    mdl = api.model or {}
    cands = []
    caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
    for p, e in api.enemy.items():
        pr = provs.get(p)
        if not pr or str(p) in atks: continue
        ow = own.get(p)
        if ow is None or ow in pacts: continue
        fort = pr.get("fort", 0) or 0
        adj = [n for n in pr.get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
        if not adj: continue
        pool = []; dirs = 0; elev_pen = 0
        for n in adj:
            here = byprov.get(n, [])
            us = [u for u in here if u["id"] not in busy and u["type"] not in ("rec", "mil")
                  and u.get("dom", 0) == 0
                  and u["str"] >= 75 and u.get("rdy", 0) >= 55 and u.get("mor", 70) >= 45
                  and u["state"] not in ("routing", "shaken", "refitting")]
            if not us: continue
            us.sort(key=lambda u: -u["str"])
            keep = 1 if len(here) <= len(us) else 0
            take = us[keep:]
            if take:
                dirs += 1
                elev_pen += max(0, (pr.get("elev", 0) or 0) - (provs.get(n, {}).get("elev", 0) or 0))
            pool += take
        if len(pool) < 6: continue
        d_str = e.get("str", 0) or 0
        if not e.get("exact"): d_str *= 1.3
        art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / float(len(pool))
        if fort >= 3 and art < 0.4: continue
        if fort >= 2 and art < 0.3: continue
        tdf, fort, ed = _eff_def(pr, d_str, art)
        rdy = sum(u["rdy"] for u in pool) / (100.0 * len(pool))
        a_eff = sum(u["str"] for u in pool) * (0.4 + 0.6 * rdy) * 1.45
        if elev_pen and dirs: a_eff *= 0.9 ** (elev_pen / float(dirs))
        if a_eff < 3.0 * (ed + 1): continue
        score = 0.6
        if mdl.get("w"):
            heavy = sum(1 for u in pool if u["type"] in ("art", "eng", "arm")) / float(len(pool))
            a_str = sum(u["str"] for u in pool)
            x = [math.log((a_str + 1) / (d_str + 1)), tdf, fort, 1 if pr.get("city") else 0,
                 0.45, 0.7, heavy, dirs]
            z = mdl["b"]
            for i in range(len(x)):
                z += mdl["w"][i] * (x[i] - mdl["mean"][i]) / (mdl["std"][i] or 1)
            score = _sig(z)
            if score < 0.45: continue
        val = (pr.get("y", 0) or 0) + 3 * (1 if pr.get("city") else 0) + pr.get("steel", 0) + pr.get("oil", 0) + pr.get("rare", 0)
        if p in caps: val += 50
        cands.append((score + 0.02 * val + 0.12 * dirs, p, pool))
    cands.sort(key=lambda c: -c[0])
    for sc, p, pool in cands:
        if len(atks) >= maxa: break
        ids = [u["id"] for u in pool if u["id"] not in busy]
        if len(ids) < 6: continue
        r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in ids), p))
        if r.startswith("ok"):
            atks[str(p)] = {"ids": ids, "start": api.t, "launch": None}
            busy.update(ids)

def _far_targets(api, neut, k):
    cap = api.provs.get(api.capital) or {}
    cx = cap.get("x", 0) or 0; cy = cap.get("y0", 0) or 0
    nb = set(api.neutral_border or [])
    sc = []
    for i in neut:
        pr = api.provs.get(i)
        if not pr: continue
        adj = False
        for n in pr.get("nbrs", []):
            if n in nb: adj = True; break
        v = (pr.get("y", 0) or 0) + 2 * (1 if pr.get("city") else 0) + (pr.get("mp", 0) or 0) * 0.3
        v += 0.5 * (pr.get("steel", 0) + pr.get("oil", 0) + pr.get("rare", 0) + (pr.get("coal", 0) or 0) + (pr.get("rubber", 0) or 0))
        d = math.sqrt(((pr.get("x", 0) or 0) - cx) ** 2 + ((pr.get("y0", 0) or 0) - cy) ** 2)
        sc.append((v - 0.004 * d + (0 if adj else 0.5), i))
    sc.sort(key=lambda s: -s[0])
    return [i for _, i in sc[:k]]

def _maybe_call(api, m):
    if api.t not in (19200, 38400): return
    if m.get("called_%d" % api.t): return
    m["called_%d" % api.t] = True
    b = api.budget or {}
    gross = b.get("income", 0) or 1
    uu = b.get("upkeep_units", 0) or 0
    old = api.old_units or 0
    nu = max(1, len(api.units))
    if uu > 0.6 * gross or old > 0.7 * nu or (b.get("net", 0) or 0) < 20:
        api.call_home("Checkpoint t%d: upkeep_units %.0f of income %.0f, old units %d/%d, net %.0f. Review army size vs economy/research." % (api.t, uu, gross, old, nu, b.get("net", 0) or 0))

def tick(api):
    m = api.mem
    byprov = {}; uby = {}
    for u in api.units:
        byprov.setdefault(u["prov"], []).append(u); uby[u["id"]] = u
    try:
        _diplo(api, m)
    except Exception:
        api.count("diplo_err")
    try:
        _research(api)
    except Exception:
        api.count("res_err")
    try:
        _depots(api, m)
    except Exception:
        m["dep_save"] = False
    try:
        if not m.get("dep_save"): _economy(api, m)
    except Exception:
        api.count("eco_err")
    neut = _neutrals(api, m)
    try:
        _recruit(api, m, neut)
    except Exception:
        api.count("rec_err")
    inatk = set()
    for a in m.get("atk", {}).values(): inatk.update(a["ids"])
    try:
        _refit(api, m, inatk)
    except Exception:
        pass
    try:
        _maybe_call(api, m)
    except Exception:
        pass
    expanding = bool(api.neutral_border or neut)
    exp_ids = []; front_ids = []; explore_ids = []
    for u in api.units:
        if u.get("dom", 0) != 0 or u.get("at_sea"): continue
        if u["id"] in inatk: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u["state"] == "refitting": continue
        if u["type"] == "rec":
            if api.unexplored: explore_ids.append(u["id"])
            continue
        if expanding and u["type"] in ("cav", "inf", "mot", "mtn"):
            exp_ids.append(u["id"])
        else:
            front_ids.append(u["id"])
    if explore_ids: api.cmd("explore " + ",".join(str(i) for i in explore_ids))
    if exp_ids:
        if neut and len(exp_ids) >= 3:
            tg = _far_targets(api, neut, max(1, len(exp_ids) // 4))
            j = 0
            for p in tg:
                grp = exp_ids[j:j + 2]
                if len(grp) < 2: break
                r = api.cmd("expand %s P%d" % (",".join(str(i) for i in grp), p))
                if r.startswith("ok"): j += 2
            exp_ids = exp_ids[j:]
        if exp_ids: api.cmd("expand " + ",".join(str(i) for i in exp_ids))
    if front_ids: api.cmd("front " + ",".join(str(i) for i in front_ids))
    if api.t >= 150 and api.enemy:
        _attacks(api, m, byprov, uby)
```

```letters
to andea: Our pact stands. We have surplus rubber and coal; we will offer them for res. Peace on our border, always.
to platina: Amazonia keeps its pact. Let us both grow rather than bleed each other.
to granada: Our pact holds. Open to rubber/coal for res or steel trades.
```

```feedback
The review should flag when unit upkeep exceeds about 90% of income. I only noticed it from the purse totals. A `disband <sel>` command would let me cut an oversized or obsolete army instead of carrying it for centuries. The refit refusal "must stand on your own supplied land" should say which condition failed (supplied, own land, or in contact).
```

REVIEW: standard