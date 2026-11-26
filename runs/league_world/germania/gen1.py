TERR = {'p': 1.0, 'f': 1.25, 'h': 1.5, 'm': 2.0}

def _sig(x):
    if x < -30: return 0.0
    if x > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-x))

def _p_take(api, att, dfs, tprov, bonus, rdy, heavy, dirs):
    m = api.model or {}
    w = m.get("w"); b = m.get("b"); mu = m.get("mean"); sd = m.get("std")
    pr = api.provs.get(tprov, {})
    td = TERR.get(str(pr.get("terrain", "p"))[:1].lower(), 1.0)
    fort = pr.get("fort", 0) or 0
    city = 1.0 if pr.get("city") else 0.0
    lr = math.log((att + 1.0) / (dfs + 1.0))
    if not w or not mu or not sd or len(w) < 8:
        return _sig(1.2 * lr - 0.4 * fort - (td - 1.0) + bonus)
    x = [lr, td, fort, city, bonus, rdy, heavy, dirs]
    z = b
    for i in range(8):
        s = sd[i] if sd[i] else 1.0
        z += w[i] * (x[i] - mu[i]) / s
    return _sig(z)

RESEARCH_ORDER = ["conscription", "logistics", "industry", "mining", "medicine", "farming",
                  "inf.protection", "discipline", "cav.mobility", "staffwork", "art.weapons",
                  "inf.weapons", "drill", "refining", "drilling", "fieldworks",
                  "art.protection", "atg.weapons", "inf.mobility", "cav.protection"]

def _afford(api, cost, reserve=0):
    st = api.stock or {}
    for k, v in (cost or {}).items():
        if k in ("hours", "mp"):
            continue
        have = st.get(k, api.res if k == "res" else 0)
        if have < v + (reserve if k == "res" else 0):
            return False
    return True

def _research(api):
    rs = api.research or []
    if len(rs) >= 2:
        return
    tech = api.tech or {}
    busy = set(r[0] for r in rs)
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
            if str(api.cmd("research " + line)).startswith("ok"):
                busy.add(line)

def _recruit(api, mem, units, armour_seen):
    t = api.t
    inc = (api.income_by or {}).get("res", api.income)
    nrec = sum(1 for u in units if u["type"] == "rec")
    expanding = bool(api.neutral_border) or bool(api.unexplored)
    for _ in range(4):
        if nrec < (6 if t < 1500 else 3):
            typ = "rec"
        elif expanding and t < 900 and mem.get("cavn", 0) < 30:
            typ = "cav"
        else:
            if inc is not None and inc < 0.5 and len(units) > 15:
                return
            k = mem.get("cyc", 0)
            cyc = ["inf", "inf", "art", "inf", "eng", "inf", "grn", "inf", "art", "inf"]
            if armour_seen:
                cyc += ["atg", "atg"]
            typ = cyc[k % len(cyc)]
            mem["cyc"] = k + 1
        c = (api.unit_costs or {}).get(typ) or {"res": 8, "mp": 9}
        reserve = 30 if t > 200 else 5
        mpres = 25 if t > 300 else 5
        if not _afford(api, c, reserve) or api.mp < c.get("mp", 9) + mpres:
            return
        r = api.cmd("recruit %s P%d" % (typ, api.capital))
        if not str(r).startswith("ok"):
            return
        if typ == "rec":
            nrec += 1
        elif typ == "cav":
            mem["cavn"] = mem.get("cavn", 0) + 1

