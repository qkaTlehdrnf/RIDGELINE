def _sig(z):
    if z > 30: return 1.0
    if z < -30: return 0.0
    return 1.0 / (1.0 + math.exp(-z))

RES_ORDER = ["farming", "conscription", "logistics", "medicine", "industry",
             "art.weapons", "inf.weapons", "inf.protection", "staffwork", "drill",
             "discipline", "grn.weapons", "fieldworks", "mining", "art.protection",
             "eng.weapons", "grn.protection", "atg.weapons", "inf.mobility",
             "drilling", "refining", "mtn.weapons", "cav.mobility", "eng.protection"]

MIX_EARLY = [("inf", 0.45), ("cav", 0.25), ("art", 0.12), ("eng", 0.06), ("grn", 0.08), ("atg", 0.04)]
MIX_LATE = [("inf", 0.34), ("art", 0.22), ("grn", 0.16), ("eng", 0.10), ("atg", 0.08), ("mtn", 0.06), ("cav", 0.04)]
TERR = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}


def _afford(api, t, n):
    c = api.unit_costs.get(t)
    if not c: return 0
    st = api.stock
    best = n
    for k in ("res", "mp", "steel", "oil", "rare"):
        need = c.get(k, 0) or 0
        if need <= 0: continue
        if k == "res": have = api.res - 60
        elif k == "mp": have = api.mp - 10
        else: have = st.get(k, 0)
        best = min(best, int(have // need))
    return max(0, best)


def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    order = list(RES_ORDER) + sorted(k for k in api.tech.keys() if k not in RES_ORDER)
    for line in order:
        if len(busy) >= 2: break
        tk = api.tech.get(line)
        if not tk or tk.get("status") != "open" or line in busy: continue
        cost = tk.get("cost") or {}
        ok = True
        for k, v in cost.items():
            have = api.res if k == "res" else api.stock.get(k, 0)
            if have < v + (30 if k == "res" else 0): ok = False; break
        if ok and api.cmd("research " + line).startswith("ok"):
            busy.add(line)


def _recruit(api, units, mem):
    cnt = {}
    for u in units: cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    if cnt.get("rec", 0) < 4 and _afford(api, "rec", 1) > 0:
        api.cmd("recruit rec 1"); cnt["rec"] = cnt.get("rec", 0) + 1
    if api.res < 80: return
    if api.income < 0 and api.res < 400: return
    budget = (api.res - 60) * 0.6
    mix = MIX_EARLY if (api.t < 600 and api.neutral_border) else MIX_LATE
    lines = max(1, len(units) - cnt.get("rec", 0))
    plan = []
    for t, share in mix:
        if t not in api.unit_costs: continue
        gap = share - cnt.get(t, 0) / float(lines)
        plan.append((gap, t, share))
    plan.sort(reverse=True)
    spent = 0.0
    for gap, t, share in plan:
        c = api.unit_costs[t]
        cr = c.get("res", 10) or 10
        alloc = budget * max(0.1, share + max(0, gap))
        n = int(min(alloc, budget - spent) // cr)
        n = min(n, 25, _afford(api, t, 25))
        if n <= 0: continue
        r = api.cmd("recruit %s %d" % (t, n))
        if r.startswith("ok"):
            spent += n * cr
        if spent >= budget: break


def _dist(api, a, b):
    pa, pb = api.provs.get(a), api.provs.get(b)
    if not pa or not pb: return 999
    return abs(pa.get("x", 0) - pb.get("x", 0)) + abs(pa.get("y0", 0) - pb.get("y0", 0))


def _pwin(api, att, dfn, bonus, rdy, heavy, terr, fort, city, dirs):
    m = api.model or {}
    w = m.get("w"); mean = m.get("mean"); std = m.get("std")
    x = [math.log((att + 1.0) / (dfn + 1.0)), terr, fort, city, bonus, rdy, heavy, dirs]
    if not w or not mean or not std:
        return _sig(1.2 * x[0] - 0.3 * fort + 0.8 * bonus)
    z = m.get("b", 0)
    for i in range(min(len(w), len(x))):
        s = std[i] if std[i] else 1.0
        z += w[i] * (x[i] - mean[i]) / s
    return _sig(z)


def _release(api, ids):
    if ids: api.cmd("front " + ",".join(str(i) for i in ids))


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _run_op(api, op, byid):
    """returns False when op finished"""
    tgt = op["tgt"]
    tp = api.provs.get(tgt, {})
    asg = dict((i, s) for i, s in op["asg"].items() if i in byid)
    op["asg"] = asg
    ids = list(asg.keys())
    if tp.get("owner") == "me" or len(ids) < 3 or api.t - op["t0"] > 240:
        _release(api, ids)
        if op.get("rec") in byid: api.cmd("explore %d" % op["rec"])
        return False
    stgs = [s for s in op["stgs"] if api.provs.get(s, {}).get("owner") == "me"]
    if not stgs and op["phase"] != "go":
        _release(api, ids); return False
    e = api.enemy.get(tgt) or {}
    dfn = e.get("str", 0) or 0
    us = [byid[i] for i in ids]
    att = sum(u["str"] for u in us if u["type"] != "art") + 0.5 * sum(u["str"] for u in us if u["type"] == "art")
    ph = op["phase"]
    if ph == "gather":
        here = [u for u in us if u["prov"] == asg[u["id"]] and not u["path"]]
        if len(here) >= 0.75 * len(us) or api.t - op["t0"] > 90:
            api.cmd("hold " + _sel([u["id"] for u in here]))
            for u in us:
                if u not in here: del asg[u["id"]]
            _release(api, [u["id"] for u in us if u not in here])
            op["phase"] = "rest"; op["tr"] = api.t
    elif ph == "rest":
        rdy = sum(u["rdy"] for u in us) / float(len(us))
        if rdy >= 65 or api.t - op["tr"] > 54:
            for s in set(asg.values()):
                g = [i for i in ids if asg[i] == s]
                if g: api.cmd("prepare %s P%d" % (_sel(g), tgt))
            op["phase"] = "prep"; op["tp"] = api.t
    elif ph == "prep":
        if dfn > 1.3 * att and api.t - op["tp"] > 12:
            _release(api, ids); return False
        bonus = max([u.get("bonus", 0) or 0 for u in us] + [0])
        rdy = sum(u["rdy"] for u in us) / float(len(us))
        heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / float(len(us))
        dirs = len(set(asg.values()))
        p = _pwin(api, att, dfn, bonus / 100.0, rdy / 100.0, heavy,
                  TERR.get(tp.get("terrain"), 1.0), tp.get("fort", 0) or 0,
                  1 if tp.get("city") else 0, dirs)
        waited = api.t - op["tp"]
        if (bonus >= 35 and p > 0.45) or bonus >= 48 or (waited > 72 and p > 0.35) or \
           (waited > 30 and dfn == 0 and e == {}):
            go = [u["id"] for u in us if u["type"] != "art"]
            if go: api.cmd("move %s P%d" % (_sel(go), tgt))
            arts = [u["id"] for u in us if u["type"] == "art"]
            if arts: api.cmd("hold " + _sel(arts))
            op["phase"] = "go"; op["tg"] = api.t
        elif waited > 110:
            _release(api, ids); return False
    elif ph == "go":
        if api.t - op["tg"] > 72:
            _release(api, ids); return False
    return True


def _new_op(api, units, used, mem):
    line = [u for u in units if u["type"] not in ("rec", "mil")]
    if len(line) < 20: return None
    taken = set(o["tgt"] for o in mem.get("ops", []))
    best, bs = None, -1e9
    for b in api.border:
        pb = api.provs.get(b)
        if not pb or not pb.get("supplied"): continue
        for nb in pb.get("nbrs", []):
            if nb in taken: continue
            q = api.provs.get(nb)
            if not q or q.get("owner") != "enemy": continue
            e = api.enemy.get(nb) or {}
            es = e.get("str", 0) or 0
            fort = q.get("fort", 0) or 0
            stg = [s for s in q.get("nbrs", []) if api.provs.get(s, {}).get("owner") == "me"
                   and api.provs[s].get("supplied")]
            sc = q.get("y", 0) * 3 + (12 if q.get("city") else 0) - es * 0.12 \
                 - 14 * fort - 14 * (TERR.get(q.get("terrain"), 1) - 1) + 6 * min(3, len(stg))
            if nb in api.enemy_capitals.values(): sc += 40
            if q.get("elev", 0) > pb.get("elev", 0): sc -= 5 * (q["elev"] - pb["elev"])
            if sc > bs: bs, best = sc, (nb, stg, es)
    if not best: return None
    tgt, stgs, es = best
    stgs = sorted(stgs, key=lambda s: -(api.provs[s].get("elev", 0)))[:3]
    if not stgs: return None
    cand = [u for u in line if u["id"] not in used and u["str"] > 75 and u["rdy"] > 40
            and u["state"] not in ("routing", "shaken", "assault") and u["prov"] != api.capital
            and not u.get("expand")]
    cand.sort(key=lambda u: _dist(api, u["prov"], tgt))
    n = min(24, max(8, int(len(line) * 0.15)))
    pick = cand[:n]
    if len(pick) < 6: return None
    if sum(u["str"] for u in pick) < 2.0 * es: return None
    asg = {}
    for k, u in enumerate(pick):
        s = stgs[k % len(stgs)]
        asg[u["id"]] = s
    for s in stgs:
        g = [i for i in asg if asg[i] == s]
        if g: api.cmd("move %s P%d" % (_sel(g), s))
    gname = "op%d" % (mem.get("opn", 0) % 6)
    mem["opn"] = mem.get("opn", 0) + 1
    api.cmd("group %s %s" % (gname, _sel(list(asg.keys()))))
    op = {"tgt": tgt, "stgs": stgs, "asg": asg, "t0": api.t, "phase": "gather", "rec": None}
    recs = [u for u in units if u["type"] == "rec" and u["id"] not in used]
    if recs:
        recs.sort(key=lambda u: _dist(api, u["prov"], stgs[0]))
        op["rec"] = recs[0]["id"]
        api.cmd("move %d P%d" % (recs[0]["id"], stgs[0]))
    return op


def tick(api):
    mem = api.mem
    units = api.units
    byid = {}
    for u in units: byid[u["id"]] = u

    if not mem.get("init"):
        mem["init"] = 1
        recs = [u["id"] for u in units if u["type"] == "rec"]
        rest = [u["id"] for u in units if u["type"] != "rec"]
        if recs: api.cmd("explore " + _sel(recs))
        if rest: api.cmd("expand " + _sel(rest))

    try: _research(api)
    except Exception: pass
    try: _recruit(api, units, mem)
    except Exception: pass

    ops = mem.get("ops") or []
    used = set()
    for o in ops:
        used.update(o["asg"].keys())
        if o.get("rec") is not None: used.add(o["rec"])

    cap = api.capital
    threat = False
    cp = api.provs.get(cap)
    if cp:
        for nb in cp.get("nbrs", []) + [cap]:
            if nb in api.enemy: threat = True; break
    if threat and api.t - mem.get("capdef", -99) > 24:
        near = [u for u in units if u["type"] != "rec" and u["id"] not in used
                and u["prov"] != cap and _dist(api, u["prov"], cap) < 14 and u["str"] > 40]
        if near:
            api.cmd("move %s P%d" % (_sel([u["id"] for u in near[:12]]), cap))
            mem["capdef"] = api.t

    idle_exp, idle_front, idle_rec = [], [], []
    for u in units:
        if u["id"] in used: continue
        if u["path"] or u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["state"] in ("assault", "routing", "preparing"): continue
        if u["type"] == "rec":
            if api.unexplored: idle_rec.append(u["id"])
            continue
        if threat and u["prov"] == cap and api.t - mem.get("capdef", -99) < 48: continue
        if api.neutral_border: idle_exp.append(u["id"])
        else: idle_front.append(u["id"])
    if idle_rec: api.cmd("explore " + _sel(idle_rec))
    if idle_exp: api.cmd("expand " + _sel(idle_exp))
    if idle_front: api.cmd("front " + _sel(idle_front))

    keep = []
    for o in ops:
        try:
            if _run_op(api, o, byid): keep.append(o)
            else: mem["cool"] = api.t + 6
        except Exception:
            pass
    ops = keep
    try:
        nline = sum(1 for u in units if u["type"] not in ("rec", "mil"))
        maxops = 1 if nline < 60 else (2 if nline < 160 else 3)
        if len(ops) < maxops and api.t >= mem.get("cool", 0):
            used = set()
            for o in ops:
                used.update(o["asg"].keys())
                if o.get("rec") is not None: used.add(o["rec"])
            mem["ops"] = ops
            o = _new_op(api, units, used, mem)
            if o: ops.append(o)
            else: mem["cool"] = api.t + 12
    except Exception:
        pass
    mem["ops"] = ops
