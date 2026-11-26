**Review:** Last war we finished 16th of 30 with 87 provinces. The stalemate came from two places. Assaults almost never launched, because the attack gates (strength ≥50, readiness ≥70, ratio ≥2.2, model ≥0.5) were too strict. We also ended with 1082 rare, 646 steel and 487 oil unspent. Land ran out by about day 25.

**Changes:**
- Loosen the attack gates (readiness ≥50, strength ≥40, ratio ≥1.7, launch ≥1.4) and allow up to 6 plans at once, with shorter plan windows.
- Shift the recruit mix toward rocket, heavy, armour and motorised units when rare, steel or oil pile up, and cut the reserve so stockpiles get used.
- Accept pacts as before. Also accept trades that give us oil or rare for surplus steel or rare when our stock is high.
- Recruit up to 8 units per tick instead of 4.

Research order and the micro logic are kept as before. Dead-end lines are still skipped automatically.

```python
RESERVE = 20
BASE_MIX = {"inf": 0.20, "mtn": 0.05, "grn": 0.08, "mot": 0.07, "art": 0.16,
            "atg": 0.05, "eng": 0.05, "arm": 0.11, "cav": 0.02, "mec": 0.06,
            "rkt": 0.07, "hvt": 0.04}
RESEARCH = ["farming", "conscription", "art.weapons", "industry", "inf.weapons",
            "arm.weapons", "logistics", "mining", "medicine", "inf.protection",
            "rkt.weapons", "atg.weapons", "drill", "discipline", "staffwork",
            "fieldworks", "mot.weapons", "arm.protection", "drilling", "refining",
            "inf.mobility", "mec.protection", "art.protection"]
EXPAND_TYPES = ("inf", "mtn", "grn", "mot", "mil", "mec", "cav")
WT = {"art": 2.0, "rkt": 2.0, "arm": 1.5, "hvt": 1.8, "eng": 1.2, "atg": 1.2, "grn": 1.2}
FORT_MULT = 1.25
MAX_PLANS = 6
PLAN_HOURS = 16
MIN_RATIO = 1.7
LAUNCH_RATIO = 1.4
MIN_PM = 0.35


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
    m = dict(BASE_MIX)
    if stock.get("rare", 0) > 200:
        m["rkt"] = m.get("rkt", 0) + 0.08
        m["hvt"] = m.get("hvt", 0) + 0.04
    if stock.get("steel", 0) > 200:
        m["arm"] = m.get("arm", 0) + 0.06
        m["hvt"] = m.get("hvt", 0) + 0.02
    if stock.get("oil", 0) > 200:
        m["mot"] = m.get("mot", 0) + 0.04
        m["arm"] = m.get("arm", 0) + 0.02
    s = sum(m.values())
    return {k: v / s for k, v in m.items()}


def _accept_offers(api, stock):
    for o in (api.offers_in or []):
        try:
            oid = int(o["id"])
            if o.get("kind") == "pact":
                api.cmd("accept %d" % oid)
                continue
            if o.get("kind") == "trade":
                give = o.get("they_give", {}) or {}
                pay = o.get("you_give", {}) or {}
                if not give or not set(pay.keys()) <= {"steel", "rare"}:
                    continue
                if stock.get("steel", 0) > 400 or stock.get("rare", 0) > 400:
                    if set(give.keys()) <= {"oil", "steel"} and stock.get("oil", 0) < 150:
                        api.cmd("accept %d" % oid)
        except Exception:
            pass


def _recruit(api, stock, units):
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    mix = _mix(stock)
    total = len(units) + 1
    uc_all = api.unit_costs or {}
    for _ in range(8):
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
    nonrec = [u for u in api.units if u["type"] != "rec"]
    expand_n = sum(1 for u in api.units if u.get("expand"))
    cap = max(2, len(nonrec) // 3)
    done = mem.setdefault("fortified", [])
    border = api.border or {}
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
                    cool[q] = t + 18
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
            if u.get("state") not in ("ready", "defending") or u.get("str", 0) < 40 or u.get("rdy", 0) < 50:
                continue
            ours.append(u)
        if not ours:
            continue
        os_ = _strength_w(ours)
        if os_ < 60:
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
        _accept_offers(api, stock)
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
to cascadia: Accepted. Lasting peace holds from our side: no attacks, no provinces taken, while your pact stands.
```