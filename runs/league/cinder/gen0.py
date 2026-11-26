TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
RES_ORDER = ["farming", "conscription", "mining", "inf.weapons", "art.weapons",
             "logistics", "medicine", "grn.weapons", "discipline", "inf.protection",
             "staffwork", "industry", "drill", "art.protection", "fieldworks",
             "drilling", "refining", "grn.protection"]


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


def do_recruit(api, units):
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    army = len(units)
    t = api.t
    want = []
    if cnt.get("rec", 0) < 2 and t < 1500:
        want.append("rec")
    if t < 200 or army < 6:
        want.append("inf")
    else:
        tot = max(1, army - cnt.get("rec", 0))
        armor = enemy_armor(api)
        if cnt.get("art", 0) < 0.2 * tot:
            want.append("art")
        if cnt.get("grn", 0) < 0.2 * tot:
            want.append("grn")
        if armor and cnt.get("atg", 0) < 0.12 * tot:
            want.append("atg")
        want.append("inf")
    made = 0
    net = api.income_by.get("res", api.income)
    for typ in want:
        if made >= 3:
            break
        c = api.unit_costs.get(typ)
        if not c:
            continue
        upk = {"inf": 0.09, "art": 0.135, "grn": 0.114, "atg": 0.075, "rec": 0.045}.get(typ, 0.1)
        if net < 1.0 + upk * 5 and army > 4:
            continue
        if api.mp < c.get("mp", 9) + 15:
            continue
        reserve = 20 if t < 200 else 50
        if not can_pay(api, c, reserve):
            continue
        r = api.cmd("recruit %s 1" % typ)
        if r.startswith("ok"):
            made += 1
            net -= upk
        # keep filling infantry if rich
    if made < 3 and api.res > 300 and net > 3 and api.mp > 60:
        c = api.unit_costs.get("inf", {})
        if can_pay(api, c, 200):
            api.cmd("recruit inf 2")


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


def release(api, op):
    if op and op.get("ids"):
        api.cmd("front " + ",".join(str(i) for i in op["ids"]))
    api.mem["op"] = None
    api.mem["cool"] = api.t + 6


def estr_of(api, T):
    e = api.enemy.get(T)
    if e:
        return float(e.get("str", 0) or 0)
    pr = api.provs.get(T, {})
    if pr.get("visible"):
        return 0.0
    return 120.0


