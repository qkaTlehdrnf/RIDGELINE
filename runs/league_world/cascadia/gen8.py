def _tdfn(t):
    c = str(t or "p")[0]
    if c == "m": return 2.0
    if c == "h": return 1.5
    if c == "f": return 1.25
    return 1.0

def _sig(x):
    if x < -30: return 0.0
    if x > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-x))

RESEARCH = ["farming", "logistics", "medicine", "conscription", "industry", "inf.weapons", "art.weapons",
            "mining", "discipline", "staffwork", "drill", "grn.weapons",
            "inf.protection", "fieldworks", "refining", "art.protection", "atg.weapons",
            "inf.mobility", "art.mobility", "drilling", "grn.protection", "arm.weapons",
            "cav.weapons", "atg.protection", "arm.protection", "grn.mobility", "cav.protection",
            "arm.mobility", "mtn.weapons", "eng.protection"]

def _research(api):
    if len(api.research) >= 2:
        return
    busy = set(r[0] for r in api.research)
    n = len(api.research)
    st = api.stock or {}
    for line in RESEARCH:
        if n >= 2:
            break
        info = api.tech.get(line)
        if not info or line in busy or info.get("status") != "open":
            continue
        cost = info.get("cost") or {}
        ok = True
        for k, v in cost.items():
            if st.get(k, 0) < v + (60 if k == "res" else 0):
                ok = False
                break
        if not ok:
            continue
        if str(api.cmd("research " + line)).startswith("ok"):
            busy.add(line)
            n += 1

def _cost(c, key):
    if isinstance(c, dict):
        return c.get(key, 0) or 0
    if key == "res":
        try:
            return float(c or 0)
        except Exception:
            return 0
    return 0

def _econ(api):
    m = api.mem
    t = api.t
    if t - m.get("econ_t", -999) < 12:
        return
    m["econ_t"] = t
    eco = api.economy or {}
    st = dict(api.stock or {})
    if "res" not in st:
        st["res"] = api.res
    works = eco.get("works") or []
    busyp = set()
    ndev = 0
    ninf = 0
    for w in works:
        try:
            busyp.add(w[1])
            if w[0] == "dev":
                ndev += 1
            else:
                ninf += 1
        except Exception:
            pass
    border = api.border or {}
    provs = api.provs
    plist = eco.get("provs") or []
    # candidates: own supplied non-border provinces
    cand = []
    for e in plist:
        pid = e.get("prov")
        if pid is None or pid in busyp or pid in border:
            continue
        p = provs.get(pid) or {}
        if p and not p.get("supplied", True):
            continue
        cand.append(e)
    res = st.get("res", 0)
    coal = st.get("coal", 0)
    reserve = 1200
    maxdev = min(24, 3 + int(max(0, res - reserve) / 2500))
    if res > reserve + 300 and ndev < maxdev:
        scored = []
        for e in cand:
            if (e.get("room", 0) or 0) <= 0:
                continue
            c = e.get("dev_cost")
            cr = _cost(c, "res"); cc = _cost(c, "coal")
            if cr <= 0:
                continue
            agg = e.get("agg", 1.0) or 1.0
            base = e.get("base", 1.0) or 1.0
            gain = (base * 0.3 + 0.8) * agg
            if e.get("city"):
                gain *= 1.3
            if e.get("prov") == api.capital:
                gain *= 1.3
            scored.append((gain / (cr + 3 * cc), e["prov"], cr, cc))
        scored.sort(key=lambda s: -s[0])
        for sc, pid, cr, cc in scored:
            if ndev >= maxdev:
                break
            if res - cr < reserve or coal - cc < 30:
                continue
            r = api.cmd("develop P%d" % pid)
            if str(r).startswith("ok"):
                res -= cr; coal -= cc; ndev += 1
                api.count("develop")
            else:
                api.count("develop_fail")
                break
    steel = st.get("steel", 0)
    if res > reserve + 300 and steel > 40 and ninf < 4:
        scored = []
        for e in cand:
            if (e.get("dev", 0) or 0) < 2:
                continue
            if (e.get("infra", 0) or 0) >= 3:
                continue
            c = e.get("infra_cost")
            cr = _cost(c, "res"); cs = _cost(c, "steel")
            if cr <= 0:
                continue
            scored.append(((e.get("dev", 0) or 0) * (e.get("agg", 1) or 1), e["prov"], cr, cs))
        scored.sort(key=lambda s: -s[0])
        for sc, pid, cr, cs in scored:
            if ninf >= 4:
                break
            if res - cr < reserve or steel - cs < 25:
                continue
            r = api.cmd("build P%d" % pid)
            if str(r).startswith("ok"):
                res -= cr; steel -= cs; ninf += 1
                api.count("build")
            else:
                break
    # buy coal with spare res from pact partners
    if coal < 150 and res > 5000 and t - m.get("coal_t", -999) >= 96:
        m["coal_t"] = t
        pacts = api.pacts or {}
        pending = set(o.get("to") for o in (api.offers_out or []))
        partners = [f for f in (api.met or []) if _active_pact(pacts, f) and f not in pending]
        for f in partners[:2]:
            api.cmd("offer %s trade 400 res for 60 coal" % f)

