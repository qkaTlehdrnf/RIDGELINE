def _ids(lst):
    return ",".join(str(i) for i in lst)

def _afford(api, t, n=1, reserve=25):
    c = api.unit_costs.get(t)
    if not c:
        return False
    s = api.stock
    if s.get("res", 0) < c.get("res", 0) * n + reserve: return False
    if api.mp < c.get("mp", 0) * n + 15: return False
    for k in ("steel", "oil", "rare"):
        if s.get(k, 0) < c.get(k, 0) * n: return False
    return True

def _model_p(api, A, D, tdf, fort, city, bonus, rdy, heavy, dirs):
    m = api.model or {}
    w = m.get("w"); mu = m.get("mean"); sd = m.get("std")
    if not w or not mu or not sd:
        return 1.0 / (1.0 + math.exp(-(math.log((A + 1.0) / (D + 1.0)) - 0.3 * fort - (tdf - 1))))
    x = [math.log((A + 1.0) / (D + 1.0)), tdf, fort, 1.0 if city else 0.0, bonus, rdy, heavy, dirs]
    z = m.get("b", 0.0)
    for i in range(len(w)):
        z += w[i] * (x[i] - mu[i]) / (sd[i] or 1.0)
    return 1.0 / (1.0 + math.exp(-z))

TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
RESEARCH = ["farming", "conscription", "industry", "staffwork", "logistics", "art.weapons",
            "grn.weapons", "medicine", "discipline", "mining", "drilling", "inf.protection",
            "fieldworks", "refining", "cav.mobility", "grn.protection", "inf.weapons",
            "art.protection", "drill", "atg.protection"]
STRIKE_T = ("grn", "art", "rkt", "arm", "mec", "hvt", "eng")

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    for line in RESEARCH:
        if len(busy) >= 2: break
        tk = api.tech.get(line)
        if not tk or tk.get("status") != "open" or line in busy: continue
        cost = tk.get("cost") or {}
        ok = True
        for k, v in cost.items():
            if api.stock.get(k, 0) < v + (60 if k == "res" else 0): ok = False
        if ok:
            r = api.cmd("research " + line)
            if r.startswith("ok"): busy.add(line)

def _recruit(api, mem, units, nstrike):
    t = api.t
    nun = len(units)
    nrec = sum(1 for u in units if u["type"] == "rec")
    nexp = sum(1 for u in units if u["expand"])
    want_rec = 4 if (api.unexplored and t < 1500) else (2 if api.unexplored else 1)
    if nrec < want_rec and _afford(api, "rec", 1, 5) and nun < 1400:
        api.cmd("recruit rec 1")
    if nun >= 1400: return
    bank = api.stock.get("res", 0)
    inc = api.income_by.get("res", api.income) if api.income_by else api.income
    if inc < 1 and bank < 200: return
    budget = int(min(14, 2 + bank / 60.0))
    expanding = bool(api.neutral_border)
    nb = len(api.border or {})
    nfront = sum(1 for u in units if u["front"] and not u["expand"])
    k0 = t // 6
    for b in range(budget):
        k = (k0 + b) % 8
        if expanding and nexp < 25 + nun // 6:
            typ = "cav" if k % 3 else "inf"
            nexp += 1
        elif nfront < 3 * nb + 10:
            typ = ["inf", "inf", "atg", "inf", "mil", "inf", "inf", "atg"][k]
            nfront += 1
        elif nstrike < 45:
            typ = ["grn", "art", "grn", "inf", "grn", "art", "eng", "grn"][k]
            nstrike += 1
        else:
            typ = ["inf", "atg", "inf", "inf", "grn", "inf", "art", "inf"][k]
        if not _afford(api, typ):
            typ = "inf"
            if not _afford(api, typ): break
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): break