def tick(api):
    mem = api.mem
    t = api.t
    units = api.units or []
    provs = api.provs or {}
    enemy = api.enemy or {}
    ops = mem.setdefault("ops", {})
    in_op = set()
    for op in ops.values():
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
        if isinstance(ty, dict) and (ty.get("arm") or ty.get("hvt") or ty.get("mec")):
            armour_seen = True
            break

    try: _research(api)
    except Exception: pass
    try: _recruit(api, mem, units, armour_seen)
    except Exception: pass

    # capital garrison
    try:
        cap = api.capital
        cp = provs.get(cap, {})
        near = set(cp.get("nbrs", []))
        for n in list(near):
            for n2 in provs.get(n, {}).get("nbrs", []):
                near.add(n2)
        threat = cap in enemy or any(p in near for p in enemy)
        garrison = set(i for i in garrison if i in byid)
        if threat and len(garrison) < 4:
            cands = sorted([u for u in units if u["type"] in ("inf", "grn", "mil", "eng", "atg")
                            and u["id"] not in garrison and u["id"] not in in_op and u["str"] > 50],
                           key=lambda u: 0 if u["prov"] == cap else 1)
            for u in cands[:4 - len(garrison)]:
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

    # far neutral targets (for directed expansion)
    far = mem.get("far", [])
    if t % 24 == 0:
        try:
            cx = provs.get(api.capital, {}).get("x", 0) or 0
            cy = provs.get(api.capital, {}).get("y0", 0) or 0
            ns = []
            for pid, pr in provs.items():
                if pr.get("owner") == "neutral" and not pr.get("harsh"):
                    d = abs((pr.get("x", 0) or 0) - cx) + abs((pr.get("y0", 0) or 0) - cy)
                    ns.append((-(pr.get("y", 0) or 0) - (pr.get("mp", 0) or 0) + 0.02 * d, pid))
            ns.sort()
            far = [p for _, p in ns[:6]]
            mem["far"] = far
        except Exception:
            pass

    # idle units
    try:
        nexp = sum(1 for u in units if u.get("expand"))
        cap_exp = 40 if t < 1200 else 20
        idle_front = []
        k = mem.get("fk", 0)
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
            if api.neutral_border and nexp < cap_exp and u["type"] in ("cav", "inf", "mil", "mot", "mtn"):
                if far and k % 3 == 0:
                    api.cmd("expand %d P%d" % (i, far[(k // 3) % len(far)]))
                else:
                    api.cmd("expand %d" % i)
                k += 1
                nexp += 1
            else:
                idle_front.append(i)
        mem["fk"] = k
        if idle_front:
            api.cmd("front " + ",".join(str(i) for i in idle_front))
    except Exception:
        pass

    # manage ops
    try:
        done = []
        for tg, op in ops.items():
            ids = [i for i in op["u"] if i in byid]
            op["u"] = ids
            pr = provs.get(tg, {})
            if not ids or pr.get("owner") == "me" or t - op["t0"] > 150:
                done.append(tg); continue
            if op["ph"] == "prep":
                n = float(len(ids))
                bon = sum((byid[i].get("bonus", 0) or 0) for i in ids) / n
                rd = sum(byid[i]["rdy"] for i in ids) / 100.0 / n
                age = t - op["t0"]
                if (bon >= 35 and rd >= 0.65) or age >= 96:
                    e = enemy.get(tg)
                    ds = e["str"] if e else 0
                    ast = sum(byid[i]["str"] for i in ids)
                    hv = sum(1 for i in ids if byid[i]["type"] in ("art", "eng", "arm", "hvt")) / n
                    p = _p_take(api, ast, ds, tg, bon / 100.0, rd, hv, 1)
                    if p >= 0.6 and rd >= 0.55 and ast >= 2.5 * ds:
                        api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tg))
                        op["ph"] = "go"; op["t1"] = t
                    elif age >= 96:
                        done.append(tg)
            elif t - op.get("t1", t) > 48:
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

    # new ops
    if t % 6 == 0 and len(ops) < 3:
        try:
            cands = []
            caps = set((api.enemy_capitals or {}).values())
            for a in (api.border or {}):
                pa = provs.get(a)
                if not pa or pa.get("owner") != "me":
                    continue
                mine = [u for u in byprov.get(a, []) if u["type"] != "rec" and u["str"] >= 70
                        and u["id"] not in in_op and u["id"] not in garrison
                        and u["state"] not in ("routing", "shaken")]
                if len(mine) < 2:
                    continue
                for b in pa.get("nbrs", []):
                    pb = provs.get(b)
                    if not pb or pb.get("owner") != "enemy" or b in ops:
                        continue
                    if (pb.get("fort", 0) or 0) >= 2:
                        continue
                    e = enemy.get(b)
                    if e is None and not pb.get("visible"):
                        continue
                    if e is not None and not e.get("exact"):
                        continue
                    ds = e["str"] if e else 0
                    ast = sum(u["str"] for u in mine)
                    if ast < 2.5 * ds + 80:
                        continue
                    rd = sum(u["rdy"] for u in mine) / 100.0 / len(mine)
                    hv = sum(1 for u in mine if u["type"] in ("art", "eng", "arm", "hvt")) / float(len(mine))
                    p = _p_take(api, ast, ds, b, 0.4, max(rd, 0.7), hv, 1)
                    val = (pb.get("y", 0) or 0) + 2 * (pb.get("steel", 0) or 0) + 2 * (pb.get("oil", 0) or 0) \
                        + 3 * (pb.get("rare", 0) or 0) + (5 if pb.get("city") else 0)
                    if b in caps:
                        val += 50
                    cands.append((p + 0.01 * val, p, a, b, mine, ds))
            cands.sort(key=lambda c: -c[0])
            for sc, p, a, b, mine, ds in cands:
                if len(ops) >= 3:
                    break
                if b in ops:
                    continue
                mine = [u for u in mine if u["id"] not in in_op]
                if len(mine) < 2:
                    continue
                keep = 1 if len(mine) > 3 else 0
                use = sorted(mine, key=lambda u: -u["str"])[:len(mine) - keep]
                ids = [u["id"] for u in use]
                sel = ",".join(str(i) for i in ids)
                if ds == 0:
                    api.cmd("move %s P%d" % (sel, b))
                    ops[b] = {"u": ids, "t0": t, "ph": "go", "t1": t}
                elif p >= 0.45:
                    r = api.cmd("prepare %s P%d" % (sel, b))
                    if not str(r).startswith("ok"):
                        continue
                    ops[b] = {"u": ids, "t0": t, "ph": "prep"}
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