def _depots(api):
    m = api.mem
    t = api.t
    if t - m.get("dep_t", -999) < 48:
        return
    m["dep_t"] = t
    deps = api.depots or {}
    if not deps or len(deps) >= 8:
        return
    over = False
    for d, info in deps.items():
        if (info.get("opens_in") or 0) > 0:
            return
        cap = info.get("capacity") or 30
        if (info.get("load") or 0) > cap * 1.15:
            over = True
    if not over:
        return
    st = api.stock or {}
    if st.get("res", api.res) < 900:
        return
    provs = api.provs
    dpos = []
    for d in deps:
        p = provs.get(d)
        if p:
            dpos.append((p.get("x", 0) or 0, p.get("y0", 0) or 0))
    if not dpos:
        return
    border = api.border or {}
    best, bs = None, -1
    for pid, p in provs.items():
        if p.get("owner") != "me" or not p.get("supplied") or pid in deps or pid in border:
            continue
        if p.get("harsh"):
            continue
        bad = False
        for nb in p.get("nbrs", []):
            q = provs.get(nb)
            if q is None or q.get("owner") == "enemy":
                bad = True
                break
        if bad:
            continue
        x = p.get("x", 0) or 0; y = p.get("y0", 0) or 0
        dmin = min((x - a) ** 2 + (y - b) ** 2 for a, b in dpos)
        dmin = math.sqrt(dmin)
        if dmin < 25:
            continue
        sc = dmin * (2.0 if p.get("city") else 1.0)
        if sc > bs:
            best, bs = pid, sc
    if best is not None:
        r = api.cmd("depot P%d" % best)
        api.count("depot_open" if str(r).startswith("ok") else "depot_fail")

def _active_pact(pacts, f):
    pk = pacts.get(f)
    return bool(pk) and not pk.get("broken_by")

def _diplo(api):
    m = api.mem
    t = api.t
    if t - m.get("dip_t", -999) < 24:
        return
    m["dip_t"] = t
    met = list(api.met or [])
    pacts = api.pacts or {}
    cnt = {}
    for p, f in (api.owner_name or {}).items():
        cnt[f] = cnt.get(f, 0) + 1
    target = m.get("target")
    if target and (target not in met or _active_pact(pacts, target)):
        target = None
    if not target and t >= 400:
        best = None
        for f in met:
            c = cnt.get(f, 0)
            if c <= 0 or _active_pact(pacts, f):
                continue
            if best is None or c < cnt.get(best, 0):
                best = f
        target = best
    m["target"] = target
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            if o.get("frm") != target:
                api.cmd("accept %s" % o.get("id"))
            else:
                api.cmd("reject %s" % o.get("id"))
        elif o.get("kind") == "trade":
            tg = o.get("they_give") or {}
            yg = o.get("you_give") or {}
            st = api.stock or {}
            val = {"res": 1.0, "oil": 0.5, "rare": 2.0, "steel": 3.0, "mp": 3.0, "coal": 3.0}
            gin = sum(val.get(k, 1) * v for k, v in tg.items())
            gout = sum(val.get(k, 1) * v for k, v in yg.items())
            can = all(st.get(k, api.mp if k == "mp" else 0) >= v for k, v in yg.items())
            if can and gin >= gout and "mp" not in yg and "steel" not in yg and "coal" not in yg:
                api.cmd("accept %s" % o.get("id"))
    pending = set(o.get("to") for o in (api.offers_out or []))
    last = m.setdefault("pact_ask", {})
    for f in met:
        if f == target or f in pending:
            continue
        if _active_pact(pacts, f):
            continue
        if t - last.get(f, -999) < 96:
            continue
        last[f] = t
        api.cmd("offer %s pact" % f)
        api.cmd("say %s Cascadia accepts lasting peace: no attacks either way. Pact offered; we will keep it." % f)
    if t - m.get("trade_t", -999) >= 96:
        m["trade_t"] = t
        st = api.stock or {}
        partners = [f for f in met if _active_pact(pacts, f) and f not in pending]
        for f in partners[:2]:
            if st.get("oil", 0) > 1500:
                api.cmd("offer %s trade 300 oil for 60 steel" % f)
            elif st.get("rare", 0) > 600:
                api.cmd("offer %s trade 100 rare for 60 steel" % f)
            elif st.get("res", 0) > 6000:
                api.cmd("offer %s trade 600 res for 100 mp" % f)

