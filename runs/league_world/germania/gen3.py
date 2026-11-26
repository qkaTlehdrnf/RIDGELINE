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

RESEARCH_ORDER = ["conscription", "industry", "art.weapons", "logistics", "staffwork", "farming",
                  "inf.protection", "inf.weapons", "grn.weapons", "medicine", "discipline",
                  "fieldworks", "art.protection", "drill", "atg.weapons", "grn.protection",
                  "refining", "drilling", "cav.mobility", "inf.mobility"]

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
        if _afford(api, cost, 30):
            if str(api.cmd("research " + line)).startswith("ok"):
                busy.add(line)

def _recruit(api, mem, units, armour_seen):
    t = api.t
    inc = (api.income_by or {}).get("res", api.income)
    if inc is None:
        inc = 0
    nrec = sum(1 for u in units if u["type"] == "rec")
    expanding = bool(api.neutral_border) or bool(mem.get("far"))
    for _ in range(4):
        if nrec < (6 if t < 1000 else 3):
            typ = "rec"
        elif expanding and t < 600 and mem.get("cavn", 0) < 40:
            typ = "cav"
        else:
            if inc < 4 and len(units) > 30:
                return
            k = mem.get("cyc", 0)
            cyc = ["art", "inf", "grn", "art", "inf", "eng", "grn", "art", "inf"]
            if armour_seen:
                cyc += ["atg", "atg"]
            typ = cyc[k % len(cyc)]
            mem["cyc"] = k + 1
        c = (api.unit_costs or {}).get(typ) or {"res": 8, "mp": 9}
        reserve = 40 if t > 200 else 5
        mpres = 60 if t > 300 else 5
        if not _afford(api, c, reserve) or api.mp < c.get("mp", 9) + mpres:
            return
        r = api.cmd("recruit %s P%d" % (typ, api.capital))
        if not str(r).startswith("ok"):
            return
        if typ == "rec":
            nrec += 1
        elif typ == "cav":
            mem["cavn"] = mem.get("cavn", 0) + 1

