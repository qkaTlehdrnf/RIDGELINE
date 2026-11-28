The last war's policy put Germania 3rd with 456 provinces, so I keep its structure and make three small fixes:

- **Group names.** The 715 rejected `group` commands came from names like `g1234`. Names now use letters only, so attack formations can build formation experience.
- **Recruitment and upkeep.** Upkeep took about 90% of everything earned, and net income ended negative. Recruiting now slows when upkeep passes 92% of income. Recruiting stops entirely when the army is already large and the purse is under 400.
- **Development.** With fewer res lost to upkeep, more goes to development. Develop and build orders are also allowed with a smaller reserve once income is healthy.

Everything else stays as it was: research order, assault operations with prepared attacks, the model-based launch decision, expansion, pacts with everyone except the current target, and the capital garrison.

```python
TERR = {'p': 1.0, 'f': 1.25, 'h': 1.5, 'm': 2.0}
ARTT = ("art", "rkt")
ASLT = ("inf", "grn", "eng", "mec", "arm", "hvt", "mtn", "mot", "cav")

def _sig(x):
    if x < -30: return 0.0
    if x > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-x))

def _td(pr):
    return TERR.get(str(pr.get("terrain", "p"))[:1].lower(), 1.0)

def _bon(u):
    b = u.get("bonus", 0) or 0
    if 0 < b <= 0.76:
        b = b * 100.0
    return b

def _gname(tg):
    return "op" + "".join(chr(97 + int(c)) for c in str(int(tg)))

def _pwin(api, ast, ds, pr, bon, rd, heavy, dirs):
    m = api.model or {}
    w = m.get("w"); mu = m.get("mean"); sd = m.get("std")
    lr = math.log((ast + 1.0) / (ds + 1.0))
    if not w or not mu or not sd or len(w) < 8:
        return _sig(1.2 * lr + 0.8 * (rd - 0.6) + 0.8 * bon / 100.0 - 0.35 * (pr.get("fort", 0) or 0))
    x = [lr, _td(pr), pr.get("fort", 0) or 0, 1.0 if pr.get("city") else 0.0, bon / 100.0, rd, heavy, dirs]
    z = m.get("b", 0)
    for k in range(8):
        z += w[k] * (x[k] - mu[k]) / (sd[k] or 1.0)
    return _sig(z)

DISC = ["iron_working", "siege_engines", "masonry", "roads", "horse_riding", "crop_rotation",
        "pikes_crossbows", "trebuchet", "stirrup", "castles", "banking", "gunpowder", "matchlock",
        "steam_power", "rifling", "railways", "steel_guns", "grenadiers", "field_engineering",
        "dragoons", "combustion", "machine_guns", "heavy_artillery", "anti_tank_guns", "tanks",
        "hillmen", "assault_rifles", "mechanisation", "rocket_artillery", "flight", "heavy_armour",
        "composite_armour", "jet_engines", "bombers", "rocketry", "satellites", "ballistic_missiles",
        "guided_weapons"]

RESEARCH_ORDER = ["industry", "farming", "staffwork", "inf.weapons", "logistics", "art.weapons",
                  "conscription", "mining", "inf.protection", "medicine", "discipline", "drill",
                  "art.protection", "grn.weapons", "arm.weapons", "atg.weapons", "refining", "drilling",
                  "inf.mobility"]

def _afford(api, cost, reserve=0):
    st = api.stock or {}
    if not isinstance(cost, dict):
        return api.res >= (cost or 0) + reserve
    for k, v in cost.items():
        if k in ("hours", "mp"):
            continue
        have = api.res if k == "res" else st.get(k, 0)
        if (have or 0) < (v or 0) + (reserve if k == "res" else 0):
            return False
    return True

def _research(api):
    rs = api.research or []
    if len(rs) >= 2:
        return
    busy = set(r[0] for r in rs)
    tree = api.tree or {}
    reserve = 60 if api.t < 300 else 120
    for d in DISC:
        if len(busy) >= 2:
            return
        info = tree.get(d)
        if not info or d in busy or info.get("status") != "open":
            continue
        need = info.get("res_now")
        if need is None:
            c = info.get("cost") or {}
            need = c.get("res", 9999) if isinstance(c, dict) else 9999
        if api.res >= (need or 0) + reserve:
            if str(api.cmd("research " + d)).startswith("ok"):
                busy.add(d); api.count("disc_" + d[:12])
        break
    if len(busy) >= 2:
        return
    tech = api.tech or {}
    for line in RESEARCH_ORDER:
        if len(busy) >= 2:
            break
        info = tech.get(line)
        if not info or line in busy or info.get("status") != "open":
            continue
        cost = info.get("cost")
        if cost is None:
            continue
        if _afford(api, cost, reserve + 150):
            if str(api.cmd("research " + line)).startswith("ok"):
                busy.add(line)
            break

def _economy(api, mem, provs):
    t = api.t
    if t < 36 or t % 24 != 12:
        return
    eco = api.economy or {}
    works = eco.get("works") or []
    if len(works) >= 4:
        return
    busy = set(w[1] for w in works if len(w) > 1)
    border = set((api.border or {}).keys())
    st = api.stock or {}
    inc = (api.income_by or {}).get("res", api.income) or 0
    if inc < 3:
        return
    res_reserve = 150 if inc < 60 else 100
    cands = []
    for p in (eco.get("provs") or []):
        pid = p.get("prov")
        if pid in busy or pid in border:
            continue
        pr = provs.get(pid, {})
        if pr and not pr.get("supplied", True):
            continue
        base = p.get("base", 0) or 0
        dev = p.get("dev", 0) or 0
        sc = base * (1.3 if p.get("city") else 1.0) * (p.get("agg", 1) or 1) - 0.4 * dev
        cands.append((-sc, pid, p))
    cands.sort(key=lambda z: z[0])
    n = 0
    for _, pid, p in cands[:14]:
        if n >= 4 - len(works):
            break
        dev = p.get("dev", 0) or 0
        room = p.get("room", 0) or 0
        if p.get("can_dev") and dev + 1 <= room and dev < 5:
            c = p.get("dev_cost") or {"res": 50 * (dev + 1), "coal": 8 * (dev + 1)}
            if _afford(api, c, res_reserve):
                if str(api.cmd("develop P%d" % pid)).startswith("ok"):
                    api.count("develop"); n += 1
                    continue
        if dev + 1 > room and p.get("can_infra") and (p.get("infra", 0) or 0) < 3 and (st.get("steel", 0) or 0) > 30:
            c = p.get("infra_cost") or {"res": 30, "steel": 6}
            if _afford(api, c, res_reserve + 10):
                if str(api.cmd("build P%d" % pid)).startswith("ok"):
                    api.count("build"); n += 1

def _depots(api, mem, provs):
    t = api.t
    if t < 48 or t % 48 != 18:
        return
    deps = api.depots or {}
    if len(deps) >= 3 or api.res < 300:
        return
    over = False
    for d, info in deps.items():
        cap = info.get("capacity", 30) or 30
        if (info.get("load", 0) or 0) > 0.8 * cap:
            over = True
    if not over:
        return
    border = set((api.border or {}).keys())
    dpts = [(provs.get(d, {}).get("x", 0) or 0, provs.get(d, {}).get("y0", 0) or 0) for d in deps]
    best = None
    for pid, pr in provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied") or pid in border or pid in deps:
            continue
        if pr.get("harsh"):
            continue
        if any(n in border for n in pr.get("nbrs", [])):
            continue
        x = pr.get("x", 0) or 0; y = pr.get("y0", 0) or 0
        dm = min(math.hypot(x - a, y - b) for a, b in dpts) if dpts else 0
        if dm < 15:
            continue
        sc = dm + (25 if pr.get("city") else 0)
        if best is None or sc > best[0]:
            best = (sc, pid)
    if best:
        if str(api.cmd("depot P%d" % best[1])).startswith("ok"):
            api.count("depot_open")

def _recruit(api, mem, units, armour_seen):
    t = api.t
    can = set(api.can_raise or ["inf", "mil", "rec"])
    bud = api.budget or {}
    net = bud.get("net", api.income) or 0
    dl = bud.get("days_left")
    if net < 0 and dl is not None and dl < 15:
        api.count("rec_pause_budget")
        return
    share = bud.get("upkeep_share") or 0
    if t > 2000 and share > 0.92 and len(units) > 300:
        if api.res < 400 or t % 24 != 0:
            api.count("rec_pause_upkeep")
            return
    nrec = sum(1 for u in units if u["type"] == "rec")
    reserve = 70 if t > 200 else 5
    if api.res > 600:
        reserve = 150
    n = 8 if api.res > 500 else 5
    for _ in range(n):
        if nrec < (8 if t < 600 else 5):
            typ = "rec"
        else:
            if net < 1 and len(units) > 40:
                return
            k = mem.get("cyc", 0)
            cyc = ["art", "inf", "grn", "inf", "art", "cav", "eng", "inf", "arm", "inf", "mec"]
            if armour_seen:
                cyc += ["atg", "atg"]
            mem["cyc"] = k + 1
            typ = cyc[k % len(cyc)]
            if typ == "art" and "rkt" in can and k % 2 == 0:
                typ = "rkt"
            if typ not in can:
                typ = "inf"
        c = (api.unit_costs or {}).get(typ) or {"res": 8, "mp": 9}
        mpres = 60 if t > 300 else 5
        if not _afford(api, c, reserve) or api.mp < (c.get("mp", 9) or 0) + mpres:
            typ = "inf"
            c = (api.unit_costs or {}).get(typ) or {"res": 8, "mp": 9}
            if not _afford(api, c, reserve) or api.mp < (c.get("mp", 9) or 0) + mpres:
                return
        r = api.cmd("recruit %s P%d" % (typ, api.capital))
        if not str(r).startswith("ok"):
            return
        api.count("recruit_" + typ)
        if typ == "rec":
            nrec += 1

def _diplomacy(api, mem, provs):
    t = api.t
    pacts = api.pacts or {}
    met = api.met or []
    on = api.owner_name or {}
    nb = {}
    cnt = {}
    for p, f in on.items():
        cnt[f] = cnt.get(f, 0) + 1
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
    stale = t - max(mem.get("lastop", -999), mem.get("tset", -999)) >= 150 and not mem.get("ops")
    if t >= 24 and nb and (target not in nb or stale or t - mem.get("tset", -999) >= 400 and not mem.get("ops")):
        cands = [(s / 100.0 + cnt.get(f, 0) + (50 if f == target and stale else 0), f) for f, s in nb.items()]
        cands.sort()
        if cands[0][1] != target:
            api.count("retarget")
        target = cands[0][1]
        mem["target"] = target
        mem["tset"] = t
    if target and target in pacts and not pacts[target].get("broken_by") and t >= 24:
        api.cmd("break %s" % target)
        api.count("break_pact")
    if t >= 12:
        for o in (api.offers_in or []):
            if o.get("kind") in ("pact", "alliance"):
                if o.get("frm") != target:
                    api.cmd("accept %s" % o["id"])
                else:
                    api.cmd("reject %s" % o["id"])
            elif o.get("kind") == "trade":
                val = {"res": 1.0, "mp": 0.8, "steel": 0.3, "oil": 0.5, "rare": 2.0, "coal": 0.2, "rubber": 0.5}
                tg = sum(val.get(k, 1) * (v or 0) for k, v in (o.get("they_give") or {}).items())
                yg = sum(val.get(k, 1) * (v or 0) for k, v in (o.get("you_give") or {}).items())
                if tg >= 1.1 * yg and _afford(api, o.get("you_give") or {}, 20):
                    api.cmd("accept %s" % o["id"])
                else:
                    api.cmd("reject %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
    if t % 24 == 0 and t >= 24:
        out = set(o.get("to") for o in (api.offers_out or []))
        sent = mem.setdefault("psent", {})
        for f in met:
            if f == target or f in pacts or f in out:
                continue
            if t - sent.get(f, -999) < 96:
                continue
            api.cmd("offer %s pact" % f)
            api.cmd("say %s Germania offers lasting peace. We have no claims on you." % f)
            sent[f] = t
    if t % 48 == 12:
        st = api.stock or {}
        partners = [f for f, p in pacts.items() if not p.get("broken_by")]
        out = set(o.get("to") for o in (api.offers_out or []))
        n = 0
        for f in partners:
            if n >= 2 or f in out:
                continue
            if (st.get("coal", 0) or 0) > 1500:
                api.cmd("offer %s trade 300 coal for 60 res" % f)
                n += 1
            elif (st.get("steel", 0) or 0) > 3000:
                api.cmd("offer %s trade 300 steel for 60 res" % f)
                n += 1
            elif (st.get("oil", 0) or 0) > 5000:
                api.cmd("offer %s trade 400 oil for 80 res" % f)
                n += 1

def _done(api, ops, key, byid, in_op):
    op = ops[key]
    ids = [i for i in op["art"] + op["inf"] + op.get("rec", []) if i in byid]
    if ids:
        api.cmd("front " + ",".join(str(i) for i in ids))
    for i in ids:
        in_op.discard(i)
    del ops[key]

def _prep(api, op, byid, ids):
    bya = {}
    for i in ids:
        a = op["asg"].get(str(i))
        if a is None:
            continue
        bya.setdefault(a, []).append(i)
    ok = []
    for a, li in bya.items():
        r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in li), op["b"]))
        if str(r).startswith("ok"):
            ok += li
    return ok

def _blacklist(mem, b, t):
    bl = mem.setdefault("bl", {})
    bl[str(b)] = t

def _manage_ops(api, mem, ops, byid, provs, enemy, on, pacts, in_op):
    t = api.t
    for key in list(ops.keys()):
        op = ops[key]
        tg = op["b"]
        op["art"] = [i for i in op["art"] if i in byid]
        op["inf"] = [i for i in op["inf"] if i in byid]
        op["rec"] = [i for i in op.get("rec", []) if i in byid]
        pr = provs.get(tg, {})
        f = on.get(tg)
        if pr.get("owner") == "me":
            api.count("op_won")
            mem["lastop"] = t
            _done(api, ops, key, byid, in_op); continue
        if (f in pacts and not pacts[f].get("broken_by")) or t - op["t0"] > 400 or len(op["inf"]) < 3:
            api.count("op_abort")
            _blacklist(mem, tg, t)
            _done(api, ops, key, byid, in_op); continue
        ph = op["ph"]
        inf = op["inf"]
        if ph == "gather":
            at = [i for i in inf if byid[i]["prov"] == op["asg"].get(str(i)) and not byid[i]["path"]]
            if len(at) >= 0.85 * len(inf) or t - op["t0"] > 120:
                if len(at) < 4:
                    api.count("op_nogather")
                    _done(api, ops, key, byid, in_op); continue
                ok = _prep(api, op, byid, at)
                if len(ok) < 4:
                    api.count("op_noprep")
                    _blacklist(mem, tg, t)
                    _done(api, ops, key, byid, in_op); continue
                rest = [i for i in inf if i not in ok]
                if rest:
                    api.cmd("front " + ",".join(str(i) for i in rest))
                op["inf"] = ok
                r = api.cmd("group %s %s" % (_gname(tg), ",".join(str(i) for i in ok)))
                if not str(r).startswith("ok"):
                    api.count("group_fail")
                arts = [i for i in op["art"] if not byid[i]["path"]]
                if arts:
                    api.cmd("hold " + ",".join(str(i) for i in arts))
                op["ph"] = "siege"; op["t1"] = t
        elif ph == "siege":
            redo = [i for i in inf if not byid[i]["path"] and byid[i]["prov"] == op["asg"].get(str(i))
                    and byid[i]["state"] != "preparing" and _bon(byid[i]) <= 0 and byid[i].get("plan") != tg]
            if redo:
                _prep(api, op, byid, redo)
            arts = [i for i in op["art"] if not byid[i]["path"] and byid[i]["state"] == "ready"]
            if arts and t % 24 == 0:
                api.cmd("hold " + ",".join(str(i) for i in arts))
            e = enemy.get(tg)
            if e:
                ds = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
            else:
                ds = 0 if pr.get("visible") else 150
            n = float(len(inf))
            bon = sum(_bon(byid[i]) for i in inf) / n
            rd = sum(byid[i]["rdy"] for i in inf) / 100.0 / n
            ast = sum(byid[i]["str"] for i in inf)
            heavy = sum(1 for i in inf if byid[i]["type"] in ("eng", "arm", "art")) / n
            dirs = len(set(op["asg"].get(str(i)) for i in inf))
            p = _pwin(api, ast, ds, pr, bon, rd, heavy, dirs)
            age = t - op["t1"]
            go = False
            if rd >= 0.6 and age >= 18:
                if p >= 0.55 or ds <= 40:
                    go = True
                elif bon >= 45 and p >= 0.3:
                    go = True
            if age >= 96 and rd >= 0.5 and p >= 0.25 and ast >= 1.8 * ds:
                go = True
            if go:
                api.cmd("move %s P%d" % (",".join(str(i) for i in inf), tg))
                api.count("op_launch")
                mem["lastop"] = t
                op["ph"] = "go"; op["t2"] = t
            elif age >= 220:
                api.count("op_timeout")
                _blacklist(mem, tg, t)
                _done(api, ops, key, byid, in_op)
        elif ph == "go":
            avg = sum(byid[i]["str"] for i in inf) / float(len(inf))
            if t - op["t2"] > 72 or avg < 35:
                api.count("op_fail")
                _blacklist(mem, tg, t)
                _done(api, ops, key, byid, in_op); continue

def _new_ops(api, mem, ops, units, provs, enemy, on, pacts, in_op, garrison):
    t = api.t
    maxops = 3 if t < 600 else (4 if t < 1500 else 5)
    if t < 48 or len(ops) >= maxops:
        return
    caps = set((api.enemy_capitals or {}).values())
    edep = set((api.enemy_depots or {}).keys())
    target = mem.get("target")
    bl = mem.get("bl", {})
    tb = set(op["b"] for op in ops.values())
    hasart = "art" in (api.can_raise or [])
    seen = {}
    for a in (api.border or {}):
        pa = provs.get(a)
        if not pa or pa.get("owner") != "me" or not pa.get("supplied", True):
            continue
        for b in pa.get("nbrs", []):
            if b in tb:
                continue
            if t - bl.get(str(b), -9999) < 120:
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
        if pb.get("harsh"):
            continue
        e = enemy.get(b)
        if e is None and not pb.get("visible"):
            ds = 150
        else:
            ds = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3) if e else 0
        fort = pb.get("fort", 0) or 0
        td = _td(pb)
        val = (pb.get("y", 0) or 0) + 2 * (pb.get("steel", 0) or 0) + 2 * (pb.get("oil", 0) or 0) \
            + 3 * (pb.get("rare", 0) or 0) + (4 if pb.get("city") else 0)
        if b in caps:
            val += 80
        if b in edep:
            val += 60
        if f == target:
            val += 15
        sc = val - ds / 60.0 - 6 * (td - 1.0) - 3 * fort + 5 * min(3, len(srcs))
        cands.append((-sc, b, srcs, ds))
    if not cands:
        api.count("ops_nocand")
        return
    cands.sort(key=lambda z: z[0])
    pool = [u for u in units if u["id"] not in in_op and u["id"] not in garrison and not u.get("expand")
            and not u.get("explore") and (u.get("front") or (not u["path"] and u["state"] == "ready"))
            and u["str"] >= 70 and u["rdy"] >= 50 and not u.get("fighting") and u.get("dom", 0) == 0
            and u["state"] not in ("routing", "shaken", "refitting")
            and (u["type"] in ARTT or u["type"] in ASLT)]
    for _, b, srcs, ds in cands[:6]:
        if len(ops) >= maxops:
            break
        pb = provs[b]
        srcs = sorted(srcs, key=lambda a: -((provs[a].get("stock", 0) or 0)))[:3]
        pts = [(a, provs[a].get("x", 0) or 0, provs[a].get("y0", 0) or 0) for a in srcs]
        near_i = []; near_a = []
        for u in pool:
            if u["id"] in in_op:
                continue
            pu = provs.get(u["prov"], {})
            ux = pu.get("x", 0) or 0; uy = pu.get("y0", 0) or 0
            best = None
            for a, ax, ay in pts:
                d = abs(ux - ax) + abs(uy - ay)
                if best is None or d < best[0]:
                    best = (d, a)
            if best is None or best[0] > 90:
                continue
            if u["type"] in ARTT:
                near_a.append((best[0], u))
            else:
                near_i.append((best[0], best[1], u))
        near_i.sort(key=lambda z: z[0]); near_a.sort(key=lambda z: z[0])
        fm = 1.0 + 0.2 * (pb.get("fort", 0) or 0)
        td = _td(pb) + (0.25 if pb.get("city") else 0)
        need = max(2.5 * ds * fm * td, 600)
        need = min(need, 16000)
        pick = []; s = 0
        for d, a, u in near_i:
            if s >= need or len(pick) >= 160:
                break
            pick.append((a, u)); s += u["str"]
        if len(pick) < 6 or s < need * 0.8:
            api.count("op_short")
            continue
        arts = [u for d, u in near_a[:40]]
        if hasart and ds > 600 and len(arts) < 3:
            api.count("op_noart")
            continue
        if len(srcs) > 1:
            pick = [(srcs[k % len(srcs)], u) for k, (a, u) in enumerate(pick)]
        bya = {}
        asg = {}
        for a, u in pick:
            bya.setdefault(a, []).append(u["id"])
        for a, li in bya.items():
            api.cmd("move %s P%d" % (",".join(str(i) for i in li), a))
            for i in li:
                asg[str(i)] = a
                in_op.add(i)
        a0 = srcs[0]
        if arts:
            api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in arts), a0))
            for u in arts:
                in_op.add(u["id"])
        recs = []
        for u in units:
            if u["type"] == "rec" and u["id"] not in in_op and not u.get("fighting"):
                api.cmd("move %d P%d" % (u["id"], a0))
                in_op.add(u["id"]); recs.append(u["id"])
                break
        api.count("op_new")
        mem["lastop"] = t
        ops[str(b)] = {"b": b, "inf": [u["id"] for a, u in pick], "art": [u["id"] for u in arts],
                       "rec": recs, "asg": asg, "t0": t, "ph": "gather"}

def tick(api):
    mem = api.mem
    t = api.t
    units = [u for u in (api.units or []) if u.get("dom", 0) == 0 and not u.get("at_sea")]
    provs = api.provs or {}
    enemy = api.enemy or {}
    pacts = api.pacts or {}
    on = api.owner_name or {}
    ops = mem.setdefault("ops", {})
    for k in list(ops.keys()):
        if "inf" not in ops[k]:
            del ops[k]
    in_op = set()
    for op in ops.values():
        for i in op["inf"] + op["art"] + op.get("rec", []):
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
    except Exception: api.count("err_research")
    try: _economy(api, mem, provs)
    except Exception: api.count("err_econ")
    try: _depots(api, mem, provs)
    except Exception: pass
    try: _recruit(api, mem, units, armour_seen)
    except Exception: api.count("err_recruit")
    try: _diplomacy(api, mem, provs)
    except Exception: api.count("err_dip")
    try:
        if t % 96 == 30 and (api.old_units or 0) > 0 and api.res > 400:
            api.cmd("refit old")
    except Exception: pass

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

    claimed = mem.setdefault("claim", {})
    try:
        if t < 3000:
            for k in list(claimed.keys()):
                pr = provs.get(int(k), {})
                if pr.get("owner") != "neutral" or t - claimed[k][1] > 120 or claimed[k][0] not in byid:
                    del claimed[k]
            targ = []
            for a in (api.neutral_border or []):
                for b in provs.get(a, {}).get("nbrs", []):
                    pb = provs.get(b)
                    if not pb or pb.get("owner") != "neutral" or pb.get("harsh") or str(b) in claimed:
                        continue
                    if b in enemy:
                        continue
                    targ.append(b)
            targ = list(set(targ))[:6]
            busy = set(v[0] for v in claimed.values())
            free = [u for u in units if u["type"] in ("inf", "mil", "cav", "mot", "mtn") and not u["path"]
                    and u["id"] not in in_op and u["id"] not in garrison and u["id"] not in busy
                    and not u.get("fighting") and u["state"] in ("ready", "digging")]
            for b in targ:
                if not free:
                    break
                pb = provs[b]
                bx = pb.get("x", 0) or 0; by = pb.get("y0", 0) or 0
                best = None
                for u in free:
                    pu = provs.get(u["prov"], {})
                    d = math.hypot((pu.get("x", 0) or 0) - bx, (pu.get("y0", 0) or 0) - by)
                    if best is None or d < best[0]:
                        best = (d, u)
                if best and best[0] < 30:
                    u = best[1]
                    if str(api.cmd("move %d P%d" % (u["id"], b))).startswith("ok"):
                        claimed[str(b)] = (u["id"], t)
                        free.remove(u)
    except Exception:
        pass
    busyc = set(v[0] for v in claimed.values())

    try: _manage_ops(api, mem, ops, byid, provs, enemy, on, pacts, in_op)
    except Exception: api.count("err_ops")
    try: _new_ops(api, mem, ops, units, provs, enemy, on, pacts, in_op, garrison)
    except Exception: api.count("err_newops")

    try:
        nexp = sum(1 for u in units if u.get("expand"))
        cap_exp = max(40, int(len(units) * 0.4)) if t < 700 else (40 if t < 1500 else 20)
        can_expand = bool(api.neutral_border) or bool(far)
        idle_front = []
        k = mem.get("fk", 0)
        for u in units:
            i = u["id"]
            if i in in_op or i in garrison or i in busyc:
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
            if can_expand and nexp < cap_exp and u["type"] in ("cav", "inf", "mil", "mot", "mtn", "mec"):
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
```

```feedback
The 715 "bad group name" refusals gave no hint of the naming rule; please state it in the briefing (allowed characters, length). Upkeep took 90% of all earnings and the budget shows this only as a total. A per-unit-age breakdown, or a "units idle on quiet fronts" count, would help decide when to stop raising troops. Front units averaged readiness 20 for most of the war, and it is unclear whether the front order's constant re-spreading is what drains it; a readiness-loss-by-cause line in api.army(1) would answer that.
```

REVIEW: standard