def _affordable(api, typ, n, st, mp, reserve=40):
    uc = api.unit_costs.get(typ)
    if not uc:
        return False
    if st.get("res", 0) < uc.get("res", 0) * n + reserve:
        return False
    if mp < uc.get("mp", 0) * n + 5:
        return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < uc.get(k, 0) * n:
            return False
    return True

def _spend(api, typ, n, st):
    uc = api.unit_costs.get(typ) or {}
    for k in ("res", "steel", "oil", "rare"):
        st[k] = st.get(k, 0) - uc.get(k, 0) * n
    return uc.get("mp", 0) * n

def _recruit(api, counts, armour_seen, threat):
    m = api.mem
    cap = api.capital
    st = dict(api.stock or {})
    if "res" not in st:
        st["res"] = api.res
    mp = api.mp
    if threat and _affordable(api, "mil", 2, st, mp):
        if str(api.cmd("recruit mil 2 P%d" % cap)).startswith("ok"):
            mp -= _spend(api, "mil", 2, st)
    inc = (api.income_by or {}).get("res", api.income) or 0
    if counts.get("rec", 0) + m.get("rec_q", 0) < 6 and api.t < 3000:
        if _affordable(api, "rec", 1, st, mp):
            if str(api.cmd("recruit rec 1")).startswith("ok"):
                m["rec_q"] = m.get("rec_q", 0) + 1
                mp -= _spend(api, "rec", 1, st)
    bank = st.get("res", 0)
    if inc < 0 and bank < 1500:
        return
    if inc < 1 and bank < 400:
        return
    cities = m.get("cities")
    if not cities or api.t % 48 < 6:
        cities = [cap]
        for pid, p in api.provs.items():
            if p.get("city") and p.get("owner") == "me" and p.get("supplied") and pid != cap:
                if pid not in api.border:
                    cities.append(pid)
        m["cities"] = cities[:12]
        cities = m["cities"]
    if api.t < 500:
        target = {"cav": 0.4, "inf": 0.6}
    else:
        target = {"inf": 0.26, "art": 0.26, "grn": 0.14, "cav": 0.04, "eng": 0.07,
                  "atg": 0.13 if armour_seen else 0.06, "arm": 0.04, "mtn": 0.02}
        if mp < 150:
            target = {"art": 0.4, "atg": 0.25, "arm": 0.2, "rkt": 0.1, "inf": 0.05}
    combat = max(1, sum(v for k, v in counts.items() if k != "rec"))
    cnt = dict(counts)
    reserve = 150 if bank < 3000 else bank * 0.05
    nbatch = 1 if bank < 300 else (3 if bank < 1500 else (8 if bank < 5000 else 16))
    ci = m.get("ci", 0)
    for _ in range(nbatch):
        best, gap = None, -9
        for k, w in target.items():
            g = w - cnt.get(k, 0) / float(combat)
            if g > gap and _affordable(api, k, 2, st, mp, reserve):
                best, gap = k, g
        if best is None:
            break
        city = cities[ci % len(cities)]
        ci += 1
        r = api.cmd("recruit %s 2 P%d" % (best, city))
        if not str(r).startswith("ok"):
            r = api.cmd("recruit %s 2" % best)
            if not str(r).startswith("ok"):
                break
        mp -= _spend(api, best, 2, st)
        cnt[best] = cnt.get(best, 0) + 2
        combat += 2
    m["ci"] = ci

def _refit(api):
    m = api.mem
    if (api.old_units or 0) <= 0:
        return
    if api.t - m.get("refit_t", -999) < 72:
        return
    st = api.stock or {}
    if st.get("res", api.res) < 1500:
        return
    m["refit_t"] = api.t
    for ty in ("art", "inf", "grn", "atg", "arm", "cav", "eng", "mtn"):
        if (api.marks or {}).get(ty, 1) > 1:
            api.cmd("refit old:%s" % ty)

def _release(api, ids, byid):
    for i in ids:
        u = byid.get(i)
        if not u:
            continue
        if u["type"] == "rec":
            api.cmd("explore %d" % i)
        else:
            api.cmd("front %d" % i)

