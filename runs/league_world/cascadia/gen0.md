Cascadia is fast and cheap but weak on defence. So the plan is to grab land quickly, build income, and keep the army alive, since score decides the war at tick 4800.

- **Early game:** two or three scouts explore. Cheap fast cavalry and infantry take neutral land with `expand`.
- **Garrison:** three units dig in at Seattle. If enemies appear next to the capital, militia are raised there.
- **Research:** two projects run at all times. Economy lines come first: farming, conscription, industry, mining, logistics and medicine. Combat lines (infantry, artillery, assault infantry) follow. Dead ends are skipped automatically.
- **Recruiting:** only while daily net income stays positive after upkeep and a bank reserve remains. The mix leans toward infantry with artillery and assault infantry. Anti-tank guns are added once enemy armour is seen.
- **Attacks:** units idle in the rear join the front order. Every tick I score enemy provinces next to my border with the fitted battle model. If one is clearly winnable (p≥0.6, strength ratio ≥2), healthy nearby units take part. They prepare for about 30 h (a scout is brought up when available) and then assault. They return to the front order after a capture or a timeout.
- **Limits:** at most 3 attacks run at once, and the work per tick is kept cheap.

```python
def _tdfn(t):
    t = str(t or "p")
    c = t[0]
    if c == "m":
        return 2.0
    if c == "h":
        return 1.5
    if c == "f":
        return 1.25
    return 1.0

def _sig(x):
    if x < -30: return 0.0
    if x > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-x))

RESEARCH = ["farming", "conscription", "industry", "mining", "logistics", "medicine",
            "inf.weapons", "art.weapons", "discipline", "drill", "inf.protection",
            "grn.weapons", "staffwork", "fieldworks", "drilling", "refining",
            "art.protection", "grn.protection", "cav.weapons", "atg.weapons"]

def _research(api):
    if len(api.research) >= 2:
        return
    busy = set(r[0] for r in api.research)
    st = api.stock or {}
    for line in RESEARCH:
        if len(api.research) + len(busy) - len(set(r[0] for r in api.research)) >= 2:
            break
        info = api.tech.get(line)
        if not info or line in busy:
            continue
        if info.get("status") != "open":
            continue
        cost = info.get("cost") or {}
        ok = True
        for k, v in cost.items():
            have = st.get(k, 0)
            need = v + (60 if k == "res" else 0)
            if have < need:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research " + line)
        if str(r).startswith("ok"):
            busy.add(line)
            if len(busy) >= 2:
                break

def _affordable(api, typ, n):
    uc = api.unit_costs.get(typ)
    if not uc:
        return False
    st = api.stock or {}
    if st.get("res", api.res) < uc.get("res", 0) * n + 25:
        return False
    if api.mp < uc.get("mp", 0) * n + 5:
        return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < uc.get(k, 0) * n:
            return False
    return True

def _recruit(api, counts, armour_seen, threat):
    m = api.mem
    cap = api.capital
    if threat and _affordable(api, "mil", 2):
        api.cmd("recruit mil 2 P%d" % cap)
    inc = (api.income_by or {}).get("res", api.income)
    if inc is None:
        inc = 0
    total = sum(counts.values())
    if counts.get("rec", 0) + m.get("rec_q", 0) < 3 and api.t < 1500:
        if _affordable(api, "rec", 1):
            if str(api.cmd("recruit rec 1")).startswith("ok"):
                m["rec_q"] = m.get("rec_q", 0) + 1
                return
    # upkeep gate
    if inc < 0.8 + 0.02 * total:
        return
    if api.t < 720:
        target = {"cav": 0.45, "inf": 0.55}
    else:
        target = {"inf": 0.42, "art": 0.15, "grn": 0.15, "cav": 0.08, "eng": 0.05, "atg": 0.15 if armour_seen else 0.03}
    combat = max(1, sum(v for k, v in counts.items() if k != "rec"))
    best, gap = None, -9
    for k, w in target.items():
        g = w - counts.get(k, 0) / float(combat)
        if g > gap and _affordable(api, k, 1):
            best, gap = k, g
    if best is None:
        return
    n = 2 if _affordable(api, best, 2) and inc > 3 else 1
    api.cmd("recruit %s %d" % (best, n))

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
                keys = ty.keys() if hasattr(ty, "keys") else ty
                for k in keys:
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

    # garrison
    gar = [g for g in m["garrison"] if g in byid]
    m["garrison"] = gar
    attackers = set()
    for a in m["attacks"].values():
        for i in a["ids"]:
            attackers.add(i)

    # assign idle units
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
        if len(gar) < 3 and typ in ("inf", "mil", "eng", "atg", "grn") and u["prov"] == cap:
            gar.append(uid); gset.add(uid)
            api.cmd("fortify %d" % uid)
            continue
        if typ == "mil":
            if u["prov"] == cap:
                api.cmd("fortify %d" % uid)
            else:
                api.cmd("front %d" % uid)
            continue
        if api.neutral_border and typ != "art":
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
        if not ids or owner == "me" or age > 110:
            for i in ids:
                if byid[i]["type"] == "rec":
                    api.cmd("explore %d" % i)
                else:
                    api.cmd("front %d" % i)
            del m["attacks"][tgt]
            continue
        if a["phase"] == "prep" and age >= 30:
            sel = ",".join(str(i) for i in ids if byid[i]["type"] != "rec")
            if sel:
                api.cmd("move %s P%d" % (sel, tgt))
            a["phase"] = "go"

    if len(m["attacks"]) >= 3 or t % 12 >= 6 and len(m["attacks"]) >= 1:
        return

    # find new attack targets
    model = api.model or {}
    w = model.get("w"); mean = model.get("mean"); std = model.get("std"); b = model.get("b", 0)
    busy = attackers | gset
    byprov = {}
    for u in units:
        if u["id"] in busy or u["type"] in ("rec", "mil"):
            continue
        if u["str"] < 60 or u["state"] in ("routing", "shaken", "pinned"):
            continue
        byprov.setdefault(u["prov"], []).append(u)
    recs = [u for u in units if u["type"] == "rec" and u["id"] not in attackers]
    best = None
    for tgt, e in enemy.items():
        if tgt in m["attacks"]:
            continue
        tp = provs.get(tgt)
        if not tp:
            continue
        cands = []
        dirs = 0
        for nb in tp.get("nbrs", []):
            pn = provs.get(nb)
            if not pn or pn.get("owner") != "me" or nb == cap:
                continue
            lst = byprov.get(nb)
            if lst:
                # leave one unit behind if province is a border with other threats
                take = lst if len(lst) > 1 else lst
                cands.extend(take)
                dirs += 1
        if len(cands) < 3:
            continue
        astr = sum(u["str"] for u in cands)
        dstr = e.get("str", 0) or 0
        if not e.get("exact"):
            dstr *= 1.3
        ratio = (astr + 1.0) / (dstr + 1.0)
        if ratio < 2.0:
            continue
        rdy = sum(u["rdy"] for u in cands) / float(len(cands)) / 100.0
        heavy = sum(1 for u in cands if u["type"] in ("art", "eng", "arm")) / float(len(cands))
        x = [math.log(ratio), _tdfn(tp.get("terrain")), tp.get("fort", 0) or 0,
             1 if tp.get("city") else 0, 0.3, rdy, heavy, dirs]
        if w and mean and std:
            z = b
            for i in range(min(len(w), len(x))):
                s = std[i] if std[i] else 1
                z += w[i] * (x[i] - mean[i]) / s
            p = _sig(z)
        else:
            p = 0.7 if ratio > 3 else 0.5
        if tgt in (api.enemy_capitals or {}).values():
            p += 0.15
        score = p + 0.02 * (tp.get("y", 0) or 0)
        if p >= 0.6 and (best is None or score > best[0]):
            best = (score, tgt, cands)
    if best:
        _, tgt, cands = best
        ids = [u["id"] for u in cands]
        sel = ",".join(str(i) for i in ids)
        r = api.cmd("prepare %s P%d" % (sel, tgt))
        if str(r).startswith("ok"):
            rid = None
            tp = provs.get(tgt, {})
            for rc in recs:
                if rc["str"] > 40:
                    rid = rc["id"]
                    break
            if rid is not None:
                nb = None
                for n2 in tp.get("nbrs", []):
                    if provs.get(n2, {}).get("owner") == "me":
                        nb = n2
                        break
                if nb is not None:
                    api.cmd("move %d P%d" % (rid, nb))
                    ids.append(rid)
            m["attacks"][tgt] = {"ids": ids, "t0": t, "phase": "prep"}
```