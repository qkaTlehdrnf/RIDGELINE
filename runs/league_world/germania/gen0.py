TERR = {'p': 1.0, 'f': 1.25, 'h': 1.5, 'm': 2.0}

def _sig(x):
    if x < -30: return 0.0
    if x > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-x))

def _p_take(api, att_str, def_str, tprov, bonus, rdy, heavy, dirs):
    m = api.model or {}
    w = m.get("w"); b = m.get("b"); mu = m.get("mean"); sd = m.get("std")
    pr = api.provs.get(tprov, {})
    td = TERR.get(str(pr.get("terrain", "p"))[:1].lower(), 1.0)
    fort = pr.get("fort", 0) or 0
    city = 1.0 if pr.get("city") else 0.0
    lr = math.log((att_str + 1.0) / (def_str + 1.0))
    if not w or not mu or not sd or len(w) < 8:
        return _sig(1.2 * lr - 0.4 * fort - (td - 1.0) + bonus)
    x = [lr, td, fort, city, bonus, rdy, heavy, dirs]
    z = b
    for i in range(8):
        s = sd[i] if sd[i] else 1.0
        z += w[i] * (x[i] - mu[i]) / s
    return _sig(z)

RESEARCH_ORDER = ["farming", "conscription", "industry", "inf.weapons", "logistics",
                  "inf.protection", "art.weapons", "medicine", "discipline", "mining",
                  "staffwork", "drill", "fieldworks", "art.protection", "atg.weapons",
                  "inf.mobility", "drilling", "refining", "eng.protection"]

def _afford(api, cost, reserve=0):
    st = api.stock or {}
    for k, v in (cost or {}).items():
        if k in ("hours", "mp"):
            continue
        have = st.get(k, api.res if k == "res" else 0)
        need = v + (reserve if k == "res" else 0)
        if have < need:
            return False
    return True

def _research(api):
    if len(api.research or []) >= 2:
        return
    tech = api.tech or {}
    busy = set(r[0] for r in (api.research or []))
    for line in RESEARCH_ORDER:
        if len(busy) >= 2:
            break
        info = tech.get(line)
        if not info or line in busy or info.get("status") != "open":
            continue
        cost = info.get("cost")
        if cost is None:
            continue
        if _afford(api, cost, 40):
            r = api.cmd("research " + line)
            if str(r).startswith("ok"):
                busy.add(line)

def _recruit(api, mem, nunits, armour_seen):
    t = api.t
    inc = (api.income_by or {}).get("res", api.income)
    ntype = mem.setdefault("built", {})
    tries = 0
    while tries < 3:
        tries += 1
        if ntype.get("rec", 0) < 2:
            typ = "rec"
        elif t < 400 and api.neutral_border and ntype.get("cav", 0) < 6:
            typ = "cav"
        else:
            if inc is not None and inc < 1.0 and nunits > 12:
                return
            k = mem.get("cyc", 0)
            cyc = ["inf", "inf", "art", "inf", "grn", "inf", "eng", "inf", "art", "inf"]
            if armour_seen:
                cyc += ["atg", "atg"]
            typ = cyc[k % len(cyc)]
            mem["cyc"] = k + 1
        c = (api.unit_costs or {}).get(typ)
        if not c:
            typ = "inf"; c = (api.unit_costs or {}).get("inf", {"res": 8, "mp": 9})
        reserve = 30 if t > 200 else 5
        if not _afford(api, c, reserve) or api.mp < c.get("mp", 9) + 5:
            if typ != "inf":
                c = (api.unit_costs or {}).get("inf", {"res": 8, "mp": 9})
                if _afford(api, c, reserve) and api.mp >= c.get("mp", 9) + 5:
                    typ = "inf"
                else:
                    return
            else:
                return
        r = api.cmd("recruit %s P%d" % (typ, api.capital))
        if not str(r).startswith("ok"):
            return
        ntype[typ] = ntype.get(typ, 0) + 1