def _bpct(b):
    b = b or 0
    if b <= 1.0:
        b *= 100.0
    return b

def tick(api):
    m = api.mem
    if "init" not in m:
        m["init"] = 1
        m["garrison"] = []
        m["attacks"] = {}
        m["rec_q"] = 0
    t = api.t
    provs = api.provs
    cap = api.capital
    units = api.units
    byid = {}
    counts = {}
    for u in units:
        byid[u["id"]] = u
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    if counts.get("rec", 0) >= m.get("rec_q", 0):
        m["rec_q"] = 0

    enemy = api.enemy or {}
    armour_seen = m.get("armour", False)
    if not armour_seen:
        for e in enemy.values():
            ty = e.get("types") or {}
            try:
                for k in (ty.keys() if hasattr(ty, "keys") else ty):
                    if str(k) in ("arm", "hvt", "mec"):
                        armour_seen = True
                        m["armour"] = True
            except Exception:
                pass

    capp = provs.get(cap, {})
    threat = False
    for nb in capp.get("nbrs", []) + [cap]:
        if nb in enemy:
            threat = True

    try:
        _diplo(api)
    except Exception:
        pass
    try:
        _depots(api)
    except Exception:
        pass
    _research(api)
    try:
        _econ(api)
    except Exception:
        api.count("econ_err")
    _recruit(api, counts, armour_seen, threat)
    try:
        _refit(api)
    except Exception:
        pass

    gar = [g for g in m["garrison"] if g in byid]
    attackers = set()
    for a in m["attacks"].values():
        for i in a["ids"]:
            attackers.add(i)
    gset = set(gar)
    for u in units:
        uid = u["id"]
        if uid in gset or uid in attackers:
            continue
        if u["front"] or u["expand"] or u["explore"] or u["path"]:
            continue
        if u["state"] in ("routing", "shaken", "refitting"):
            continue
        typ = u["type"]
        if typ == "rec":
            if api.unexplored:
                api.cmd("explore %d" % uid)
            continue
        if len(gar) < 4 and typ in ("inf", "mil", "eng", "atg", "grn") and u["prov"] == cap:
            gar.append(uid); gset.add(uid)
            api.cmd("fortify %d" % uid)
            continue
        if typ == "mil":
            if u["prov"] == cap:
                api.cmd("fortify %d" % uid)
            else:
                api.cmd("front %d" % uid)
            continue
        if api.neutral_border and typ not in ("art", "atg", "rkt"):
            api.cmd("expand %d" % uid)
        else:
            api.cmd("front %d" % uid)
    m["garrison"] = gar

    for tgt in list(m["attacks"].keys()):
        a = m["attacks"][tgt]
        ids = [i for i in a["ids"] if i in byid]
        a["ids"] = ids
        owner = provs.get(tgt, {}).get("owner")
        age = t - a["t0"]
        fighters = [i for i in ids if byid[i]["type"] != "rec"]
        if not fighters or owner == "me" or age > 220 or (a["phase"] == "go" and t - a.get("tg", t) > 72):
            if owner == "me":
                api.count("grab_ok" if a.get("grab") else "attack_ok")
            _release(api, ids, byid)
            del m["attacks"][tgt]
            continue
        if a["phase"] == "prep":
            e = enemy.get(tgt)
            astr = sum(byid[i]["str"] for i in fighters)
            if e:
                dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                if (astr + 1.0) / (dstr + 1.0) < 2.0:
                    _release(api, ids, byid)
                    del m["attacks"][tgt]
                    continue
            lost = [i for i in fighters if byid[i].get("plan") != tgt and not byid[i]["path"]]
            if lost:
                api.cmd("prepare %s P%d" % (",".join(str(i) for i in lost), tgt))
            bs = [_bpct(byid[i].get("bonus", 0)) for i in fighters]
            avgb = sum(bs) / float(len(bs))
            rdy = sum(byid[i]["rdy"] for i in fighters) / float(len(fighters))
            if (avgb >= 45 and rdy >= 60) or (avgb >= 65 and rdy >= 50) or (age >= 130 and avgb >= 35 and rdy >= 50):
                api.cmd("move %s P%d" % (",".join(str(i) for i in fighters), tgt))
                a["phase"] = "go"
                a["tg"] = t
                api.count("attack_launch")
            elif age >= 170:
                _release(api, ids, byid)
                del m["attacks"][tgt]
                continue

    maxa = min(24, 4 + len(units) // 120)
    if len(m["attacks"]) >= maxa:
        return

    model = api.model or {}
    w = model.get("w"); mean = model.get("mean"); std = model.get("std"); b0 = model.get("b", 0)
    busy = attackers | gset
    byprov = {}
    for u in units:
        if u["id"] in busy or u["type"] in ("rec", "mil"):
            continue
        if u["str"] < 80 or u["rdy"] < 55 or u["state"] in ("routing", "shaken", "pinned", "refitting"):
            continue
        byprov.setdefault(u["prov"], []).append(u)
    recs = [u for u in units if u["type"] == "rec" and u["id"] not in attackers and u["str"] > 40]
    caps = set((api.enemy_capitals or {}).values())
    target = m.get("target")
    names = api.owner_name or {}
    pacts = api.pacts or {}
    cands_all = []
    for tgt, e in enemy.items():
        if tgt in m["attacks"]:
            continue
        tp = provs.get(tgt)
        if not tp or tp.get("owner") == "me":
            continue
        own = names.get(tgt)
        if own and _active_pact(pacts, own):
            continue
        fort = tp.get("fort", 0) or 0
        if fort >= 3:
            continue
        cands = []
        dirs = 0
        srcs = []
        for nb in tp.get("nbrs", []):
            pn = provs.get(nb)
            if not pn or pn.get("owner") != "me" or nb == cap:
                continue
            lst = byprov.get(nb)
            if lst:
                cands.extend(lst[:40])
                dirs += 1
                srcs.append(nb)
        if len(cands) < 5:
            continue
        astr = sum(u["str"] for u in cands)
        dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.4)
        ratio = (astr + 1.0) / (dstr + 1.0)
        heavy = sum(1 for u in cands if u["type"] in ("art", "eng", "arm", "rkt")) / float(len(cands))
        need = 2.4 + 1.0 * fort
        if ratio < need:
            continue
        if fort >= 2 and heavy < 0.3:
            continue
        rdy = sum(u["rdy"] for u in cands) / float(len(cands)) / 100.0
        x = [math.log(ratio), _tdfn(tp.get("terrain")), fort,
             1 if tp.get("city") else 0, 0.5, max(rdy, 0.7), heavy, dirs]
        if w and mean and std:
            z = b0
            for i in range(min(len(w), len(x))):
                s = std[i] if std[i] else 1
                z += w[i] * (x[i] - mean[i]) / s
            p = _sig(z)
        else:
            p = 0.7 if ratio > 3 else 0.5
        if tgt in caps:
            p += 0.25
        score = p + 0.02 * (tp.get("y", 0) or 0) + (0.05 if tp.get("city") else 0)
        if target and own == target:
            score += 0.3
        if p >= 0.55:
            cands_all.append((score, tgt, cands, srcs))
    cands_all.sort(key=lambda c: -c[0])
    used = set()
    for score, tgt, cands, srcs in cands_all:
        if len(m["attacks"]) >= maxa:
            break
        cs = [u for u in cands if u["id"] not in used]
        if len(cs) < 5:
            continue
        ids = [u["id"] for u in cs]
        r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in ids), tgt))
        if not str(r).startswith("ok"):
            continue
        for i in ids:
            used.add(i)
        if recs and srcs:
            rc = recs.pop(0)
            api.cmd("move %d P%d" % (rc["id"], srcs[0]))
            ids.append(rc["id"])
        m["attacks"][tgt] = {"ids": ids, "t0": t, "phase": "prep"}

    grabs = 0
    for tgt, tp in provs.items():
        if grabs >= 6:
            break
        if tp.get("owner") != "enemy" or not tp.get("visible") or tgt in enemy or tgt in m["attacks"]:
            continue
        own = names.get(tgt)
        if own and _active_pact(pacts, own):
            continue
        if (tp.get("fort", 0) or 0) >= 2:
            continue
        pick = []
        for nb in tp.get("nbrs", []):
            pn = provs.get(nb)
            if not pn or pn.get("owner") != "me" or nb == cap:
                continue
            for u in byprov.get(nb, []):
                if u["id"] in used:
                    continue
                if len(byprov.get(nb, [])) < 4:
                    break
                pick.append(u["id"])
                if len(pick) >= 3:
                    break
            if len(pick) >= 3:
                break
        if len(pick) < 2:
            continue
        r = api.cmd("move %s P%d" % (",".join(str(i) for i in pick), tgt))
        if not str(r).startswith("ok"):
            continue
        for i in pick:
            used.add(i)
        m["attacks"][tgt] = {"ids": pick, "t0": t, "phase": "go", "tg": t, "grab": 1}
        grabs += 1
        api.count("grab_launch")