def _rear_prov(api):
    provs = api.provs
    cap = api.capital
    best = None
    for pid, pr in provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied"): continue
        if pid in (api.border or {}): continue
        bad = False
        for nb in pr.get("nbrs", []):
            if nb in api.enemy or provs.get(nb, {}).get("owner") == "enemy":
                bad = True; break
        if bad: continue
        d = (pr.get("x", 0) or 0)
        score = -(pr.get("stock", 0) or 0)
        if best is None or score < best[0]:
            best = (score, pid)
    return best[1] if best else cap

def tick(api):
    mem = api.mem
    t = api.t
    provs = api.provs
    units = api.units
    if "strike" not in mem:
        mem["strike"] = []
        mem["op"] = None
        mem["grouped"] = False
    alive = {}
    for u in units:
        alive[u["id"]] = u
    strike = [i for i in mem["strike"] if i in alive]

    try:
        _research(api)
    except Exception:
        pass
    try:
        _recruit(api, mem, units, len(strike))
    except Exception:
        pass

    # ---- assign idle units ----
    strikeset = set(strike)
    newstrike = []
    has_rec = any(alive[i]["type"] == "rec" for i in strike)
    for u in units:
        if u["id"] in strikeset: continue
        if u["front"] or u["explore"] or u["expand"]: continue
        if u["path"]: continue
        typ = u["type"]
        if typ == "rec":
            if not has_rec and t > 300:
                newstrike.append(u["id"]); has_rec = True
            else:
                api.cmd("explore %d" % u["id"])
            continue
        if t > 300 and (typ in STRIKE_T or (typ == "inf" and len(strike) + len(newstrike) < 14)):
            if len(strike) + len(newstrike) < 50:
                newstrike.append(u["id"])
                continue
        if api.neutral_border and typ in ("cav", "inf", "mot", "mtn", "mil", "grn"):
            api.cmd("expand %d" % u["id"])
        else:
            api.cmd("front %d" % u["id"])
    if newstrike:
        if mem["grouped"]:
            api.cmd("group strike + " + _ids(newstrike))
        else:
            api.cmd("group strike " + _ids(newstrike))
        mem["grouped"] = True
        strike += newstrike
    keep = []
    for i in strike:
        u = alive[i]
        if u["str"] < 25 and u["type"] != "rec" and not mem.get("op"):
            api.cmd("front %d" % i)
        else:
            keep.append(i)
    strike = keep
    mem["strike"] = strike
    fighters = [i for i in strike if alive[i]["type"] != "rec"]
    recs = [i for i in strike if alive[i]["type"] == "rec"]

    # ---- operation state machine ----
    op = mem["op"]
    if op:
        T = op["T"]; S = op["S"]; st = op["st"]
        pt = provs.get(T, {})
        if st != "refit" and (pt.get("owner") == "me" or not fighters or t - op["t0"] > 300):
            took = pt.get("owner") == "me"
            if fighters:
                api.cmd("hold " + _ids(fighters))
            avg = sum(alive[i]["str"] for i in fighters) / float(len(fighters)) if fighters else 100
            if avg < 70 or not took:
                R = _rear_prov(api)
                api.cmd("move " + _ids(strike) + " P%d" % R)
                op = dict(T=T, S=R, st="refit", t0=t, t1=t)
            else:
                op = None
        elif st == "refit":
            avg = sum(alive[i]["str"] for i in fighters) / float(len(fighters)) if fighters else 100
            ar = sum(alive[i]["rdy"] for i in fighters) / float(len(fighters)) if fighters else 100
            if (avg > 85 and ar > 70) or t - op["t1"] > 200:
                op = None
        elif st == "gather":
            ps = provs.get(S, {})
            if ps.get("owner") != "me":
                op = None
            else:
                there = [i for i in fighters if alive[i]["prov"] == S and not alive[i]["path"]]
                if len(there) >= 0.8 * len(fighters) or t - op["t1"] > 90:
                    rr = [i for i in recs if alive[i]["prov"] == S]
                    api.cmd("prepare " + _ids(there + rr) + " P%d" % T)
                    op["st"] = "prep"; op["t1"] = t
                else:
                    lag = [i for i in strike if alive[i]["prov"] != S and not alive[i]["path"]]
                    if lag and t - op["t1"] >= 6:
                        api.cmd("move " + _ids(lag) + " P%d" % S)
        elif st == "prep":
            there = [i for i in fighters if alive[i]["prov"] == S]
            lag = [i for i in strike if alive[i]["prov"] != S and not alive[i]["path"]]
            if lag:
                api.cmd("move " + _ids(lag) + " P%d" % S)
            notprep = [i for i in strike if alive[i]["prov"] == S and alive[i]["plan"] != T]
            if notprep:
                api.cmd("prepare " + _ids(notprep) + " P%d" % T)
            if there:
                ab = sum(alive[i]["bonus"] for i in there) / float(len(there))
                ar = sum(alive[i]["rdy"] for i in there) / float(len(there))
                A = sum(alive[i]["str"] for i in there)
                e = api.enemy.get(T, {})
                D = e.get("str", 0)
                heavy = sum(1 for i in there if alive[i]["type"] in ("art", "eng", "arm")) / float(len(there))
                dirs = sum(1 for x in pt.get("nbrs", []) if provs.get(x, {}).get("owner") == "me")
                p = _model_p(api, A, D, TDF.get(pt.get("terrain"), 1.0), pt.get("fort", 0) or 0,
                             pt.get("city"), ab / 100.0, ar / 100.0, heavy, min(dirs, 4))
                ready = (ab >= 45 and ar >= 60) or t - op["t1"] > 110
                if ready:
                    if p >= 0.45 and A > 2.5 * D:
                        api.cmd("move " + _ids(there) + " P%d" % T)
                        op["st"] = "go"; op["t1"] = t
                    elif t - op["t1"] > 140:
                        api.cmd("hold " + _ids(strike))
                        op = None
        elif st == "go":
            idle = [i for i in fighters if not alive[i]["path"] and alive[i]["prov"] != T]
            if idle and t - op["t1"] < 150:
                api.cmd("move " + _ids(idle) + " P%d" % T)
            avg = sum(alive[i]["str"] for i in fighters) / float(len(fighters))
            if avg < 40:
                api.cmd("hold " + _ids(fighters))
                R = _rear_prov(api)
                api.cmd("move " + _ids(strike) + " P%d" % R)
                op = dict(T=T, S=R, st="refit", t0=t, t1=t)
        mem["op"] = op

    if not mem["op"] and len(fighters) >= 10 and t > 350:
        A = sum(alive[i]["str"] for i in fighters)
        heavy = sum(1 for i in fighters if alive[i]["type"] in ("art", "eng", "arm")) / float(len(fighters))
        best = None
        caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
        for pid, pr in provs.items():
            if pr.get("owner") != "me" or not pr.get("supplied"): continue
            for nb in pr.get("nbrs", []):
                q = provs.get(nb)
                if not q or q.get("owner") != "enemy": continue
                e = api.enemy.get(nb)
                if e:
                    D = e.get("str", 0)
                elif q.get("visible"):
                    D = 0
                else:
                    D = 150
                fort = q.get("fort", 0) or 0
                dirs = sum(1 for x in q.get("nbrs", []) if provs.get(x, {}).get("owner") == "me")
                p = _model_p(api, A, D, TDF.get(q.get("terrain"), 1.0), fort,
                             q.get("city"), 0.45, 0.75, heavy, min(dirs, 4))
                if p < 0.5 or A < 3 * D: continue
                val = p * (1.0 + 0.3 * (q.get("y", 1) or 1) + (6.0 if nb in caps else 0)
                           + (0.6 if q.get("city") else 0) + 0.2 * dirs - 0.3 * fort)
                if best is None or val > best[0]:
                    best = (val, nb, pid)
        if best:
            T, S = best[1], best[2]
            mem["op"] = dict(T=T, S=S, st="gather", t0=t, t1=t)
            api.cmd("move " + _ids(strike) + " P%d" % S)