def choose_target(api, units, byid):
    pool = [u for u in units if u["type"] != "rec" and u["front"] and not u.get("expand")
            and u["str"] >= 70 and u["state"] not in ("routing", "shaken", "refitting")]
    frontn = sum(1 for u in units if u["type"] != "rec")
    if len(pool) < 4:
        return None
    maxtake = max(4, frontn // 2)
    caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
    cands = []
    for T, pr in api.provs.items():
        if pr.get("owner") != "enemy":
            continue
        stg = [n for n in pr.get("nbrs", []) if api.provs.get(n, {}).get("owner") == "me"]
        if not stg:
            continue
        es = estr_of(api, T)
        tdf = TDF.get(pr.get("terrain"), 1.3) + (0.25 if pr.get("city") else 0)
        fort = pr.get("fort", 0) or 0
        val = (pr.get("y", 1) or 1) + 1.0
        if T in caps:
            val *= 4
        val += 0.5 * ((pr.get("steel", 0) or 0) + (pr.get("oil", 0) or 0) + (pr.get("rare", 0) or 0))
        sc = val / ((es + 40.0) * tdf * (1 + 0.35 * fort))
        cands.append((sc, T, stg, es, tdf, fort))
    cands.sort(reverse=True)
    for sc, T, stg, es, tdf, fort in cands[:10]:
        # staging: own neighbour with most supplies / supplied
        best = None
        for s in stg:
            ps = api.provs[s]
            k = (1 if ps.get("supplied") else 0, ps.get("stock", 0) or 0)
            if best is None or k > best[0]:
                best = (k, s)
        S = best[1]
        ps = api.provs[S]
        sx, sy = ps.get("x", 0), ps.get("y0", 0)
        need = max(180.0, 2.5 * es * tdf * (1 + 0.25 * fort))
        ranked = []
        for u in pool:
            pu = api.provs.get(u["prov"])
            if not pu:
                continue
            d = (pu.get("x", 0) - sx) ** 2 + (pu.get("y0", 0) - sy) ** 2
            if d > 900:
                continue
            ranked.append((d, u["id"], u))
        ranked.sort()
        took = []
        tot = 0.0
        for d, i, u in ranked:
            if len(took) >= maxtake or tot >= need * 1.4:
                break
            took.append(i)
            tot += u["str"] * (1.6 if u["type"] in ("art", "grn") else 1.0)
        if tot >= need and len(took) >= 3:
            return dict(T=T, S=S, ids=took, phase="gather", t0=api.t)
    return None


def run_op(api, units, byid):
    op = api.mem.get("op")
    if not op:
        return
    op["ids"] = [i for i in op["ids"] if i in byid]
    ids = op["ids"]
    T, S = op["T"], op["S"]
    if len(ids) < 3:
        release(api, op)
        return
    pT = api.provs.get(T, {})
    if pT.get("owner") == "me":
        release(api, op)
        return
    if api.provs.get(S, {}).get("owner") != "me" and op["phase"] != "assault":
        release(api, op)
        return
    us = [byid[i] for i in ids]
    avg = sum(u["str"] for u in us) / len(us)
    if avg < 40:
        release(api, op)
        return
    inf_ids = [u["id"] for u in us if u["type"] not in ("art", "rkt")]
    art_ids = [u["id"] for u in us if u["type"] in ("art", "rkt")]
    js = lambda l: ",".join(str(i) for i in l)
    if op["phase"] == "gather":
        here = [u for u in us if u["prov"] == S and not u["path"]]
        if len(here) >= 0.8 * len(us) or api.t - op["t0"] > 72:
            if inf_ids:
                api.cmd("prepare %s P%d" % (js(inf_ids), T))
            if art_ids:
                api.cmd("hold " + js(art_ids))
            op["phase"] = "prep"
            op["tp"] = api.t
        elif not op.get("sent"):
            api.cmd("move %s P%d" % (js(ids), S))
            op["sent"] = 1
        return
    if op["phase"] == "prep":
        es = estr_of(api, T)
        mine = sum(u["str"] for u in us if u["prov"] == S)
        tdf = TDF.get(pT.get("terrain"), 1.3)
        fort = pT.get("fort", 0) or 0
        pu = [u for u in us if u["type"] not in ("art", "rkt")]
        bonus = (sum(u.get("bonus", 0) or 0 for u in pu) / max(1, len(pu)))
        rdy = sum(u["rdy"] for u in us) / len(us)
        heavy = len(art_ids) / float(len(us))
        p = model_p(api, mine, es, tdf, fort, pT.get("city"), bonus / 100.0, rdy / 100.0, heavy, 1)
        waited = api.t - op["tp"]
        if es > 0 and mine < 1.1 * es * tdf and waited > 24:
            release(api, op)
            return
        if bonus >= 40 or (p >= 0.75 and waited >= 12) or waited >= 54:
            if inf_ids:
                api.cmd("move %s P%d" % (js(inf_ids), T))
            if art_ids:
                api.cmd("hold " + js(art_ids))
            op["phase"] = "assault"
            op["ta"] = api.t
        return
    if op["phase"] == "assault":
        if api.t - op["ta"] > 72:
            release(api, op)


def assign_idle(api, units, opids):
    nb = bool(api.neutral_border)
    exp_n = sum(1 for u in units if u.get("expand"))
    nonrec = sum(1 for u in units if u["type"] != "rec")
    for u in units:
        if u["id"] in opids:
            continue
        if u["front"] or u.get("expand") or u.get("explore") or u["path"]:
            continue
        if u["state"] in ("routing",):
            continue
        if u["type"] == "rec":
            if api.unexplored:
                api.cmd("explore %d" % u["id"])
            continue
        if nb and (exp_n < max(3, int(0.6 * nonrec)) or not api.enemy):
            r = api.cmd("expand %d" % u["id"])
            if r.startswith("ok"):
                exp_n += 1
                continue
        api.cmd("front %d" % u["id"])


def tick(api):
    m = api.mem
    if "op" not in m:
        m["op"] = None
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
        do_recruit(api, units)
    except Exception:
        pass
    try:
        run_op(api, units, byid)
    except Exception:
        m["op"] = None
    try:
        if not m.get("op") and api.t >= m.get("cool", 0) and api.t > 120:
            nonrec = sum(1 for u in units if u["type"] != "rec")
            if nonrec >= 8:
                op = choose_target(api, units, byid)
                if op:
                    m["op"] = op
                    run_op(api, units, byid)
                else:
                    m["cool"] = api.t + 12
    except Exception:
        m["op"] = None
    try:
        opids = set(m["op"]["ids"]) if m.get("op") else set()
        assign_idle(api, units, opids)
    except Exception:
        pass
