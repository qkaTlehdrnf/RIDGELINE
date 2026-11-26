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

RESEARCH = ["farming", "conscription", "logistics", "medicine", "industry", "inf.weapons", "art.weapons",
            "mining", "discipline", "staffwork", "grn.weapons", "drill",
            "inf.protection", "fieldworks", "drilling", "refining", "art.protection",
            "atg.weapons", "grn.protection", "cav.weapons", "arm.weapons", "inf.mobility"]

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

def _diplo(api):
    m = api.mem
    t = api.t
    if t - m.get("dip_t", -999) < 24:
        return
    m["dip_t"] = t
    met = list(api.met or [])
    if not met:
        return
    cnt = {}
    for p, f in (api.owner_name or {}).items():
        cnt[f] = cnt.get(f, 0) + 1
    target = m.get("target")
    if not target or target not in met:
        best = None
        for f in met:
            c = cnt.get(f, 0)
            if c <= 0:
                continue
            if best is None or c < cnt.get(best, 0):
                best = f
        if best is None:
            best = met[0]
        target = best
        m["target"] = target
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            if o.get("frm") != target:
                api.cmd("accept %s" % o.get("id"))
            else:
                api.cmd("reject %s" % o.get("id"))
    pending = set(o.get("to") for o in (api.offers_out or []))
    pacts = api.pacts or {}
    last = m.setdefault("pact_ask", {})
    for f in met:
        if f == target or f in pending:
            continue
        pk = pacts.get(f)
        if pk and not pk.get("broken_by"):
            continue
        if t - last.get(f, -999) < 96:
            continue
        last[f] = t
        api.cmd("offer %s pact" % f)
        api.cmd("say %s Cascadia proposes lasting peace: no attacks either way. We will keep it." % f)

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
        target = {"inf": 0.28, "art": 0.24, "grn": 0.14, "cav": 0.04, "eng": 0.07,
                  "atg": 0.13 if armour_seen else 0.06, "arm": 0.04, "mtn": 0.02}
        if mp < 150:
            target = {"art": 0.4, "atg": 0.25, "arm": 0.2, "inf": 0.15}
    combat = max(1, sum(v for k, v in counts.items() if k != "rec"))
    cnt = dict(counts)
    reserve = 150 if bank < 3000 else bank * 0.05
    nbatch = 1 if bank < 300 else (3 if bank < 1500 else 8)
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
    if st.get("res", api.res) < 2500:
        return
    m["refit_t"] = api.t
    for ty in ("inf", "art", "grn", "atg", "cav", "eng", "arm", "mtn"):
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
    _research(api)
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
        if api.neutral_border and typ not in ("art", "atg"):
            api.cmd("expand %d" % uid)
        else:
            api.cmd("front %d" % uid)
    m["garrison"] = gar

    # manage running attacks
    for tgt in list(m["attacks"].keys()):
        a = m["attacks"][tgt]
        ids = [i for i in a["ids"] if i in byid]
        a["ids"] = ids
        owner = provs.get(tgt, {}).get("owner")
        age = t - a["t0"]
        fighters = [i for i in ids if byid[i]["type"] != "rec"]
        if not fighters or owner == "me" or age > 200 or (a["phase"] == "go" and t - a.get("tg", t) > 72):
            _release(api, ids, byid)
            del m["attacks"][tgt]
            continue
        if a["phase"] == "prep":
            e = enemy.get(tgt)
            astr = sum(byid[i]["str"] for i in fighters)
            if e:
                dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                if (astr + 1.0) / (dstr + 1.0) < 1.8:
                    _release(api, ids, byid)
                    del m["attacks"][tgt]
                    continue
            lost = [i for i in fighters if byid[i].get("plan") != tgt and not byid[i]["path"]]
            if lost:
                api.cmd("prepare %s P%d" % (",".join(str(i) for i in lost), tgt))
            bs = []
            for i in fighters:
                b = byid[i].get("bonus", 0) or 0
                if b <= 1.0:
                    b *= 100.0
                bs.append(b)
            avgb = sum(bs) / float(len(bs))
            rdy = sum(byid[i]["rdy"] for i in fighters) / float(len(fighters))
            if (avgb >= 40 and rdy >= 55) or (avgb >= 60 and rdy >= 45) or (age >= 110 and avgb >= 30 and rdy >= 40):
                api.cmd("move %s P%d" % (",".join(str(i) for i in fighters), tgt))
                a["phase"] = "go"
                a["tg"] = t
            elif age >= 150:
                _release(api, ids, byid)
                del m["attacks"][tgt]
                continue

    maxa = min(10, 2 + len(units) // 150)
    if len(m["attacks"]) >= maxa:
        return

    model = api.model or {}
    w = model.get("w"); mean = model.get("mean"); std = model.get("std"); b0 = model.get("b", 0)
    busy = attackers | gset
    byprov = {}
    for u in units:
        if u["id"] in busy or u["type"] in ("rec", "mil"):
            continue
        if u["str"] < 70 or u["rdy"] < 50 or u["state"] in ("routing", "shaken", "pinned", "refitting"):
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
        if own and own in pacts and not (pacts[own] or {}).get("broken_by"):
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
                cands.extend(lst)
                dirs += 1
                srcs.append(nb)
        if len(cands) < 4:
            continue
        astr = sum(u["str"] for u in cands)
        dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.35)
        ratio = (astr + 1.0) / (dstr + 1.0)
        heavy = sum(1 for u in cands if u["type"] in ("art", "eng", "arm")) / float(len(cands))
        need = 2.5 + 1.0 * fort
        if ratio < need:
            continue
        if fort >= 2 and heavy < 0.25:
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
        if len(cs) < 4:
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