def _diplomacy(api, mem, provs):
    pacts = api.pacts or {}
    met = api.met or []
    on = api.owner_name or {}
    nb = {}
    for a in (api.border or {}):
        for b in provs.get(a, {}).get("nbrs", []):
            f = on.get(b)
            if f and f != api.me:
                nb[f] = nb.get(f, 0)
    for p, e in (api.enemy or {}).items():
        f = on.get(p)
        if f in nb:
            nb[f] += e.get("str", 0) or 0
    target = mem.get("target")
    if api.t % 96 == 0 or target not in nb:
        cands = [(s, f) for f, s in nb.items() if f not in pacts or pacts[f].get("broken_by")]
        if cands:
            cands.sort()
            target = cands[0][1]
            mem["target"] = target
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            if o.get("frm") != target:
                api.cmd("accept %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
        elif o.get("kind") == "trade":
            val = {"res": 1.0, "mp": 0.8, "steel": 0.3, "oil": 0.5, "rare": 2.0}
            tg = sum(val.get(k, 1) * (v or 0) for k, v in (o.get("they_give") or {}).items())
            yg = sum(val.get(k, 1) * (v or 0) for k, v in (o.get("you_give") or {}).items())
            if tg >= 1.1 * yg and _afford(api, o.get("you_give") or {}, 20):
                api.cmd("accept %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
    if api.t % 24 == 0:
        out = set(o.get("to") for o in (api.offers_out or []))
        sent = mem.setdefault("psent", {})
        for f in met:
            if f == target or f in pacts or f in out:
                continue
            if api.t - sent.get(f, -999) < 96:
                continue
            api.cmd("offer %s pact" % f)
            api.cmd("say %s Germania offers lasting peace and trade (steel for res). We have no claims on you." % f)
            sent[f] = api.t
    # sell surplus steel / oil for res
    if api.t % 48 == 12:
        st = api.stock or {}
        partners = [f for f, p in pacts.items() if not p.get("broken_by")]
        out = set(o.get("to") for o in (api.offers_out or []))
        n = 0
        for f in partners:
            if n >= 2 or f in out:
                continue
            if (st.get("steel", 0) or 0) > 250:
                api.cmd("offer %s trade 120 steel for 35 res" % f)
                n += 1
            elif (st.get("oil", 0) or 0) > 250:
                api.cmd("offer %s trade 100 oil for 40 res" % f)
                n += 1
    if api.t > 800 and api.t % 48 == 0 and not api.neutral_border:
        hostile = [f for f in nb if f not in pacts]
        if not hostile and nb:
            w = min(nb.items(), key=lambda kv: kv[1])[0]
            api.cmd("break %s" % w)
            mem["target"] = w

def tick(api):
    mem = api.mem
    t = api.t
    units = api.units or []
    provs = api.provs or {}
    enemy = api.enemy or {}
    pacts = api.pacts or {}
    on = api.owner_name or {}
    ops = mem.setdefault("ops", {})
    in_op = set()
    for op in ops.values():
        for i in op["u"]:
            in_op.add(int(i))
    garrison = set(mem.get("gar", []))
    byid = {}
    for u in units:
        byid[u["id"]] = u

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
    try: _diplomacy(api, mem, provs)
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
        if threat and len(garrison) < 6:
            cands = sorted([u for u in units if u["type"] in ("inf", "grn", "mil", "eng", "atg")
                            and u["id"] not in garrison and u["id"] not in in_op and u["str"] > 50],
                           key=lambda u: 0 if u["prov"] == cap else 1)
            for u in cands[:6 - len(garrison)]:
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

    # far neutral targets
    far = mem.get("far", [])
    if t % 24 == 0:
        try:
            cx = provs.get(api.capital, {}).get("x", 0) or 0
            cy = provs.get(api.capital, {}).get("y0", 0) or 0
            ns = []
            for pid, pr in provs.items():
                if pr.get("owner") == "neutral" and not pr.get("harsh"):
                    d = abs((pr.get("x", 0) or 0) - cx) + abs((pr.get("y0", 0) or 0) - cy)
                    val = (pr.get("y", 0) or 0) + (pr.get("mp", 0) or 0) + 2 * ((pr.get("steel", 0) or 0)
                          + (pr.get("oil", 0) or 0) + (pr.get("rare", 0) or 0)) + (4 if pr.get("city") else 0)
                    ns.append((-val + 0.03 * d, pid))
            ns.sort()
            far = [p for _, p in ns[:10]]
            mem["far"] = far
        except Exception:
            pass

    # idle units
    try:
        nexp = sum(1 for u in units if u.get("expand"))
        if t < 700:
            cap_exp = max(60, int(len(units) * 0.5))
        elif t < 1500:
            cap_exp = 50
        else:
            cap_exp = 25
        can_expand = bool(api.neutral_border) or bool(far)
        idle_front = []
        k = mem.get("fk", 0)
        for u in units:
            i = u["id"]
            if i in in_op or i in garrison:
                continue
            if u.get("explore") or u.get("front") or u.get("expand"):
                continue
            if u["path"] or u["state"] in ("routing", "shaken", "preparing", "assault", "refitting"):
                continue
            if u["type"] == "rec":
                if api.unexplored:
                    api.cmd("explore %d" % i)
                else:
                    idle_front.append(i)
                continue
            if can_expand and nexp < cap_exp and u["type"] in ("cav", "inf", "mil", "mot", "mtn", "grn", "mec"):
                if far and (not api.neutral_border or k % 3 == 0):
                    r = api.cmd("expand %d P%d" % (i, far[(k // 3) % len(far)]))
                    if not str(r).startswith("ok"):
                        api.cmd("expand %d" % i)
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

    ratio_need = 2.5 + 0.5 * min(4, mem.get("fail", 0) - mem.get("win", 0)) if mem.get("fail", 0) > mem.get("win", 0) else 2.5

    # manage ops
    try:
        done = []
        for key, op in ops.items():
            tg = op["b"]
            asg = op["asg"]
            ids = [i for i in op["u"] if i in byid]
            op["u"] = ids
            pr = provs.get(tg, {})
            f = on.get(tg)
            if pr.get("owner") == "me":
                if op["ph"] == "go":
                    mem["win"] = mem.get("win", 0) + 1
                done.append(key); continue
            if not ids or t - op["t0"] > 260 or (f in pacts and not pacts[f].get("broken_by")):
                if op["ph"] == "go":
                    mem["fail"] = mem.get("fail", 0) + 1
                done.append(key); continue
            if op["ph"] == "gather":
                at = [i for i in ids if byid[i]["prov"] == asg.get(str(i)) and not byid[i]["path"]]
                if len(at) >= 0.8 * len(ids) or t - op["t0"] > 90:
                    if len(at) < 4:
                        done.append(key); continue
                    bya = {}
                    for i in at:
                        bya.setdefault(asg[str(i)], []).append(i)
                    ok = []
                    for a, li in bya.items():
                        sel = ",".join(str(i) for i in li)
                        r = api.cmd("prepare %s P%d" % (sel, tg))
                        if str(r).startswith("ok"):
                            ok += li
                    if len(ok) < 4:
                        done.append(key); continue
                    api.cmd("group g%d %s" % (tg, ",".join(str(i) for i in ok)))
                    rest = [i for i in ids if i not in ok]
                    if rest:
                        api.cmd("front " + ",".join(str(i) for i in rest))
                    op["u"] = ok
                    op["ph"] = "prep"; op["t1"] = t
            elif op["ph"] == "prep":
                n = float(len(ids))
                bon = sum((byid[i].get("bonus", 0) or 0) for i in ids) / n
                rd = sum(byid[i]["rdy"] for i in ids) / 100.0 / n
                age = t - op["t1"]
                if (bon >= 35 and rd >= 0.65) or age >= 60:
                    e = enemy.get(tg)
                    ds = e["str"] if e else 0
                    ast = sum(byid[i]["str"] for i in ids)
                    hv = sum(1 for i in ids if byid[i]["type"] in ("art", "eng", "arm", "hvt")) / n
                    dirs = len(set(byid[i]["prov"] for i in ids))
                    p = _p_take(api, ast, ds, tg, bon / 100.0, rd, hv, dirs)
                    if p >= 0.5 and rd >= 0.55 and ast >= ratio_need * ds:
                        api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tg))
                        op["ph"] = "go"; op["t2"] = t
                    elif age >= 110:
                        done.append(key)
            else:
                if t - op.get("t2", t) > 60:
                    mem["fail"] = mem.get("fail", 0) + 1
                    done.append(key)
                else:
                    avg = sum(byid[i]["str"] for i in ids) / float(len(ids))
                    if avg < 35:
                        mem["fail"] = mem.get("fail", 0) + 1
                        done.append(key)
        for key in done:
            ids = [i for i in ops[key]["u"] if i in byid]
            if ids:
                api.cmd("front " + ",".join(str(i) for i in ids))
            del ops[key]
            for i in ids:
                in_op.discard(i)
    except Exception:
        pass

    # new ops
    maxops = 2 if t < 500 else (3 if t < 1500 else 4)
    if t % 12 == 0 and t >= 24 and len(ops) < maxops:
        try:
            caps = set((api.enemy_capitals or {}).values())
            target = mem.get("target")
            tb = set(op["b"] for op in ops.values())
            seen = {}
            for a in (api.border or {}):
                pa = provs.get(a)
                if not pa or pa.get("owner") != "me" or not pa.get("supplied", True):
                    continue
                for b in pa.get("nbrs", []):
                    if b in tb:
                        continue
                    pb = provs.get(b)
                    if not pb or pb.get("owner") != "enemy":
                        continue
                    seen.setdefault(b, []).append(a)
            cands = []
            for b, srcs in seen.items():
                pb = provs[b]
                f = on.get(b)
                if f in pacts and not pacts[f].get("broken_by"):
                    continue
                if (pb.get("fort", 0) or 0) >= 2 or pb.get("harsh"):
                    continue
                e = enemy.get(b)
                if e is None and not pb.get("visible"):
                    continue
                if e is not None and not e.get("exact"):
                    continue
                ds = e["str"] if e else 0
                td = TERR.get(str(pb.get("terrain", "p"))[:1].lower(), 1.0)
                val = (pb.get("y", 0) or 0) + 2 * (pb.get("steel", 0) or 0) + 2 * (pb.get("oil", 0) or 0) \
                    + 3 * (pb.get("rare", 0) or 0) + (4 if pb.get("city") else 0)
                if b in caps:
                    val += 60
                if f == target:
                    val += 6
                sc = val - ds / 50.0 - 4 * (td - 1.0) - 3 * (pb.get("fort", 0) or 0) + 1.5 * min(3, len(srcs))
                cands.append((-sc, b, srcs, ds))
            cands.sort(key=lambda z: z[0])
            pool = [u for u in units if u.get("front") and not u.get("expand") and u["type"] not in ("rec", "mil")
                    and u["str"] >= 75 and u["rdy"] >= 55 and u["id"] not in in_op and u["id"] not in garrison
                    and u["state"] not in ("routing", "shaken", "refitting") and not u.get("fighting")]
            for _, b, srcs, ds in cands[:8]:
                if len(ops) >= maxops:
                    break
                srcs = srcs[:3]
                pts = [(a, provs[a].get("x", 0) or 0, provs[a].get("y0", 0) or 0) for a in srcs]
                near = []
                for u in pool:
                    if u["id"] in in_op:
                        continue
                    pu = provs.get(u["prov"], {})
                    ux = pu.get("x", 0) or 0; uy = pu.get("y0", 0) or 0
                    best = None
                    for a, ax, ay in pts:
                        d = math.hypot(ux - ax, uy - ay)
                        if best is None or d < best[0]:
                            best = (d, a)
                    if best[0] <= 30:
                        near.append((best[0], best[1], u))
                near.sort(key=lambda z: z[0])
                need = max(ratio_need * ds * 1.2 + 150, 450)
                pick = []; s = 0
                for d, a, u in near:
                    if s >= need or len(pick) >= 28:
                        break
                    pick.append((a, u)); s += u["str"]
                if s < need or len(pick) < 4:
                    continue
                hv = sum(1 for a, u in pick if u["type"] in ("art", "eng", "arm", "hvt")) / float(len(pick))
                dirs = len(set(a for a, u in pick))
                p = _p_take(api, s, ds, b, 0.4, 0.75, hv, dirs)
                if p < 0.5:
                    continue
                bya = {}
                for a, u in pick:
                    bya.setdefault(a, []).append(u["id"])
                asg = {}
                for a, li in bya.items():
                    api.cmd("move %s P%d" % (",".join(str(i) for i in li), a))
                    for i in li:
                        asg[str(i)] = a
                ids = [u["id"] for a, u in pick]
                ops[str(b)] = {"u": ids, "asg": asg, "b": b, "t0": t, "ph": "gather"}
                for i in ids:
                    in_op.add(i)
                for u in units:
                    if u["type"] == "rec" and u["id"] not in in_op and not u.get("fighting"):
                        a0 = srcs[0]
                        api.cmd("move %d P%d" % (u["id"], a0))
                        in_op.add(u["id"])
                        ops[str(b)]["u"].append(u["id"])
                        ops[str(b)]["asg"][str(u["id"])] = a0
                        break
        except Exception:
            pass
