Last war I finished 27th of 30 and stayed at about 32 provinces from day 5 to the end. Three things went wrong:

1. **Slow land grab.** Only 40 units ever had the expand order, while neighbours grabbed Europe in the first days. Most of my army now expands until about hour 700.
2. **Every assault failed (0 of 181).** They went in at low readiness, with no prepared-attack bonus, often into level-3 forts I had not seen.
   - Attacks now first gather a strike group at a staging province, add a scout, then wait for the bonus and readiness.
   - Targets must be visible, have a low known fort level, and pass the model's odds plus a strength margin.
3. **Economy ran down.** Upkeep ate income and manpower hit zero. Recruiting now stops when net res income or manpower runs low. Score is decided by territory yield first, so land matters more than army size.

On diplomacy, I offer pacts to all factions I meet except one war target and accept their pacts. The target is the met faction whose land touches mine and whose seen force is weakest. Late in the war, if no neutral land is left and every neighbour is under a pact, I break one pact to reopen a war.

```python
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

RESEARCH_ORDER = ["farming", "conscription", "logistics", "industry", "staffwork", "mining",
                  "medicine", "inf.protection", "inf.weapons", "discipline", "art.weapons",
                  "drill", "cav.mobility", "refining", "drilling", "grn.weapons",
                  "fieldworks", "art.protection", "atg.weapons", "inf.mobility"]

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
    if inc is None:
        inc = 0
    nrec = sum(1 for u in units if u["type"] == "rec")
    expanding = bool(api.neutral_border)
    for _ in range(4):
        if nrec < (8 if t < 1000 else 3):
            typ = "rec"
        elif expanding and t < 900 and mem.get("cavn", 0) < 60:
            typ = "cav"
        else:
            if inc < 4 and len(units) > 20:
                return
            k = mem.get("cyc", 0)
            cyc = ["inf", "grn", "art", "inf", "eng", "inf", "grn", "art", "inf", "inf"]
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
    # neighbours: factions owning land next to mine, and their seen strength
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
    if t_ok(api, mem) or target not in nb:
        cands = [(s, f) for f, s in nb.items() if f not in pacts or pacts[f].get("broken_by")]
        if cands:
            cands.sort()
            target = cands[0][1]
            mem["target"] = target
    for o in (api.offers_in or []):
        if o.get("kind") == "pact" and o.get("frm") != target:
            api.cmd("accept %s" % o["id"])
        elif o.get("kind") == "pact":
            api.cmd("reject %s" % o["id"])
        elif o.get("kind") == "trade":
            tg = sum((v or 0) for v in (o.get("they_give") or {}).values())
            yg = sum((v or 0) for v in (o.get("you_give") or {}).values())
            if tg >= 1.2 * yg and _afford(api, o.get("you_give") or {}, 20):
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
            api.cmd("say %s Germania offers lasting peace. We have no claims on you; let us both grow elsewhere." % f)
            sent[f] = api.t
    # late: if boxed in by pacts, break with weakest neighbour
    if api.t > 1000 and api.t % 48 == 0 and not api.neutral_border:
        hostile = [f for f in nb if f not in pacts]
        if not hostile and nb:
            w = min(nb.items(), key=lambda kv: kv[1])[0]
            api.cmd("break %s" % w)
            mem["target"] = w

def t_ok(api, mem):
    return api.t % 96 == 0

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
                    val = (pr.get("y", 0) or 0) + (pr.get("mp", 0) or 0) + 2 * ((pr.get("steel", 0) or 0)
                          + (pr.get("oil", 0) or 0) + (pr.get("rare", 0) or 0)) + (4 if pr.get("city") else 0)
                    ns.append((-val + 0.02 * d, pid))
            ns.sort()
            far = [p for _, p in ns[:8]]
            mem["far"] = far
        except Exception:
            pass

    # idle units
    try:
        nexp = sum(1 for u in units if u.get("expand"))
        if t < 700:
            cap_exp = max(60, int(len(units) * 0.6))
        elif t < 1500:
            cap_exp = 60
        else:
            cap_exp = 25
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
            if api.neutral_border and nexp < cap_exp and u["type"] in ("cav", "inf", "mil", "mot", "mtn", "grn", "mec"):
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
        for key, op in ops.items():
            tg = op["b"]
            ids = [i for i in op["u"] if i in byid]
            op["u"] = ids
            pr = provs.get(tg, {})
            f = on.get(tg)
            if not ids or pr.get("owner") == "me" or t - op["t0"] > 240 or (f in pacts and not pacts[f].get("broken_by")):
                done.append(key); continue
            a = op["a"]
            if op["ph"] == "gather":
                at = [i for i in ids if byid[i]["prov"] == a and not byid[i]["path"]]
                if len(at) >= 0.75 * len(ids) or t - op["t0"] > 96:
                    if len(at) < 3:
                        done.append(key); continue
                    sel = ",".join(str(i) for i in at)
                    r = api.cmd("prepare %s P%d" % (sel, tg))
                    if not str(r).startswith("ok"):
                        done.append(key); continue
                    api.cmd("group g%d %s" % (tg, sel))
                    rest = [i for i in ids if i not in at]
                    if rest:
                        api.cmd("front " + ",".join(str(i) for i in rest))
                    op["u"] = at
                    op["ph"] = "prep"; op["t1"] = t
            elif op["ph"] == "prep":
                n = float(len(ids))
                bon = sum((byid[i].get("bonus", 0) or 0) for i in ids) / n
                rd = sum(byid[i]["rdy"] for i in ids) / 100.0 / n
                age = t - op["t1"]
                if (bon >= 40 and rd >= 0.65) or age >= 72:
                    e = enemy.get(tg)
                    ds = e["str"] if e else 0
                    ast = sum(byid[i]["str"] for i in ids)
                    hv = sum(1 for i in ids if byid[i]["type"] in ("art", "eng", "arm", "hvt")) / n
                    p = _p_take(api, ast, ds, tg, bon / 100.0, rd, hv, 1)
                    if p >= 0.55 and rd >= 0.5 and ast >= 2.5 * ds:
                        api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tg))
                        op["ph"] = "go"; op["t2"] = t
                    elif age >= 110:
                        done.append(key)
            else:
                if t - op.get("t2", t) > 48:
                    done.append(key)
                else:
                    # if beaten down, pull out
                    avg = sum(byid[i]["str"] for i in ids) / float(len(ids))
                    if avg < 35:
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
    maxops = 1 if t < 500 else (3 if t < 1500 else 4)
    if t % 12 == 0 and len(ops) < maxops:
        try:
            cands = []
            caps = set((api.enemy_capitals or {}).values())
            target = mem.get("target")
            tb = set(op["b"] for op in ops.values())
            for a in (api.border or {}):
                pa = provs.get(a)
                if not pa or pa.get("owner") != "me" or not pa.get("supplied", True):
                    continue
                for b in pa.get("nbrs", []):
                    pb = provs.get(b)
                    if not pb or pb.get("owner") != "enemy" or b in tb:
                        continue
                    f = on.get(b)
                    if f in pacts and not pacts[f].get("broken_by"):
                        continue
                    if (pb.get("fort", 0) or 0) >= 2:
                        continue
                    if pb.get("harsh"):
                        continue
                    e = enemy.get(b)
                    if e is None and not pb.get("visible"):
                        continue
                    if e is not None and not e.get("exact"):
                        continue
                    ds = e["str"] if e else 0
                    td = TERR.get(str(pb.get("terrain", "p"))[:1].lower(), 1.0)
                    val = (pb.get("y", 0) or 0) + 2 * (pb.get("steel", 0) or 0) + 2 * (pb.get("oil", 0) or 0) \
                        + 3 * (pb.get("rare", 0) or 0) + (5 if pb.get("city") else 0)
                    if b in caps:
                        val += 60
                    if f == target:
                        val += 5
                    sc = val - ds / 60.0 - 3 * (td - 1.0) - 2 * (pb.get("fort", 0) or 0)
                    cands.append((-sc, a, b, ds))
            cands.sort()
            pool = [u for u in units if u.get("front") and not u.get("expand") and u["type"] not in ("rec", "mil")
                    and u["str"] >= 80 and u["rdy"] >= 50 and u["id"] not in in_op and u["id"] not in garrison
                    and u["state"] not in ("routing", "shaken", "refitting") and not u.get("fighting")]
            for _, a, b, ds in cands[:12]:
                if len(ops) >= maxops:
                    break
                pa = provs.get(a, {})
                ax = pa.get("x", 0) or 0; ay = pa.get("y0", 0) or 0
                near = []
                for u in pool:
                    if u["id"] in in_op:
                        continue
                    pu = provs.get(u["prov"], {})
                    d = math.hypot((pu.get("x", 0) or 0) - ax, (pu.get("y0", 0) or 0) - ay)
                    if d <= 35:
                        near.append((d, u))
                near.sort(key=lambda z: z[0])
                need = max(3.0 * ds + 150, 500)
                pick = []; s = 0
                for d, u in near:
                    if s >= need or len(pick) >= 24:
                        break
                    pick.append(u); s += u["str"]
                if s < need or len(pick) < 4:
                    continue
                hv = sum(1 for u in pick if u["type"] in ("art", "eng", "arm", "hvt")) / float(len(pick))
                p = _p_take(api, s, ds, b, 0.5, 0.8, hv, 1)
                if p < 0.55:
                    continue
                ids = [u["id"] for u in pick]
                api.cmd("move %s P%d" % (",".join(str(i) for i in ids), a))
                ops[str(b)] = {"u": ids, "a": a, "b": b, "t0": t, "ph": "gather"}
                for i in ids:
                    in_op.add(i)
                for u in units:
                    if u["type"] == "rec" and u["id"] not in in_op and not u.get("fighting"):
                        api.cmd("move %d P%d" % (u["id"], a))
                        in_op.add(u["id"])
                        ops[str(b)]["u"].append(u["id"])
                        break
        except Exception:
            pass
```

```letters
to gallia: Germania proposes a lasting non-aggression pact from hour 0. Neither of us gained by fighting last war; let us both grow elsewhere. I will offer it in-game; please accept.
to scandia: Germania proposes a lasting non-aggression pact from hour 0. Our border is better quiet. I will offer it in-game; please accept.
to sarmatia: Germania proposes a lasting non-aggression pact. Fighting each other only fed the giants. I will offer it in-game; please accept.
to iberia: Germania proposes peace for the whole war; we have no claims on you. I will offer a pact in-game.
to anatolia: Germania proposes peace for the whole war; we have no claims on you. I will offer a pact in-game.
```