def _sig(z):
    if z > 30: return 1.0
    if z < -30: return 0.0
    return 1.0 / (1.0 + math.exp(-z))

RES_ORDER = ["farming", "conscription", "industry", "logistics", "medicine",
             "inf.protection", "art.weapons", "inf.weapons", "discipline",
             "fieldworks", "mining", "drill", "staffwork", "atg.weapons",
             "art.protection", "drilling", "refining", "inf.mobility"]

MIX = [("inf", 0.48), ("art", 0.16), ("atg", 0.10), ("eng", 0.08),
       ("grn", 0.10), ("mtn", 0.08)]


def _cost_ok(api, t):
    c = api.unit_costs.get(t)
    if not c: return False
    st = api.stock
    if api.res < c.get("res", 0) + 25: return False
    if api.mp < c.get("mp", 0) + 5: return False
    if st.get("steel", 0) < c.get("steel", 0): return False
    if st.get("oil", 0) < c.get("oil", 0): return False
    if st.get("rare", 0) < c.get("rare", 0): return False
    return True


def _research(api):
    try:
        if len(api.research) >= 2: return
        busy = set(r[0] for r in api.research)
        for line in RES_ORDER:
            if len(api.research) + 0 >= 2: break
            tk = api.tech.get(line)
            if not tk or tk.get("status") != "open" or line in busy: continue
            cost = tk.get("cost") or {}
            ok = True
            for k, v in cost.items():
                have = api.res if k == "res" else api.stock.get(k, 0)
                margin = 40 if k == "res" else 0
                if have < v + margin: ok = False; break
            if ok:
                r = api.cmd("research " + line)
                if r.startswith("ok"):
                    busy.add(line)
                    if len(busy) >= 2: break
    except Exception:
        pass


def _recruit(api, units, mem):
    if api.t - mem.get("last_rec", -99) < 6: return
    n = len(units)
    cnt = {}
    for u in units: cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    nrec = cnt.get("rec", 0)
    if nrec < 2 and _cost_ok(api, "rec"):
        if api.cmd("recruit rec").startswith("ok"):
            mem["last_rec"] = api.t
        return
    inc = api.income
    if inc < 1.0 and api.res < 120: return
    lines = n - nrec
    best, bestgap = None, -9
    for t, share in MIX:
        if t not in api.unit_costs: continue
        if lines < 6 and t != "inf": continue
        gap = share - (cnt.get(t, 0) / float(max(1, lines)))
        if gap > bestgap and _cost_ok(api, t):
            best, bestgap = t, gap
    if best is None and _cost_ok(api, "inf"): best = "inf"
    if best is None and api.mp > 30 and _cost_ok(api, "mil") and inc < 2: best = "mil"
    if best:
        k = 2 if api.res > 300 and inc > 6 else 1
        if api.cmd("recruit %s %d" % (best, k)).startswith("ok"):
            mem["last_rec"] = api.t


def _dist(api, a, b):
    pa, pb = api.provs.get(a), api.provs.get(b)
    if not pa or not pb: return 999
    return abs(pa.get("x", 0) - pb.get("x", 0)) + abs(pa.get("y0", 0) - pb.get("y0", 0))


def _pwin(api, att, dfn, bonus, rdy, heavy, terr, fort, city, dirs):
    m = api.model or {}
    w = m.get("w"); mean = m.get("mean"); std = m.get("std")
    if not w or not mean or not std: 
        return _sig(1.2 * math.log((att + 1.0) / (dfn + 1.0)) - 0.3 * fort)
    x = [math.log((att + 1.0) / (dfn + 1.0)), terr, fort, city, bonus, rdy, heavy, dirs]
    z = m.get("b", 0)
    for i in range(min(len(w), len(x))):
        s = std[i] if std[i] else 1.0
        z += w[i] * (x[i] - mean[i]) / s
    return _sig(z)


TERR = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}


def _release(api, ids):
    if ids:
        api.cmd("front " + ",".join(str(i) for i in ids))


