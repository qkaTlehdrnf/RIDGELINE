RESERVE = 30
MIX = {"inf": 0.22, "mtn": 0.06, "grn": 0.08, "mot": 0.06, "art": 0.18,
       "atg": 0.06, "eng": 0.06, "arm": 0.10, "cav": 0.03, "mec": 0.05,
       "rkt": 0.06, "hvt": 0.03}
RESEARCH = ["farming", "conscription", "art.weapons", "industry", "inf.weapons",
            "arm.weapons", "logistics", "mining", "medicine", "inf.protection",
            "rkt.weapons", "atg.weapons", "drill", "discipline", "staffwork",
            "fieldworks", "mot.weapons", "arm.protection", "drilling", "refining",
            "inf.mobility", "mec.protection", "art.protection"]
EXPAND_TYPES = ("inf", "mtn", "grn", "mot", "mil", "mec", "cav")
# siege weight: artillery, rockets, armour count for more when judging an assault
WT = {"art": 2.0, "rkt": 2.0, "arm": 1.5, "hvt": 1.8, "eng": 1.2, "atg": 1.2, "grn": 1.2}
FORT_MULT = 1.25
MAX_PLANS = 3


def _ids_str(ids):
    return ",".join(str(i) for i in ids)


def _unit_cost(uc):
    if not uc:
        return None
    return {"res": uc.get("res", 0), "mp": uc.get("mp", 0), "steel": uc.get("steel", 0),
            "oil": uc.get("oil", 0), "rare": uc.get("rare", 0)}


def _cost_ok(stock, cost, reserve):
    if not isinstance(cost, dict):
        return False
    for k, v in cost.items():
        need = v + (reserve if k == "res" else 0)
        if stock.get(k, 0) < need:
            return False
    return True


def _spend(stock, cost):
    for k, v in cost.items():
        stock[k] = stock.get(k, 0) - v


def _recruit(api, stock, units):
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units) + 1
    for _ in range(4):
        cands = []
        if counts.get("rec", 0) < 2 and api.t < 480 and "rec" in api.unit_costs:
            cands.append((1e9, "rec"))
        for t, share in MIX.items():
            if t not in api.unit_costs:
                continue
            cands.append((share * total - counts.get(t, 0), t))
        cands.sort(reverse=True)
        picked = None
        for _, t in cands:
            cost = _unit_cost(api.unit_costs.get(t))
            if _cost_ok(stock, cost, RESERVE):
                picked = (t, cost)
                break
        if picked is None:
            break
        t, cost = picked
        r = api.cmd("recruit %s 1 P%d" % (t, api.capital))
        if not str(r).startswith("ok"):
            break
        _spend(stock, cost)
        counts[t] = counts.get(t, 0) + 1
        total += 1


def _micro(api, mem):
    neutral = api.neutral_border or []
    border = api.border or {}
    nonrec = [u for u in api.units if u["type"] != "rec"]
    expand_n = sum(1 for u in api.units if u.get("expand"))
    cap = max(2, len(nonrec) // 3)
    done = mem.setdefault("fortified", [])
    for u in api.units:
        if u.get("path") or u.get("fighting") or u.get("front") or u.get("expand") or u.get("explore"):
            continue
        p = u.get("plan", -1)
        if p is None:
            p = -1
        if p >= 0:
            continue
        if u.get("state") in ("routing", "digging", "refitting"):
            continue
        if u.get("str", 0) < 25:
            continue
        if u["type"] == "rec":
            api.cmd("explore %d" % u["id"])
            continue
        if u["type"] == "eng" and u["prov"] in border:
            if u["id"] not in done:
                r = api.cmd("fortify %d" % u["id"])
                if str(r).startswith("ok"):
                    done.append(u["id"])
            continue
        if neutral and expand_n < cap and u["type"] in EXPAND_TYPES:
            r = api.cmd("expand %d" % u["id"])
            if str(r).startswith("ok"):
                expand_n += 1
                continue
        api.cmd("front %d" % u["id"])


def _model_p(api, units, pr_q, es):
    m = api.model
    if not m or "w" not in m:
        return None
    try:
        n = float(len(units))
        dfn = [1.0, 1.25, 1.5, 2.0][min(3, int(pr_q.get("elev", 0) or 0))]
        ratio = (sum(u.get("str", 0) for u in units) + 1.0) / (es + 1.0)
        x = [math.log(ratio), dfn, float(pr_q.get("fort", 0) or 0),
             1.0 if pr_q.get("city") else 0.0,
             max(u.get("bonus", 0) for u in units) / 100.0,
             sum(u.get("rdy", 50) for u in units) / (100.0 * n),
             sum(1 for u in units if u["type"] in ("art", "eng", "arm")) / n,
             1.0]
        z = m["b"]
        for i in range(len(x)):
            z += m["w"][i] * (x[i] - m["mean"][i]) / m["std"][i]
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))
    except Exception:
        return None


