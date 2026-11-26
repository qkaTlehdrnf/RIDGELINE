Three wars, third place each time. Land runs out around day 50, and after that our assaults almost never succeed: 5 of 252. Most of those assaults went in with no plan bonus and readiness under 34.

The economy also hit its limits. Manpower stayed near zero and steel ran short, while 13.7k res, 6.6k oil and 2k rare sat unused at the end.

Changes:
1. **Diplomacy.** Laurentia, a large neighbour, offered a pact, so we propose it at once. We accept every pact offer except from our one chosen target. The target is never a faction we hold a pact with, so we fight one weak met neighbour at a time.
2. **Assaults.** We launch fewer and better ones. Each needs a strength ratio of at least 3 + fort level, readiness 60 or more, and a 45% plan bonus. Units below 80 strength stay out.
3. **Spending.**
   - Bigger recruiting batches when the bank is rich.
   - A manpower-light army mix when manpower is short.
   - A longer research list that spends oil and rare (mobility lines, refining).
   - Every few days we offer surplus oil, rare or res to pacted factions in trade for steel or manpower.
4. **Refits.** We re-equip outdated units at a lower bank threshold.

```python
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
            val = {"res": 1.0, "oil": 0.5, "rare": 2.0, "steel": 3.0, "mp": 3.0}
            gin = sum(val.get(k, 1) * v for k, v in tg.items())
            gout = sum(val.get(k, 1) * v for k, v in yg.items())
            can = all(st.get(k, api.mp if k == "mp" else 0) >= v for k, v in yg.items())
            if can and gin >= gout and "mp" not in yg and "steel" not in yg:
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
    # surplus trades with partners
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
            _release(api, ids, byid)
            del m["attacks"][tgt]
            continue
        if a["phase"] == "prep":
            e = enemy.get(tgt)
            astr = sum(byid[i]["str"] for i in fighters)
            if e:
                dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                if (astr + 1.0) / (dstr + 1.0) < 2.2:
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
            elif age >= 170:
                _release(api, ids, byid)
                del m["attacks"][tgt]
                continue

    maxa = min(8, 2 + len(units) // 200)
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
                cands.extend(lst)
                dirs += 1
                srcs.append(nb)
        if len(cands) < 5:
            continue
        astr = sum(u["str"] for u in cands)
        dstr = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.4)
        ratio = (astr + 1.0) / (dstr + 1.0)
        heavy = sum(1 for u in cands if u["type"] in ("art", "eng", "arm", "rkt")) / float(len(cands))
        need = 3.0 + 1.0 * fort
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
        if p >= 0.6:
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
```

```letters
to laurentia: Cascadia agrees. We offer a pact at the start of the next war and will accept yours; we will keep it. Happy to trade surplus oil for steel too.
to anahuac: Cascadia offers lasting peace again, a pact until broken. Accept it and we leave your land alone.
to albion: Cascadia kept our pact and will again. We will offer one early; trades of oil or rare for steel are welcome.
```