def _operation(api, units, mem, byid):
    op = mem.get("op")
    if op:
        tgt, stg = op["tgt"], op["stg"]
        ids = [i for i in op["ids"] if i in byid]
        op["ids"] = ids
        tp = api.provs.get(tgt, {})
        if tp.get("owner") == "me" or not ids or api.t - op["t0"] > 160 or \
           api.provs.get(stg, {}).get("owner") != "me" and op["phase"] != "go":
            _release(api, ids)
            if op.get("rec") in byid: api.cmd("explore %d" % op["rec"])
            mem["op"] = None
            mem["cool"] = api.t + 12
            return
        sel = ",".join(str(i) for i in ids)
        if op["phase"] == "gather":
            here = [i for i in ids if byid[i]["prov"] == stg and not byid[i]["path"]]
            if len(here) >= max(3, int(0.7 * len(ids))) or api.t - op["t0"] > 72:
                api.cmd("prepare %s P%d" % (",".join(str(i) for i in here) or sel, tgt))
                op["ids"] = here or ids
                op["phase"] = "prep"; op["tp"] = api.t
        elif op["phase"] == "prep":
            us = [byid[i] for i in op["ids"] if i in byid]
            att = sum(u["str"] for u in us)
            bonus = max([u.get("bonus", 0) for u in us] + [0])
            rdy = sum(u["rdy"] for u in us) / max(1, len(us))
            heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / float(max(1, len(us)))
            e = api.enemy.get(tgt) or {}
            dfn = e.get("str", 0) or 0
            p = _pwin(api, att, dfn, bonus / 100.0, rdy / 100.0, heavy,
                      TERR.get(tp.get("terrain"), 1.0), tp.get("fort", 0) or 0,
                      1 if tp.get("city") else 0, 1)
            waited = api.t - op["tp"]
            if (p > 0.6 and waited >= 18) or (bonus >= 45 and att > 1.4 * dfn) or \
               (waited > 60 and att > 1.8 * dfn):
                api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in us), tgt))
                op["phase"] = "go"; op["tg"] = api.t
            elif waited > 84:
                _release(api, op["ids"]); mem["op"] = None; mem["cool"] = api.t + 24
        elif op["phase"] == "go":
            if api.t - op["tg"] > 60:
                _release(api, ids); mem["op"] = None; mem["cool"] = api.t + 12
        return

    if api.t < mem.get("cool", 0): return
    line = [u for u in units if u["type"] != "rec"]
    if len(line) < 18: return
    # choose target
    best, bs = None, -1e9
    for b in api.border:
        pb = api.provs.get(b)
        if not pb or not pb.get("supplied"): continue
        for nb in pb.get("nbrs", []):
            q = api.provs.get(nb)
            if not q or q.get("owner") != "enemy": continue
            e = api.enemy.get(nb) or {}
            es = e.get("str", 0) or 0
            sc = q.get("y", 0) * 3 + (15 if q.get("city") else 0) - es * 0.08 \
                 - 6 * (q.get("fort", 0) or 0) - 8 * (TERR.get(q.get("terrain"), 1) - 1)
            if nb in api.enemy_capitals.values(): sc += 40
            if q.get("elev", 0) > pb.get("elev", 0): sc -= 4 * (q["elev"] - pb["elev"])
            if sc > bs: bs, best = sc, (nb, b)
    if not best: return
    tgt, stg = best
    e = api.enemy.get(tgt) or {}
    cand = [u for u in line if u["str"] > 75 and u["rdy"] > 50 and u["state"] not in ("routing", "shaken")
            and u["type"] != "mil" and u["prov"] != api.capital]
    cand.sort(key=lambda u: _dist(api, u["prov"], stg))
    n = min(12, max(6, int(len(line) * 0.35)))
    pick = cand[:n]
    if len(pick) < 5: return
    if sum(u["str"] for u in pick) < 1.3 * (e.get("str", 0) or 0): return
    ids = [u["id"] for u in pick]
    api.cmd("move %s P%d" % (",".join(str(i) for i in ids), stg))
    api.cmd("group strike %s" % ",".join(str(i) for i in ids))
    op = {"tgt": tgt, "stg": stg, "ids": ids, "t0": api.t, "phase": "gather", "rec": None}
    recs = [u for u in units if u["type"] == "rec"]
    if recs:
        recs.sort(key=lambda u: _dist(api, u["prov"], stg))
        op["rec"] = recs[0]["id"]
        api.cmd("move %d P%d" % (recs[0]["id"], stg))
    mem["op"] = op


def tick(api):
    mem = api.mem
    units = api.units
    byid = {}
    for u in units: byid[u["id"]] = u

    if not mem.get("init"):
        mem["init"] = 1
        for u in units:
            if u["type"] == "rec": api.cmd("explore %d" % u["id"])
            else: api.cmd("expand %d" % u["id"])

    _research(api)
    try:
        _recruit(api, units, mem)
    except Exception:
        pass

    op = mem.get("op")
    opids = set(op["ids"]) if op else set()
    oprec = op.get("rec") if op else None

    # capital emergency
    cap = api.capital
    threat = False
    cp = api.provs.get(cap)
    if cp:
        for nb in cp.get("nbrs", []) + [cap]:
            if nb in api.enemy: threat = True; break
    if threat:
        near = [u for u in units if u["type"] not in ("rec",) and u["id"] not in opids
                and u["prov"] != cap and _dist(api, u["prov"], cap) < 14 and u["str"] > 40]
        if near and api.t - mem.get("capdef", -99) > 24:
            api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in near[:8]), cap))
            mem["capdef"] = api.t

    # idle units
    idle_exp, idle_front = [], []
    for u in units:
        if u["id"] in opids or u["id"] == oprec: continue
        if u["path"] or u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["state"] in ("assault", "routing", "preparing"): continue
        if u["type"] == "rec":
            if api.unexplored: api.cmd("explore %d" % u["id"])
            continue
        if threat and u["prov"] == cap and api.t - mem.get("capdef", -99) < 48: continue
        if api.neutral_border: idle_exp.append(u["id"])
        else: idle_front.append(u["id"])
    if idle_exp: api.cmd("expand " + ",".join(str(i) for i in idle_exp))
    if idle_front: api.cmd("front " + ",".join(str(i) for i in idle_front))

    try:
        _operation(api, units, mem, byid)
    except Exception:
        mem["op"] = None