def _attack(api, mem, by_prov):
    t = api.t
    plans = mem.setdefault("plans", {})
    for q in list(plans.keys()):
        if t - plans[q] >= 12:
            ids = [u["id"] for u in api.units if u.get("plan", -1) == q]
            if ids:
                api.cmd("move %s P%d" % (_ids_str(ids), q))
            del plans[q]
    if len(plans) >= MAX_PLANS:
        return
    enemy = api.enemy or {}
    provs = api.provs
    caps = set((api.enemy_capitals or {}).values())
    best = None
    for p in list(api.border.keys()):
        pr = provs.get(p)
        if not pr:
            continue
        ours = []
        for u in by_prov.get(p, []):
            pl = u.get("plan", -1)
            if pl is None:
                pl = -1
            if u.get("path") or u.get("fighting") or pl >= 0:
                continue
            if u.get("state") != "ready" or u.get("str", 0) < 50 or u.get("rdy", 0) < 60:
                continue
            ours.append(u)
        if not ours:
            continue
        os_ = sum(u.get("str", 0) * WT.get(u["type"], 1.0) for u in ours)
        if os_ < 80:
            continue
        for q in pr.get("nbrs", []):
            if q in plans:
                continue
            e = enemy.get(q)
            if not e or e.get("n", 0) <= 0:
                continue
            es = e.get("str", 0) or 0
            if es <= 0:
                es = 1.0
            pq = provs.get(q, {})
            fort = int(pq.get("fort", 0) or 0)
            eff = es * (FORT_MULT ** fort)
            ratio = os_ / (eff + 1.0)
            if ratio < 1.8:
                continue
            pm = _model_p(api, ours, pq, es)
            if pm is not None and pm < 0.45:
                continue
            score = (pm if pm is not None else min(1.0, ratio / 3.0))
            score -= 0.1 * fort
            if q in caps:
                score += 1.0
            if best is None or score > best[0]:
                best = (score, p, q, ours)
    if best is None:
        return
    _, p, q, ours = best
    r = api.cmd("prepare %s P%d" % (_ids_str([u["id"] for u in ours]), q))
    if str(r).startswith("ok"):
        plans[q] = t


def _research(api, stock):
    rs = api.research or []
    active = [r[0] for r in rs]
    slots = 2 - len(active)
    if slots <= 0:
        return
    tech = api.tech or {}
    for line in RESEARCH:
        if slots <= 0:
            break
        if line in active:
            continue
        info = tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost")
        if not _cost_ok(stock, cost, RESERVE + 20):
            continue
        r = api.cmd("research %s" % line)
        if str(r).startswith("ok"):
            _spend(stock, cost)
            slots -= 1
            active.append(line)


def tick(api):
    mem = api.mem
    stock = dict(api.stock)
    stock["mp"] = api.mp
    by_prov = {}
    for u in api.units:
        by_prov.setdefault(u["prov"], []).append(u)
    try:
        _recruit(api, stock, api.units)
    except Exception:
        pass
    try:
        _micro(api, mem)
    except Exception:
        pass
    try:
        _attack(api, mem, by_prov)
    except Exception:
        pass
    try:
        _research(api, stock)
    except Exception:
        pass
    mem["calls"] = mem.get("calls", 0) + 1
