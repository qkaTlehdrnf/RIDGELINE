Last war we placed 7th. Three things went wrong:

- **Assaults almost never worked.** Only 6 of 342 succeeded. 330 of them went in at readiness under 34, and almost none carried a prepared-attack bonus. Many also went against level-3 forts.
- **The economy sat idle.** We ended with 36k res and 12k manpower unspent, because recruiting was capped at 3 units per call behind a large reserve.
- **Fronts froze.** Once neutral land ran out we had no way to push forward, so territory stalled.

Changes in this policy:

1. **Spend the surplus.** Recruit up to 14 units per call while res stays above a modest reserve. Keep a manpower buffer for replacing losses. Shift the mix towards inf plus artillery, with anti-tank guns when armour is seen.
2. **Pick assault troops carefully.** Only use units with strength ≥65, readiness ≥55 and morale ≥45, pulled from every adjacent province.
3. **Judge targets on effective defence.** Weigh terrain, forts (reduced by our artillery's share), city and our own readiness. Require about 3x the defence, cross-checked with the fitted model.
4. **Prepare properly.** Launch at a bonus of 40 or more, or after 48 h. Re-check the odds at launch and cancel if the defender has reinforced.
5. **Abort losing assaults early,** so units refit instead of bleeding.
6. **Scale the number of concurrent attacks with army size.** Prefer targets that are high in yield or deposits, or that are a capital.
7. **Research by priority:** economy and supply first, then the infantry and artillery lines and medicine.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

RES_ORDER = ["farming", "logistics", "art.weapons", "inf.protection", "medicine", "staffwork",
             "conscription", "discipline", "industry", "inf.weapons", "mining", "drilling",
             "fieldworks", "art.protection", "drill", "refining", "atg.weapons", "inf.mobility"]

def _afford(api, cost):
    if not cost: return False
    st = api.stock
    for k, v in cost.items():
        if st.get(k, 0) < v: return False
    return True

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    for line in RES_ORDER:
        tl = api.tech.get(line)
        if not tl or line in busy or tl.get("status") != "open": continue
        c = tl.get("cost")
        if c and _afford(api, c) and api.stock.get("res", 0) - c.get("res", 0) > 30:
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                busy.add(line)
                if len(busy) >= 2: return

def _can_build(api, typ, reserve, mpres):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) - c.get("res", 0) < reserve: return False
    if api.mp < c.get("mp", 0) + mpres: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0): return False
    return True

