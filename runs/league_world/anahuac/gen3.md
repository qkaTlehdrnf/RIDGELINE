The previous file failed because it called `getattr`, which is not among the allowed builtins. This version drops `getattr` and wraps every subsystem in its own try/except, so one failing step cannot take down the whole tick.

Review of the last war: we finished 16th of 30 with 83 provinces. Assaults on defended provinces almost never succeeded (1 of 160), and about 1,000 rare sat unused. Cascadia and Andea offered pacts repeatedly, and we never accepted.

Changes from the current policy:
- Accept incoming pact offers. Peace with the strongest neighbours frees forces for the front that matters.
- Keep the expansion, fortification, and research logic, which is what grew our territory.
- Keep the attack logic, which still requires a strength and model-probability threshold before committing.
- Keep rare-heavy unit mixes, since rare stock was idle.

```python
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
WT = {"art": 2.0, "rkt": 2.0, "arm": 1.5, "hvt": 1.8, "eng": 1.2, "atg": 1.2, "grn": 1.2}
FORT_MULT = 1.25
MAX_PLANS = 4
PLAN_HOURS = 20
MIN_RATIO = 2.2
LAUNCH_RATIO = 1.8
MIN_PM = 0.5


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


def _mix(stock):
    m = dict(MIX)
    if stock.get("rare", 0) > 300:
        m["rkt"] = m.get("rkt", 0) + 0.05
        m["hvt"] = m.get("hvt", 0) + 0.03
    if stock.get("steel", 0) > 300:
        m["arm"] = m.get("arm", 0) + 0.04
    s = sum(m.values())
    return {k: v / s for k, v in m.items()}


def _accept_pacts(api):
    for o in (api.offers_in or []):
        try:
            if o.get("kind") == "pact":
                api.cmd("accept %d" % int(o["id"]))
        except Exception:
            pass


def _recruit(api, stock, units):
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    mix = _mix(stock)
    total = len(units) + 1
    uc_all = api.unit_costs or {}
    for _ in range(4):
        cands = []
        if counts.get("rec", 0) < 2 and api.t < 480 and "rec" in uc_all:
            cands.append((1e9, "rec"))
        for t, share in mix.items():
            if t not in uc_all:
                continue
            cands.append((share * total - counts.get(t, 0), t))
        cands.sort(reverse=True)
        picked = None
        for _, t in cands:
            cost = _unit_cost(uc_all.get(t))
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


def _strength_w(units):
    return sum(u.get("str", 0) * WT.get(u["type"], 1.0) for u in units)


def _launch_ok(api, q, units):
    e = (api.enemy or {}).get(q)
    if not e or e.get("n", 0) <= 0:
        return True
    es = e.get("str", 0) or 1.0
    fort = int((api.provs.get(q, {}) or {}).get("fort", 0) or 0)
    eff = es * (FORT_MULT ** fort)
    return _strength_w(units) / (eff + 1.0) >= LAUNCH_RATIO


def _attack(api, mem, by_prov):
    t = api.t
    plans = mem.setdefault("plans", {})
    cool = mem.setdefault("cool", {})
    for q in list(plans.keys()):
        if t - plans[q] >= PLAN_HOURS:
            ids = [u["id"] for u in api.units if u.get("plan", -1) == q]
            units = [u for u in api.units if u.get("plan", -1) == q]
            if ids:
                if _launch_ok(api, q, units):
                    api.cmd("move %s P%d" % (_ids_str(ids), q))
                else:
                    api.cmd("hold %s" % _ids_str(ids))
                    cool[q] = t + 24
            del plans[q]
    if len(plans) >= MAX_PLANS:
        return
    enemy = api.enemy or {}
    provs = api.provs
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
            if u.get("state") != "ready" or u.get("str", 0) < 50 or u.get("rdy", 0) < 70:
                continue
            ours.append(u)
        if not ours:
            continue
        os_ = _strength_w(ours)
        if os_ < 80:
            continue
        for q in pr.get("nbrs", []):
            if q in plans or cool.get(q, -1) > t:
                continue
            e = enemy.get(q)
            if not e or e.get("n", 0) <= 0:
                continue
            es = e.get("str", 0) or 0
            if es <= 0:
                es = 1.0
            pq = provs.get(q, {}) or {}
            fort = int(pq.get("fort", 0) or 0)
            eff = es * (FORT_MULT ** fort)
            ratio = os_ / (eff + 1.0)
            if ratio < MIN_RATIO:
                continue
            pm = _model_p(api, ours, pq, es)
            if pm is not None and pm < MIN_PM:
                continue
            score = (pm if pm is not None else min(1.0, ratio / 3.0))
            score -= 0.1 * fort
            if q in set((api.enemy_capitals or {}).values()):
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
        _accept_pacts(api)
    except Exception:
        pass
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
```

```letters
to cascadia: Anahuac accepts your peace. Keep your troops off our land and we will keep ours off yours.
```