def tick(api):
    mem = api.mem
    t = api.t
    units = api.units or []
    provs = api.provs or {}
    enemy = api.enemy or {}
    ops = mem.setdefault("ops", {})
    in_op = set()
    for tg, op in ops.items():
        for i in op["u"]:
            in_op.add(i)
    garrison = set(mem.get("gar", []))
    byid = {}
    byprov = {}
    for u in units:
        byid[u["id"]] = u
        byprov.setdefault(u["prov"], []).append(u)

    armour_seen = False
    for e in enemy.values():
        ty = e.get("types") or {}
        if isinstance(ty, dict):
            if ty.get("arm") or ty.get("hvt") or ty.get("mec"):
                armour_seen = True
                break

    try:
        _research(api)
    except Exception:
        pass
    try:
        _recruit(api, mem, len(units), armour_seen)
    except Exception:
        pass

    # --- capital garrison when threatened
    try:
        cap = api.capital
        threat = False
        cp = provs.get(cap, {})
        near = set(cp.get("nbrs", []))
        for n in list(near):
            for n2 in provs.get(n, {}).get("nbrs", []):
                near.add(n2)
        for p in enemy:
            if p in near or p == cap:
                threat = True
                break
        garrison = set(i for i in garrison if i in byid)
        if threat and len(garrison) < 3:
            cands = sorted([u for u in units if u["type"] in ("inf", "grn", "mil", "eng", "atg")
                            and u["id"] not in garrison and u["id"] not in in_op and u["str"] > 50],
                           key=lambda u: 0 if u["prov"] == cap else 1)
            for u in cands[:3 - len(garrison)]:
                if u["prov"] == cap:
                    api.cmd("fortify %d" % u["id"])
                else:
                    api.cmd("move %d P%d" % (u["id"], cap))
                garrison.add(u["id"])
        elif not threat and garrison and t % 48 == 0:
            api.cmd("front " + ",".join(str(i) for i in garrison))
            garrison = set()
        else:
            for i in garrison:
                u = byid[i]
                if u["prov"] == cap and not u["path"] and u["state"] == "ready":
                    api.cmd("fortify %d" % i)
        mem["gar"] = list(garrison)
    except Exception:
        pass

    # --- assign idle units
    try:
        nexp = sum(1 for u in units if u.get("expand"))
        idle_front = []
        for u in units:
            i = u["id"]
            if i in in_op or i in garrison:
                continue
            if u.get("explore") or u.get("front") or u.get("expand"):
                continue
            if u["path"] or u["state"] in ("routing", "shaken", "preparing", "assault"):
                continue
            if u["type"] == "rec":
                if api.unexplored:
                    api.cmd("explore %d" % i)
                else:
                    idle_front.append(i)
                continue
            if api.neutral_border and nexp < 10 and u["type"] in ("cav", "inf", "mil", "mot", "mtn"):
                api.cmd("expand %d" % i)
                nexp += 1
            else:
                idle_front.append(i)
        if idle_front:
            api.cmd("front " + ",".join(str(i) for i in idle_front))
    except Exception:
        pass

    # --- manage operations
    try:
        done = []
        for tg, op in ops.items():
            ids = [i for i in op["u"] if i in byid]
            op["u"] = ids
            pr = provs.get(tg, {})
            if not ids or pr.get("owner") == "me" or t - op["t0"] > 120:
                done.append(tg); continue
            if op["ph"] == "prep":
                bon = 0.0
                for i in ids:
                    bon += byid[i].get("bonus", 0) or 0
                bon /= len(ids)
                age = t - op["t0"]
                if bon >= 35 or age >= 48:
                    e = enemy.get(tg)
                    ds = e["str"] if e else 0
                    ast = sum(byid[i]["str"] for i in ids)
                    rd = sum(byid[i]["rdy"] for i in ids) / 100.0 / len(ids)
                    hv = sum(1 for i in ids if byid[i]["type"] in ("art", "eng", "arm", "hvt")) / float(len(ids))
                    p = _p_take(api, ast, ds, tg, bon / 100.0, rd, hv, 1)
                    if p >= 0.55:
                        api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tg))
                        op["ph"] = "go"; op["t1"] = t
                    elif age >= 72:
                        done.append(tg)
            else:
                if t - op.get("t1", t) > 48:
                    done.append(tg)
        for tg in done:
            ids = [i for i in ops[tg]["u"] if i in byid]
            if ids:
                api.cmd("front " + ",".join(str(i) for i in ids))
            del ops[tg]
            for i in ids:
                in_op.discard(i)
    except Exception:
        pass

    # --- start new operations
    if t % 6 == 0 and len(ops) < 3:
        try:
            cands = []
            for a in (api.border or {}):
                pa = provs.get(a)
                if not pa or pa.get("owner") != "me":
                    continue
                for b in pa.get("nbrs", []):
                    pb = provs.get(b)
                    if not pb or pb.get("owner") != "enemy" or b in ops:
                        continue
                    e = enemy.get(b)
                    if e is None and not pb.get("visible"):
                        continue
                    ds = e["str"] if e else 0
                    mine = [u for u in byprov.get(a, []) if u["type"] != "rec" and u["str"] >= 60
                            and u["id"] not in in_op and u["id"] not in garrison
                            and u["state"] not in ("routing", "shaken")]
                    if not mine:
                        continue
                    ast = sum(u["str"] for u in mine)
                    if ast < 1.6 * ds + 60:
                        continue
                    rd = sum(u["rdy"] for u in mine) / 100.0 / len(mine)
                    hv = sum(1 for u in mine if u["type"] in ("art", "eng", "arm", "hvt")) / float(len(mine))
                    p = _p_take(api, ast, ds, b, 0.4, rd, hv, 1)
                    val = (pb.get("y", 0) or 0) + 2 * (pb.get("steel", 0) or 0) + 2 * (pb.get("oil", 0) or 0) + 3 * (pb.get("rare", 0) or 0) + (5 if pb.get("city") else 0)
                    if b in (api.enemy_capitals or {}).values():
                        val += 50
                    cands.append((p + 0.01 * val, p, a, b, mine, ds))
            cands.sort(key=lambda c: -c[0])
            for sc, p, a, b, mine, ds in cands:
                if len(ops) >= 3:
                    break
                if b in ops:
                    continue
                mine = [u for u in mine if u["id"] not in in_op]
                if not mine:
                    continue
                # keep at least one unit behind if the province has others
                keep = 1 if len(mine) > 2 else 0
                use = sorted(mine, key=lambda u: -u["str"])[:max(1, len(mine) - keep)]
                ids = [u["id"] for u in use]
                sel = ",".join(str(i) for i in ids)
                if ds == 0:
                    api.cmd("move %s P%d" % (sel, b))
                    ops[b] = {"u": ids, "t0": t, "ph": "go", "t1": t}
                elif p >= 0.35:
                    r = api.cmd("prepare %s P%d" % (sel, b))
                    if str(r).startswith("ok"):
                        ops[b] = {"u": ids, "t0": t, "ph": "prep"}
                        # bring a scout next to target for bigger bonus
                        for u in units:
                            if u["type"] == "rec" and u["id"] not in in_op and not u["path"]:
                                api.cmd("move %d P%d" % (u["id"], a))
                                in_op.add(u["id"])
                                break
                    else:
                        continue
                for i in ids:
                    in_op.add(i)
        except Exception:
            pass
