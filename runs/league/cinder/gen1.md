Both wars show the same failure: assaults almost never worked (2 of 95, then 0 of 48), and nearly all of them were launched with readiness under 34. Units marched to the staging province, which drains readiness, and then attacked at once with little or no plan bonus. Only one operation ran at a time, with armies of 1,600 units. In war 1, 108k res and 50k manpower were left unspent. In war 2, expansion stalled early.

Changes:
- **Several operations at once.** Up to about one per 50 front units, at most 7.
- **Attacks from more than one side.** Each operation stages from up to 3 own provinces next to the target. The fitted model gives a strong weight to the number of directions.
- **Wait before launching.** Units prepare until readiness and plan bonus are high (about 60 readiness, 40% bonus) or the model's odds are good. Artillery holds next door and shells the key point.
- **A scout for every operation.** A rec next to the target raises the bonus cap to +75% and gives exact enemy counts.
- **Cancel weak attacks.** If our strength looks too low against the target's defence, the units go back to the front.
- **More scouting.** 5 rec early instead of 2, for faster exploration and expansion.
- **Spend the surplus.** When the bank is large, recruit more each tick, with a balanced inf/grn/art/atg mix.
- **Research order.** Drill and staffwork move earlier.

```python
TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
RES_ORDER = ["farming", "conscription", "staffwork", "drill", "inf.weapons", "grn.weapons",
             "art.weapons", "mining", "logistics", "medicine", "discipline", "inf.protection",
             "industry", "fieldworks", "art.protection", "grn.protection", "drilling", "refining"]
ARTY = ("art", "rkt")


def sig(z):
    if z < -30:
        return 0.0
    if z > 30:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def can_pay(api, cost, reserve=0):
    st = api.stock
    for k, v in cost.items():
        if k in ("res", "steel", "oil", "rare"):
            need = v + (reserve if k == "res" else 0)
            if st.get(k, 0) < need:
                return False
    return True


def do_research(api):
    if len(api.research) >= 2:
        return
    busy = set(r[0] for r in api.research)
    n = len(api.research)
    for line in RES_ORDER:
        if n >= 2:
            break
        tk = api.tech.get(line)
        if not tk or line in busy:
            continue
        if tk.get("status") != "open" or not tk.get("cost"):
            continue
        if can_pay(api, tk["cost"], 40):
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                n += 1


def enemy_armor(api):
    for p, e in api.enemy.items():
        s = str(e.get("types", ""))
        if "arm" in s or "hvt" in s or "mec" in s:
            return True
    return False


def do_recruit(api, units, nops):
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    army = len(units)
    t = api.t
    net = api.income_by.get("res", api.income)
    limit = 3 + int(min(9, max(0, api.res - 400) // 400))
    made = 0
    upkd = {"inf": 0.09, "art": 0.135, "grn": 0.114, "atg": 0.075, "rec": 0.045}
    wantrec = (5 if t < 1200 else 2) + nops
    armor = enemy_armor(api)
    tries = 0
    while made < limit and tries < limit + 4:
        tries += 1
        tot = max(1, army - cnt.get("rec", 0))
        if cnt.get("rec", 0) < wantrec:
            typ = "rec"
        elif t < 150 or army < 8:
            typ = "inf"
        elif cnt.get("art", 0) < 0.2 * tot:
            typ = "art"
        elif cnt.get("grn", 0) < 0.22 * tot:
            typ = "grn"
        elif armor and cnt.get("atg", 0) < 0.1 * tot:
            typ = "atg"
        else:
            typ = "inf"
        c = api.unit_costs.get(typ)
        if not c:
            break
        upk = upkd.get(typ, 0.1)
        if net < 1.0 + upk * 5 and army > 4:
            break
        if api.mp < c.get("mp", 9) + 15:
            break
        reserve = 20 if t < 200 else 60
        if not can_pay(api, c, reserve):
            if typ != "inf":
                c = api.unit_costs.get("inf")
                typ = "inf"
                if not c or not can_pay(api, c, reserve):
                    break
            else:
                break
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"):
            break
        made += 1
        net -= upk
        cnt[typ] = cnt.get(typ, 0) + 1
        army += 1


def model_p(api, my_str, e_str, tdf, fort, city, bonus, rdy, heavy, dirs):
    m = api.model
    try:
        x = [math.log((my_str + 1.0) / (e_str + 1.0)), tdf, fort, 1.0 if city else 0.0,
             bonus, rdy, heavy, dirs]
        z = m["b"]
        for i in range(len(x)):
            z += m["w"][i] * (x[i] - m["mean"][i]) / (m["std"][i] or 1.0)
        return sig(z)
    except Exception:
        r = (my_str + 1.0) / (e_str * tdf * (1 + 0.25 * fort) + 1.0)
        return sig(1.5 * (r - 2.0))


def js(l):
    return ",".join(str(i) for i in l)


def op_ids(op):
    out = []
    for s, l in op["g"].items():
        out.extend(l)
    if op.get("rec") is not None:
        out.append(op["rec"])
    return out


def release(api, op):
    ids = [i for s, l in op["g"].items() for i in l]
    if ids:
        api.cmd("front " + js(ids))
    if op.get("rec") is not None:
        api.cmd("explore %d" % op["rec"])


def estr_of(api, T):
    e = api.enemy.get(T)
    if e:
        return float(e.get("str", 0) or 0)
    pr = api.provs.get(T, {})
    if pr.get("visible"):
        return 0.0
    return 120.0


def choose_target(api, units, used, busyT, maxtake):
    pool = [u for u in units if u["type"] != "rec" and u["front"] and not u.get("expand")
            and u["id"] not in used
            and u["str"] >= 70 and u["state"] not in ("routing", "shaken", "refitting")]
    if len(pool) < 5:
        return None
    caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
    cands = []
    for T, pr in api.provs.items():
        if pr.get("owner") != "enemy" or T in busyT:
            continue
        stg = [n for n in pr.get("nbrs", []) if api.provs.get(n, {}).get("owner") == "me"]
        if not stg:
            continue
        es = estr_of(api, T)
        tdf = TDF.get(pr.get("terrain"), 1.3) + (0.25 if pr.get("city") else 0)
        fort = pr.get("fort", 0) or 0
        val = (pr.get("y", 1) or 1) + 1.0
        if T in caps:
            val *= 5
        val += 0.5 * ((pr.get("steel", 0) or 0) + (pr.get("oil", 0) or 0) + (pr.get("rare", 0) or 0))
        val *= (1 + 0.3 * min(3, len(stg) - 1))
        sc = val / ((es + 40.0) * tdf * (1 + 0.35 * fort))
        cands.append((sc, T, stg, es, tdf, fort))
    cands.sort(reverse=True)
    for sc, T, stg, es, tdf, fort in cands[:8]:
        pT = api.provs[T]
        tx, ty = pT.get("x", 0), pT.get("y0", 0)
        stg = sorted(stg, key=lambda s: (-(1 if api.provs[s].get("supplied") else 0),
                                         -(api.provs[s].get("stock", 0) or 0)))[:3]
        need = max(200.0, 3.0 * es * tdf * (1 + 0.25 * fort))
        ranked = []
        for u in pool:
            pu = api.provs.get(u["prov"])
            if not pu:
                continue
            d = (pu.get("x", 0) - tx) ** 2 + (pu.get("y0", 0) - ty) ** 2
            if d > 1000:
                continue
            ranked.append((d, u["id"], u, pu))
        ranked.sort(key=lambda a: a[0])
        took = []
        tot = 0.0
        for d, i, u, pu in ranked:
            if len(took) >= maxtake or tot >= need * 1.5:
                break
            took.append((u, pu))
            tot += u["str"] * (1.6 if u["type"] in ("art", "grn") else 1.0)
        if tot >= need and len(took) >= 4:
            g = {}
            for s in stg:
                g[s] = []
            for u, pu in took:
                best = None
                for s in stg:
                    ps = api.provs[s]
                    d = (pu.get("x", 0) - ps.get("x", 0)) ** 2 + (pu.get("y0", 0) - ps.get("y0", 0)) ** 2
                    d *= (1 + 0.15 * len(g[s]))
                    if best is None or d < best[0]:
                        best = (d, s)
                g[best[1]].append(u["id"])
            g = dict((s, l) for s, l in g.items() if l)
            return dict(T=T, g=g, phase="gather", t0=api.t, rec=None, sent=0)
    return None


def run_op(api, op, byid):
    """return False when op should be dropped"""
    for s in list(op["g"].keys()):
        op["g"][s] = [i for i in op["g"][s] if i in byid]
        if not op["g"][s]:
            del op["g"][s]
    if op.get("rec") is not None and op["rec"] not in byid:
        op["rec"] = None
    ids = [i for s, l in op["g"].items() for i in l]
    T = op["T"]
    if len(ids) < 3:
        release(api, op)
        return False
    pT = api.provs.get(T, {})
    if pT.get("owner") == "me":
        release(api, op)
        return False
    if op["phase"] != "assault":
        for s in list(op["g"].keys()):
            if api.provs.get(s, {}).get("owner") != "me":
                api.cmd("front " + js(op["g"][s]))
                del op["g"][s]
        if not op["g"]:
            return False
    us = [byid[i] for i in ids if i in byid]
    avg = sum(u["str"] for u in us) / max(1, len(us))
    if avg < 40:
        release(api, op)
        return False
    if op["phase"] == "gather":
        if not op["sent"]:
            for s, l in op["g"].items():
                api.cmd("move %s P%d" % (js(l), s))
            op["sent"] = 1
            return True
        here = 0
        for s, l in op["g"].items():
            for i in l:
                u = byid[i]
                if u["prov"] == s and not u["path"]:
                    here += 1
        if here >= 0.8 * len(ids) or api.t - op["t0"] > 96:
            for s, l in op["g"].items():
                inf = [i for i in l if byid[i]["type"] not in ARTY]
                art = [i for i in l if byid[i]["type"] in ARTY]
                if inf:
                    api.cmd("prepare %s P%d" % (js(inf), T))
                if art:
                    api.cmd("hold " + js(art))
            op["phase"] = "prep"
            op["tp"] = api.t
        return True
    if op["phase"] == "prep":
        es = estr_of(api, T)
        mine = 0.0
        for s, l in op["g"].items():
            for i in l:
                u = byid[i]
                if u["prov"] == s:
                    mine += u["str"]
        tdf = TDF.get(pT.get("terrain"), 1.3)
        fort = pT.get("fort", 0) or 0
        pu = [u for u in us if u["type"] not in ARTY]
        bonus = sum(u.get("bonus", 0) or 0 for u in pu) / max(1, len(pu))
        rdy = sum(u["rdy"] for u in us) / max(1, len(us))
        heavy = sum(1 for u in us if u["type"] in ARTY) / float(max(1, len(us)))
        dirs = len(op["g"])
        p = model_p(api, mine, es, tdf, fort, pT.get("city"), bonus / 100.0, rdy / 100.0, heavy, dirs)
        waited = api.t - op["tp"]
        if es > 0 and mine < 1.2 * es * tdf * (1 + 0.2 * fort) and waited > 30:
            release(api, op)
            return False
        if waited > 150:
            release(api, op)
            return False
        go = False
        if bonus >= 40 and rdy >= 60:
            go = True
        elif p >= 0.75 and waited >= 12 and rdy >= 45:
            go = True
        elif waited >= 96 and p >= 0.4:
            go = True
        if go:
            for s, l in op["g"].items():
                inf = [i for i in l if byid[i]["type"] not in ARTY]
                if inf:
                    api.cmd("move %s P%d" % (js(inf), T))
            op["phase"] = "assault"
            op["ta"] = api.t
        return True
    if op["phase"] == "assault":
        if api.t - op["ta"] > 72:
            release(api, op)
            return False
        return True
    return False


def attach_recs(api, units, ops, used):
    free = [u for u in units if u["type"] == "rec" and u["id"] not in used
            and u["state"] not in ("routing",)]
    nrec = len(free)
    for op in ops:
        if op.get("rec") is not None or op["phase"] == "assault":
            continue
        cand = [u for u in free if not u.get("explore")] or (free if nrec > 3 else [])
        if not cand:
            break
        u = cand[0]
        free.remove(u)
        nrec -= 1
        s = list(op["g"].keys())[0]
        r = api.cmd("move %d P%d" % (u["id"], s))
        if r.startswith("ok"):
            op["rec"] = u["id"]
            used.add(u["id"])


def assign_idle(api, units, used):
    nb = bool(api.neutral_border)
    exp_n = sum(1 for u in units if u.get("expand"))
    nonrec = sum(1 for u in units if u["type"] != "rec")
    for u in units:
        if u["id"] in used:
            continue
        if u["front"] or u.get("expand") or u.get("explore") or u["path"]:
            continue
        if u["state"] in ("routing",):
            continue
        if u["type"] == "rec":
            if api.unexplored:
                api.cmd("explore %d" % u["id"])
            continue
        if nb and (exp_n < max(4, int(0.6 * nonrec)) or not api.enemy):
            r = api.cmd("expand %d" % u["id"])
            if r.startswith("ok"):
                exp_n += 1
                continue
        api.cmd("front %d" % u["id"])


def tick(api):
    m = api.mem
    if "ops" not in m:
        m["ops"] = []
        m["cool"] = 0
    units = api.units
    byid = {}
    for u in units:
        byid[u["id"]] = u
    try:
        do_research(api)
    except Exception:
        pass
    try:
        do_recruit(api, units, len(m["ops"]))
    except Exception:
        pass
    keep = []
    for op in m["ops"]:
        try:
            if run_op(api, op, byid):
                keep.append(op)
        except Exception:
            pass
    m["ops"] = keep
    used = set()
    for op in m["ops"]:
        used.update(op_ids(op))
    try:
        nonrec = sum(1 for u in units if u["type"] != "rec")
        maxops = max(1, min(7, nonrec // 50))
        if api.t > 100 and nonrec >= 10 and len(m["ops"]) < maxops and api.t >= m.get("cool", 0):
            busyT = set(op["T"] for op in m["ops"])
            maxtake = max(6, min(40, nonrec // 6))
            op = choose_target(api, units, used, busyT, maxtake)
            if op:
                m["ops"].append(op)
                run_op(api, op, byid)
                used.update(op_ids(op))
            else:
                m["cool"] = api.t + 12
    except Exception:
        pass
    try:
        attach_recs(api, units, m["ops"], used)
    except Exception:
        pass
    try:
        assign_idle(api, units, used)
    except Exception:
        pass
```