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

RESEARCH = ["farming", "logistics", "medicine", "industry", "inf.weapons", "mining",
            "discipline", "art.weapons", "staffwork", "conscription", "grn.weapons", "drill",
            "inf.protection", "fieldworks", "drilling", "refining", "grn.protection",
            "art.protection", "atg.weapons", "cav.weapons", "inf.mobility"]

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
    if counts.get("rec", 0) + m.get("rec_q", 0) < 4 and api.t < 2000:
        if _affordable(api, "rec", 1, st, mp):
            if str(api.cmd("recruit rec 1")).startswith("ok"):
                m["rec_q"] = m.get("rec_q", 0) + 1
                mp -= _spend(api, "rec", 1, st)
    bank = st.get("res", 0)
    if inc < 0 and bank < 1500:
        return
    if inc < 1 and bank < 400:
        return
    # cities to recruit in
    cities = m.get("cities")
    if not cities or api.t % 48 < 6:
        cities = [cap]
        for pid, p in api.provs.items():
            if p.get("city") and p.get("owner") == "me" and p.get("supplied") and pid != cap:
                if pid not in api.border:
                    cities.append(pid)
        m["cities"] = cities[:12]
        cities = m["cities"]
    if api.t < 600:
        target = {"cav": 0.4, "inf": 0.6}
    else:
        target = {"inf": 0.36, "art": 0.18, "grn": 0.18, "cav": 0.06, "eng": 0.06,
                  "atg": 0.14 if armour_seen else 0.04, "mtn": 0.02}
    combat = max(1, sum(v for k, v in counts.items() if k != "rec"))
    cnt = dict(counts)
    reserve = 150 if bank < 3000 else bank * 0.05
    nbatch = 1 if bank < 300 else (3 if bank < 1500 else 6)
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

    _research(api)
    _recruit(api, counts, armour_seen, threat)

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
        if u["state"] in ("routing", "shaken"):
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
        if not fighters or owner == "me" or age > 160 or (a["phase"] == "go" and t - a.get("tg", t) > 72):
            _release(api, ids, byid)
            del m["attacks"][tgt]
            continue
        if a["phase"] == "prep":
            e = enemy.get(tgt)
            astr = sum(byid[i]["str"] for i in fighters)
            if e:
                dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                if (astr + 1.0) / (dstr + 1.0) < 1.6:
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
            if (avgb >= 40 and rdy >= 45) or avgb >= 55 or age >= 72:
                api.cmd("move %s P%d" % (",".join(str(i) for i in fighters), tgt))
                a["phase"] = "go"
                a["tg"] = t

    maxa = min(8, 2 + len(units) // 150)
    if len(m["attacks"]) >= maxa:
        return

    model = api.model or {}
    w = model.get("w"); mean = model.get("mean"); std = model.get("std"); b0 = model.get("b", 0)
    busy = attackers | gset
    byprov = {}
    for u in units:
        if u["id"] in busy or u["type"] in ("rec", "mil"):
            continue
        if u["str"] < 65 or u["rdy"] < 45 or u["state"] in ("routing", "shaken", "pinned", "refitting"):
            continue
        if u["expand"] and not u["front"]:
            pass
        byprov.setdefault(u["prov"], []).append(u)
    recs = [u for u in units if u["type"] == "rec" and u["id"] not in attackers and u["str"] > 40]
    caps = set((api.enemy_capitals or {}).values())
    cands_all = []
    for tgt, e in enemy.items():
        if tgt in m["attacks"]:
            continue
        tp = provs.get(tgt)
        if not tp or tp.get("owner") == "me":
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
        if len(cands) < 3:
            continue
        astr = sum(u["str"] for u in cands)
        dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.35)
        ratio = (astr + 1.0) / (dstr + 1.0)
        if ratio < 2.2:
            continue
        rdy = sum(u["rdy"] for u in cands) / float(len(cands)) / 100.0
        heavy = sum(1 for u in cands if u["type"] in ("art", "eng", "arm")) / float(len(cands))
        x = [math.log(ratio), _tdfn(tp.get("terrain")), tp.get("fort", 0) or 0,
             1 if tp.get("city") else 0, 0.45, rdy, heavy, dirs]
        if w and mean and std:
            z = b0
            for i in range(min(len(w), len(x))):
                s = std[i] if std[i] else 1
                z += w[i] * (x[i] - mean[i]) / s
            p = _sig(z)
        else:
            p = 0.7 if ratio > 3 else 0.5
        if tgt in caps:
            p += 0.2
        score = p + 0.02 * (tp.get("y", 0) or 0) + (0.05 if tp.get("city") else 0)
        if p >= 0.55:
            cands_all.append((score, tgt, cands, srcs))
    cands_all.sort(key=lambda c: -c[0])
    used = set()
    for score, tgt, cands, srcs in cands_all:
        if len(m["attacks"]) >= maxa:
            break
        cs = [u for u in cands if u["id"] not in used]
        if len(cs) < 3:
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
