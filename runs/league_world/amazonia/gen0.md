Amazonia's edge is cheap manpower, but its attack is weak (-5%). So the plan is to grab land fast, hold a dug-in front, and attack only when the odds are clearly in my favour.

- **Early game:** two scouts explore. Cavalry and infantry use the `expand` standing order while neutral land lasts. Every idle unit joins either expand or the `front` order.
- **Recruiting:** only while net income stays positive and a reserve is kept. The mix is infantry-heavy plus artillery when steel allows. I add anti-tank guns when enemy armour is seen and militia when cash is short.
- **Research:** economy lines first (farming, conscription, mining, logistics), then infantry and artillery weapons and support lines. Lines that hit a dead end are skipped.
- **Attacks:** at most 2 at a time. A target is attacked only if the fitted battle model gives at least 60% success, or my strength is 2.5x the enemy's adjusted for terrain and fort. Healthy units next to the target `prepare`; each border province keeps one defender. Units launch after 30h or a +30% bonus, then return to the front after 60h or once the province is taken.
- **Speed:** commands are batched by id lists to stay within the time limit.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

RES_ORDER = ["farming", "conscription", "mining", "logistics", "inf.weapons", "art.weapons",
             "medicine", "industry", "inf.protection", "discipline", "staffwork", "drilling",
             "fieldworks", "drill", "art.protection", "refining"]

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
        if c and _afford(api, c) and api.stock.get("res", 0) - c.get("res", 0) > 40:
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                busy.add(line)
                if len(busy) >= 2: return

def _can_build(api, typ, reserve):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) - c.get("res", 0) < reserve: return False
    if api.mp < c.get("mp", 0) + 5: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0): return False
    return True

def _recruit(api, m):
    inc = api.income
    if inc <= 0.5 and api.t > 48: return
    t = api.t
    nrec = sum(1 for u in api.units if u["type"] == "rec")
    armour_seen = False
    for e in api.enemy.values():
        ty = e.get("types") or {}
        if isinstance(ty, dict) and (ty.get("arm", 0) or ty.get("hvt", 0)): armour_seen = True
    reserve = 30 + 0.3 * len(api.units)
    built = 0
    while built < 3:
        if nrec < 2 and api.unexplored:
            typ = "rec"
        elif api.neutral_border and t < 900:
            typ = "cav" if (m.get("rc", 0) % 2 == 0) else "inf"
        else:
            k = m.get("rc", 0) % 6
            if armour_seen and k == 5: typ = "atg"
            elif k in (2, 4): typ = "art"
            else: typ = "inf"
        if not _can_build(api, typ, reserve):
            if typ in ("art", "atg", "cav") and _can_build(api, "inf", reserve): typ = "inf"
            elif _can_build(api, "mil", reserve) and api.stock.get("res", 0) < 60 and not api.neutral_border: typ = "mil"
            else: break
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): break
        m["rc"] = m.get("rc", 0) + 1
        if typ == "rec": nrec += 1
        built += 1

def _attacks(api, m, byprov, uby):
    atks = m.setdefault("atk", {})
    t = api.t
    provs = api.provs
    busy = set()
    for tg, a in list(atks.items()):
        pr = provs.get(int(tg))
        ids = [i for i in a["ids"] if i in uby]
        done = (pr and pr.get("owner") == "me") or not ids
        if a.get("launch") is not None and t - a["launch"] > 60: done = True
        if a.get("launch") is None and t - a["start"] > 72: done = True
        if done:
            if ids: api.cmd("front " + ",".join(str(i) for i in ids))
            del atks[tg]; continue
        busy.update(ids)
        if a.get("launch") is None:
            bon = [uby[i].get("bonus", 0) for i in ids]
            avgb = sum(bon) / max(1, len(bon))
            if t - a["start"] >= 30 or avgb >= 30:
                api.cmd("move %s P%d" % (",".join(str(i) for i in ids), int(tg)))
                a["launch"] = t
    if len(atks) >= 2: return
    mdl = api.model or {}
    cands = []
    for p, e in api.enemy.items():
        pr = provs.get(p)
        if not pr or str(p) in atks: continue
        if p == api.capital: continue
        adj = [n for n in pr.get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
        if not adj: continue
        pool = []; dirs = 0
        for n in adj:
            us = [u for u in byprov.get(n, []) if u["id"] not in busy and u["type"] != "rec"
                  and u["str"] >= 60 and u.get("mor", 70) >= 40 and u["state"] not in ("routing", "shaken")]
            us.sort(key=lambda u: -u["str"])
            keep = 1 if len(byprov.get(n, [])) <= len(us) else 0
            take = us[keep:]
            if take: dirs += 1
            pool += take
        if len(pool) < 2: continue
        a_str = sum(u["str"] for u in pool)
        d_str = e.get("str", 0) or 0
        if not e.get("exact"): d_str *= 1.3
        tdf = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}.get(pr.get("terrain", "plain")[:8].rstrip("dt") if False else None, None)
        ter = pr.get("terrain", "plain")
        tdf = 2.0 if ter.startswith("m") else 1.5 if ter.startswith("h") else 1.25 if ter.startswith("f") else 1.0
        fort = pr.get("fort", 0) or 0
        city = 1 if pr.get("city") else 0
        heavy = sum(1 for u in pool if u["type"] in ("art", "eng", "arm")) / float(len(pool))
        rdy = sum(u["rdy"] for u in pool) / (100.0 * len(pool))
        ok = False; score = 0
        if mdl.get("w"):
            x = [math.log((a_str + 1) / (d_str + 1)), tdf, fort, city, 0.35, rdy, heavy, dirs]
            z = mdl["b"]
            for i in range(len(x)):
                z += mdl["w"][i] * (x[i] - mdl["mean"][i]) / (mdl["std"][i] or 1)
            score = _sig(z); ok = score >= 0.6
        need = 2.5 * tdf * (1 + 0.25 * fort) * (1.25 if city else 1)
        if a_str >= need * (d_str + 1): ok = True; score = max(score, 0.6)
        if ok:
            val = (pr.get("y", 0) or 0) + 3 * (1 if city else 0) + pr.get("steel", 0) + pr.get("oil", 0)
            cands.append((score + 0.01 * val, p, pool))
    cands.sort(key=lambda c: -c[0])
    for sc, p, pool in cands:
        if len(atks) >= 2: break
        ids = [u["id"] for u in pool if u["id"] not in busy]
        if len(ids) < 2: continue
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
    if api.t >= 200 and api.enemy:
        _attacks(api, m, byprov, uby)
```