def _recruit(api, m):
    inc = api.income
    if inc <= 0.5 and api.t > 48: return
    t = api.t
    nrec = 0
    for u in api.units:
        if u["type"] == "rec": nrec += 1
    armour_seen = m.get("armour", False)
    if not armour_seen:
        for e in api.enemy.values():
            ty = e.get("types") or {}
            if isinstance(ty, dict) and (ty.get("arm", 0) or ty.get("hvt", 0) or ty.get("mec", 0)):
                armour_seen = True; m["armour"] = True; break
    nu = len(api.units)
    reserve = 25 + 0.08 * nu
    mpres = 40 + 0.15 * nu
    built = 0
    cap = 14
    while built < cap:
        rc = m.get("rc", 0)
        if nrec < 3 and api.unexplored:
            typ = "rec"
        elif api.neutral_border and t < 700:
            typ = "cav" if rc % 3 == 0 else "inf"
        else:
            k = rc % 8
            if armour_seen and k == 7: typ = "atg"
            elif k in (2, 5): typ = "art"
            elif k == 6 and api.stock.get("steel", 0) > 100: typ = "grn"
            else: typ = "inf"
        if not _can_build(api, typ, reserve, mpres):
            if typ != "inf" and _can_build(api, "inf", reserve, mpres): typ = "inf"
            else: break
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): break
        m["rc"] = m.get("rc", 0) + 1
        if typ == "rec": nrec += 1
        built += 1

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
    busy = set()
    for tg, a in list(atks.items()):
        tgi = int(tg)
        pr = provs.get(tgi)
        ids = [i for i in a["ids"] if i in uby]
        done = (pr and pr.get("owner") == "me") or len(ids) < 2
        if a.get("launch") is not None:
            el = t - a["launch"]
            if el > 54: done = True
            elif el >= 18:
                avs = sum(uby[i]["str"] for i in ids) / max(1, len(ids))
                if avs < 45: done = True
        elif t - a["start"] > 72: done = True
        if done:
            if ids: api.cmd("front " + ",".join(str(i) for i in ids))
            del atks[tg]; continue
        busy.update(ids)
        if a.get("launch") is None:
            bon = [uby[i].get("bonus", 0) for i in ids]
            avgb = sum(bon) / max(1, len(bon))
            if t - a["start"] >= 48 or avgb >= 40:
                e = api.enemy.get(tgi)
                ok = True
                if e and pr:
                    pool = [uby[i] for i in ids]
                    art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / float(len(pool))
                    d = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                    _, _, ed = _eff_def(pr, d, art)
                    a_str = sum(u["str"] * (0.4 + 0.6 * u["rdy"] / 100.0) for u in pool)
                    a_str *= 1 + avgb / 100.0
                    if a_str < 1.8 * (ed + 1): ok = False
                if ok:
                    api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgi))
                    a["launch"] = t
                else:
                    api.cmd("front " + ",".join(str(i) for i in ids))
                    del atks[tg]
    maxa = 3 + len(api.units) // 250
    if len(atks) >= maxa: return
    mdl = api.model or {}
    cands = []
    caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
    for p, e in api.enemy.items():
        pr = provs.get(p)
        if not pr or str(p) in atks: continue
        adj = [n for n in pr.get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
        if not adj: continue
        pool = []; dirs = 0
        for n in adj:
            here = byprov.get(n, [])
            us = [u for u in here if u["id"] not in busy and u["type"] not in ("rec", "mil")
                  and u["str"] >= 65 and u.get("rdy", 0) >= 55 and u.get("mor", 70) >= 45
                  and u["state"] not in ("routing", "shaken", "refitting")]
            if not us: continue
            us.sort(key=lambda u: -u["str"])
            keep = 1 if len(here) <= len(us) else 0
            take = us[keep:]
            if take: dirs += 1
            pool += take
        if len(pool) < 3: continue
        d_str = e.get("str", 0) or 0
        if not e.get("exact"): d_str *= 1.3
        art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / float(len(pool))
        tdf, fort, ed = _eff_def(pr, d_str, art)
        rdy = sum(u["rdy"] for u in pool) / (100.0 * len(pool))
        a_eff = sum(u["str"] for u in pool) * (0.4 + 0.6 * rdy) * 1.35
        if a_eff < 3.0 * (ed + 1): continue
        score = 0.6
        if mdl.get("w"):
            heavy = sum(1 for u in pool if u["type"] in ("art", "eng", "arm")) / float(len(pool))
            a_str = sum(u["str"] for u in pool)
            x = [math.log((a_str + 1) / (d_str + 1)), tdf, fort, 1 if pr.get("city") else 0,
                 0.4, rdy, heavy, dirs]
            z = mdl["b"]
            for i in range(len(x)):
                z += mdl["w"][i] * (x[i] - mdl["mean"][i]) / (mdl["std"][i] or 1)
            score = _sig(z)
            if score < 0.45: continue
        val = (pr.get("y", 0) or 0) + 3 * (1 if pr.get("city") else 0) + pr.get("steel", 0) + pr.get("oil", 0) + pr.get("rare", 0)
        if p in caps: val += 50
        cands.append((score + 0.02 * val + 0.1 * dirs, p, pool))
    cands.sort(key=lambda c: -c[0])
    for sc, p, pool in cands:
        if len(atks) >= maxa: break
        ids = [u["id"] for u in pool if u["id"] not in busy]
        if len(ids) < 3: continue
        r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in ids), p))
        if r.startswith("ok"):
            atks[str(p)] = {"ids": ids, "start": api.t, "launch": None}
            busy.update(ids)

def tick(api):
    m = api.mem
    byprov = {}; uby = {}
    for u in api.units:
        byprov.setdefault(u["prov"], []).append(u); uby[u["id"]] = u
    _research(api)
    _recruit(api, m)
    inatk = set()
    for a in m.get("atk", {}).values(): inatk.update(a["ids"])
    exp_ids = []; front_ids = []; explore_ids = []
    for u in api.units:
        if u["id"] in inatk: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u["type"] == "rec":
            if api.unexplored: explore_ids.append(u["id"])
            continue
        if api.neutral_border and u["type"] in ("cav", "inf", "mot", "mtn"):
            exp_ids.append(u["id"])
        else:
            front_ids.append(u["id"])
    if explore_ids: api.cmd("explore " + ",".join(str(i) for i in explore_ids))
    if exp_ids: api.cmd("expand " + ",".join(str(i) for i in exp_ids))
    if front_ids: api.cmd("front " + ",".join(str(i) for i in front_ids))
    if api.t >= 150 and api.enemy:
        _attacks(api, m, byprov, uby)
```