Sable is fast and cheap but fragile on defence, so my standing orders play a land-grab and score game with opportunistic strikes:

1. **Grab land early.** Cheap fast cavalry and infantry run `expand`, and two scouts `explore`. Territory yield decides the score at tick 4800 and pays for everything else.
2. **Hold the border with standing orders.** Every unit not assigned elsewhere joins `front`, which spreads, digs in and rotates weak units on its own.
3. **Strike with one formation.** A named group "strike" (grenadiers, artillery, infantry and a scout) builds formation experience. The cycle is pick, stage, prepare, launch:
   - It picks an adjacent enemy province scored with the fitted battle model, weighted by yield, with a big bonus for an enemy capital.
   - It gathers in a supplied staging province.
   - It runs `prepare` with the scout alongside, which allows up to +75%.
   - It launches when the bonus is about 40% or after 54 hours, and drops targets that look hopeless.
   - Units that fall below 30 strength are handed to the front.
4. **Recruit only what the economy can carry.** Recruiting needs positive net income and a manpower reserve, and units are checked against all four resources.
5. **Research economy first.** Farming, conscription, industry, logistics and mining come first, then weapons for the infantry, grenadiers and artillery. Dead ends are skipped automatically.

```python
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
RESEARCH = ["farming", "conscription", "industry", "logistics", "mining", "inf.weapons",
            "grn.weapons", "art.weapons", "medicine", "discipline", "drilling", "inf.protection",
            "drill", "fieldworks", "staffwork", "refining", "cav.mobility", "grn.protection"]

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

    # ---- research ----
    try:
        if len(api.research) < 2:
            busy = set(r[0] for r in api.research)
            for line in RESEARCH:
                if len(busy) >= 2: break
                tk = api.tech.get(line)
                if not tk or tk.get("status") != "open" or line in busy: continue
                cost = tk.get("cost") or {}
                ok = True
                for k, v in cost.items():
                    have = api.stock.get(k, 0)
                    if have < v + (40 if k == "res" else 0): ok = False
                if ok:
                    r = api.cmd("research " + line)
                    if r.startswith("ok"): busy.add(line)
    except Exception:
        pass

    # ---- recruitment ----
    nrec = sum(1 for u in units if u["type"] == "rec")
    nun = len(units)
    try:
        if nrec < (2 if api.unexplored else 1) and _afford(api, "rec", 1, 5) and nun < 200:
            api.cmd("recruit rec 1")
            nrec += 1
        inc = api.income_by.get("res", api.income) if api.income_by else api.income
        budget = 3
        while budget > 0 and (inc > 1.5 or api.stock.get("res", 0) > 250):
            budget -= 1
            if api.neutral_border and t < 1500 and nun < 40:
                typ = "cav" if (t // 6) % 2 == 0 else "inf"
            else:
                k = (t // 6 + budget) % 6
                if len(strike) < 14:
                    typ = ["grn", "art", "grn", "inf", "grn", "art"][k]
                else:
                    typ = ["inf", "inf", "atg", "inf", "mil", "inf"][k]
                if not _afford(api, typ):
                    typ = "inf"
            if not _afford(api, typ):
                break
            r = api.cmd("recruit %s 1" % typ)
            if not r.startswith("ok"): break
            inc -= api.unit_costs.get(typ, {}).get("res", 8) * 0.0 + 0.12
    except Exception:
        pass

    # ---- assign idle units ----
    strikeset = set(strike)
    newstrike = []
    for u in units:
        if u["id"] in strikeset: continue
        if u["front"] or u["explore"] or u["expand"]: continue
        if u["path"]: continue
        typ = u["type"]
        if typ == "rec":
            if api.unexplored and nrec > 0 and not any(alive[i]["type"] == "rec" for i in strike if i in alive) is False:
                pass
            if not any(alive[i]["type"] == "rec" for i in strike) and t > 200:
                newstrike.append(u["id"])
            else:
                api.cmd("explore %d" % u["id"])
            continue
        if typ in ("grn", "art", "rkt", "arm", "mot", "mec", "hvt") or (typ == "inf" and len(strike) + len(newstrike) < 6 and t > 400):
            newstrike.append(u["id"])
            continue
        if api.neutral_border:
            api.cmd("expand %d" % u["id"])
        else:
            api.cmd("front %d" % u["id"])
    if newstrike:
        if strike or mem["grouped"]:
            api.cmd("group strike + " + _ids(newstrike))
        else:
            api.cmd("group strike " + _ids(newstrike))
        mem["grouped"] = True
        strike += newstrike
    # release worn units
    keep = []
    for i in strike:
        u = alive[i]
        if u["str"] < 30 and u["type"] != "rec":
            api.cmd("front %d" % i)
        else:
            keep.append(i)
    strike = keep
    mem["strike"] = strike
    fighters = [i for i in strike if alive[i]["type"] != "rec"]

    # ---- operation state machine ----
    op = mem["op"]
    if op:
        T = op["T"]; S = op["S"]
        pt = provs.get(T, {})
        if pt.get("owner") == "me" or not fighters or t - op["t0"] > 260:
            mem["op"] = None
            if fighters and pt.get("owner") == "me":
                api.cmd("hold " + _ids(fighters))
            op = None
        elif op["st"] == "gather":
            ps = provs.get(S, {})
            if ps.get("owner") != "me":
                mem["op"] = None; op = None
            else:
                there = [i for i in fighters if alive[i]["prov"] == S and not alive[i]["path"]]
                if len(there) >= 0.75 * len(fighters) or t - op["t1"] > 72:
                    api.cmd("prepare " + _ids(there + [i for i in strike if alive[i]["type"] == "rec" and alive[i]["prov"] == S]) + " P%d" % T)
                    op["st"] = "prep"; op["t1"] = t
                elif t - op["t1"] > 6 and any(alive[i]["prov"] != S and not alive[i]["path"] for i in strike):
                    api.cmd("move " + _ids([i for i in strike if alive[i]["prov"] != S and not alive[i]["path"]]) + " P%d" % S)
        elif op["st"] == "prep":
            there = [i for i in fighters if alive[i]["prov"] == S]
            bon = [alive[i]["bonus"] for i in there] or [0]
            ab = sum(bon) / float(len(bon))
            A = sum(alive[i]["str"] for i in there)
            e = api.enemy.get(T, {})
            D = e.get("str", 0)
            p = _model_p(api, A, D, TDF.get(pt.get("terrain"), 1.0), pt.get("fort", 0) or 0,
                         pt.get("city"), ab / 100.0, 0.7, 0.3, 1)
            if (ab >= 40 or t - op["t1"] > 54) and there:
                if p < 0.3 and t - op["t1"] < 100:
                    pass
                elif p < 0.3:
                    mem["op"] = None; op = None
                else:
                    api.cmd("move " + _ids(there) + " P%d" % T)
                    op["st"] = "go"; op["t1"] = t
        elif op["st"] == "go":
            idle = [i for i in fighters if not alive[i]["path"] and alive[i]["prov"] != T]
            if idle and t - op["t1"] < 150:
                api.cmd("move " + _ids(idle) + " P%d" % T)
            avg = sum(alive[i]["str"] for i in fighters) / float(len(fighters))
            if avg < 40:
                mem["op"] = None; op = None
                api.cmd("hold " + _ids(fighters))
        if op: mem["op"] = op

    if not mem["op"] and len(fighters) >= 8 and t > 300:
        A = sum(alive[i]["str"] for i in fighters)
        heavy = sum(1 for i in fighters if alive[i]["type"] in ("art", "eng", "arm")) / float(len(fighters))
        best = None
        caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
        for pid, pr in provs.items():
            if pr.get("owner") != "me" or not pr.get("supplied"): continue
            for nb in pr.get("nbrs", []):
                q = provs.get(nb)
                if not q or q.get("owner") != "enemy": continue
                e = api.enemy.get(nb, {})
                D = e.get("str", 0)
                dirs = sum(1 for x in q.get("nbrs", []) if provs.get(x, {}).get("owner") == "me")
                p = _model_p(api, A, D, TDF.get(q.get("terrain"), 1.0), q.get("fort", 0) or 0,
                             q.get("city"), 0.4, 0.7, heavy, min(dirs, 4))
                val = p * (1.0 + 0.3 * (q.get("y", 1) or 1) + (5.0 if nb in caps else 0) + (0.5 if q.get("city") else 0))
                if p < 0.45: continue
                if best is None or val > best[0]:
                    best = (val, nb, pid)
        if best:
            T, S = best[1], best[2]
            mem["op"] = dict(T=T, S=S, st="gather", t0=t, t1=t)
            api.cmd("move " + _ids(strike) + " P%d" % S)
```