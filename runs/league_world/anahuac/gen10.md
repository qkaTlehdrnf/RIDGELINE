**Reasoning**

The last war placed 6th of 31 with 230 provinces, the best result so far, so I keep the overall plan. The main failure was economic. Units were upkeep-heavy: 20,437 units cost 2.78M res over the war against 1.59M earned. Net income went negative around day 600 and the treasury ended at zero. Readiness then fell to about 28, and 19,318 units were still on old models because refit requires readiness and supply.

Changes, kept small:
1. Recruitment pauses when net income is below 40 per day, so upkeep cannot outrun income.
2. Development and building pause while net income is negative.
3. Everything else is unchanged: the expand/front/prepare structure, pact handling, research order, and trade.

I'm not changing the attack thresholds. Assault win rates were good at ratios of 2 or more, and the bottleneck was the economy, not the assault logic.

```python
RESERVE = 20
RECRUIT_MIN_INCOME = 40
BASE_MIX = {"inf": 0.22, "mtn": 0.05, "grn": 0.09, "mot": 0.08, "art": 0.11,
            "atg": 0.05, "eng": 0.05, "arm": 0.12, "cav": 0.02, "mec": 0.07,
            "rkt": 0.05, "hvt": 0.06}
RESEARCH = ["farming", "conscription", "industry", "art.weapons", "inf.weapons",
            "arm.weapons", "logistics", "mining", "medicine", "inf.protection",
            "rkt.weapons", "atg.weapons", "drill", "discipline", "staffwork",
            "fieldworks", "mot.weapons", "arm.protection", "drilling", "refining",
            "inf.mobility", "mec.protection", "art.protection"]
DISC_ORDER = ["iron_working", "horse_riding", "masonry", "roads", "siege_engines",
              "galleys", "stirrup", "pikes_crossbows", "hillmen", "castles",
              "sailing", "crop_rotation", "trebuchet", "gunpowder", "matchlock",
              "banking", "navigation", "ships_of_the_line", "grenadiers", "dragoons",
              "steam_power", "railways", "rifling", "steel_guns", "field_engineering",
              "ironclads", "combustion", "machine_guns", "flight", "tanks",
              "heavy_artillery", "anti_tank_guns", "bombers", "submarines",
              "dreadnoughts", "mechanisation", "heavy_armour", "rocket_artillery",
              "assault_rifles", "jet_engines", "carriers", "rocketry", "satellites",
              "ballistic_missiles", "guided_weapons", "composite_armour"]
EXPAND_TYPES = ("inf", "mtn", "grn", "mot", "mil", "mec", "cav")
WT = {"art": 2.0, "rkt": 2.0, "arm": 1.5, "hvt": 1.8, "eng": 1.2, "atg": 1.2, "grn": 1.2}
FORT_MULT = 1.25
MAX_PLANS = 8
PLAN_HOURS = 16
MIN_RATIO = 1.3
LAUNCH_RATIO = 1.15
MIN_PM = 0.25
SAVE_DAYS = 12
SAVE_MIN = 400
DEV_CAP = 4
TRADE_RARE_MIN = 300
TRADE_RES_MAX = 150
TRADE_AMT = 100
TRADE_GET = 150


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


def _res_need(info):
    c = info.get("cost") if isinstance(info, dict) else None
    need = c.get("res", 0) if isinstance(c, dict) else 0
    rn = info.get("res_now") if isinstance(info, dict) else None
    if isinstance(rn, dict):
        rn = rn.get("res", 0)
    if isinstance(rn, (int, float)) and rn > need:
        need = rn
    return need


def _pacted(api, q):
    owner = (api.owner_name or {}).get(q)
    if owner is None:
        return False
    return owner in (api.pacts or {}) or owner == api.me


def _mix(stock):
    m = dict(BASE_MIX)
    if stock.get("rare", 0) > 200:
        m["hvt"] = m.get("hvt", 0) + 0.04
        m["rkt"] = m.get("rkt", 0) + 0.03
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


def _trade(api, stock, mem):
    if api.t - mem.get("trade_t", -99) < 24:
        return
    if stock.get("rare", 0) < TRADE_RARE_MIN or stock.get("res", 0) > TRADE_RES_MAX:
        return
    last = mem.setdefault("trade_last", {})
    for f in (api.met or []):
        if f == api.me or api.t - last.get(f, -999) < 96:
            continue
        r = api.cmd("offer %s trade %d rare for %d res" % (f, TRADE_AMT, TRADE_GET))
        last[f] = api.t
        if str(r).startswith("ok"):
            mem["trade_t"] = api.t
            api.count("trade_offer")
            break


def _plan_save(api, mem):
    mem["save"] = 0
    rs = api.research or []
    if any("." not in r[0] for r in rs):
        return
    tree = api.tree or {}
    inc = max(float(api.income or 0), 1.0)
    for d in DISC_ORDER:
        info = tree.get(d)
        if not info or info.get("status") != "open":
            continue
        need = _res_need(info)
        if need <= max(SAVE_MIN, SAVE_DAYS * inc):
            mem["save"] = need
        return


def _economy(api, stock, mem):
    # no new buildings while the purse is shrinking
    if float(api.income or 0) < 0:
        return
    eco = api.economy or {}
    if len(eco.get("works") or []) >= 6:
        return
    rows = eco.get("provs") or []
    res = stock.get("res", 0)
    save = mem.get("save", 0)
    n = 0
    for r in rows:
        if n >= 2:
            break
        try:
            dev = r.get("dev", 0) or 0
            room = r.get("room", 0) or 0
            if r.get("can_dev") and dev + 1 <= room and dev < DEV_CAP:
                c = r.get("dev_cost") or {}
                if res - c.get("res", 0) >= RESERVE + save + 60:
                    if str(api.cmd("develop P%d" % r["prov"])).startswith("ok"):
                        res -= c.get("res", 0)
                        _spend(stock, c)
                        api.count("develop")
                        n += 1
                        continue
            if r.get("can_infra") and (r.get("infra", 0) or 0) < 2 and dev >= 2:
                c = r.get("infra_cost") or {}
                if res - c.get("res", 0) >= RESERVE + save + 100 and \
                        stock.get("steel", 0) >= c.get("steel", 0) + 10:
                    if str(api.cmd("build P%d" % r["prov"])).startswith("ok"):
                        res -= c.get("res", 0)
                        _spend(stock, c)
                        api.count("build")
                        n += 1
        except Exception:
            continue


def _research(api, stock, mem):
    rs = api.research or []
    active = [r[0] for r in rs]
    disc_active = any("." not in a for a in active)
    tree = api.tree or {}
    open_disc = None
    for d in DISC_ORDER:
        info = tree.get(d)
        if info and info.get("status") == "open":
            open_disc = d
            break
    if not disc_active and open_disc is not None:
        info = tree.get(open_disc) or {}
        need = _res_need(info)
        if stock.get("res", 0) >= need + RESERVE:
            r = api.cmd("research %s" % open_disc)
            if str(r).startswith("ok"):
                _spend(stock, {"res": need})
                active.append(open_disc)
                disc_active = True
                api.count("discovery_started")
    pending = open_disc is not None and not disc_active and mem.get("save", 0) > 0
    max_active = 1 if pending else 2
    tech = api.tech or {}
    for line in RESEARCH:
        if len(active) >= max_active:
            break
        if line in active:
            continue
        info = tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost")
        if not _cost_ok(stock, cost, RESERVE + mem.get("save", 0) + 20):
            continue
        r = api.cmd("research %s" % line)
        if str(r).startswith("ok"):
            _spend(stock, cost)
            active.append(line)


def _recruit(api, stock, units, mem):
    # upkeep of a large army outran income last war; pause when the purse is not growing
    if float(api.income or 0) < RECRUIT_MIN_INCOME:
        api.count("recruit_paused")
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    mix = _mix(stock)
    total = len(units) + 1
    uc_all = api.unit_costs or {}
    reserve = RESERVE + mem.get("save", 0)
    for _ in range(10):
        cands = []
        if counts.get("rec", 0) < 2 and api.t < 480 and "rec" in uc_all:
            cands.append((1e9, "rec"))
        for t, share in mix.items():
            if t not in uc_all:
                continue
            cands.append((share * total - counts.get(t, 0), t))
        if not cands and "inf" in uc_all:
            cands.append((0, "inf"))
        cands.sort(reverse=True)
        picked = None
        for _, t in cands:
            cost = _unit_cost(uc_all.get(t))
            if _cost_ok(stock, cost, reserve):
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


def _refit(api, stock, mem):
    if api.t - mem.get("refit_t", -99) < 12:
        return
    if (getattr(api, "old_units", 0) or 0) <= 0:
        return
    rc = api.refit_cost or {}
    picked = []
    for u in api.units:
        if not u.get("old"):
            continue
        if u.get("path") or u.get("fighting") or u.get("state") not in ("ready", "defending"):
            continue
        if not u.get("supplied"):
            continue
        if u.get("str", 0) < 50:
            continue
        cost = rc.get(u["type"])
        if not cost:
            continue
        if not _cost_ok(stock, cost, RESERVE + 60 + mem.get("save", 0)):
            continue
        _spend(stock, cost)
        picked.append(u["id"])
        if len(picked) >= 30:
            break
    if picked:
        r = api.cmd("refit %s" % _ids_str(picked))
        if str(r).startswith("ok"):
            mem["refit_t"] = api.t


def _micro(api, mem):
    neutral = api.neutral_border or []
    nonrec = [u for u in api.units if u["type"] != "rec"]
    expand_n = sum(1 for u in api.units if u.get("expand"))
    if api.t < 360:
        cap = max(3, int(len(nonrec) * 0.6))
    else:
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


def _nb(x):
    try:
        return int(x)
    except Exception:
        try:
            return int(str(x).replace("~", "").replace("P", ""))
        except Exception:
            return None


def _depot(api, mem):
    if api.t < 72 or api.t - mem.get("depot_t", -99) < 72:
        return
    deps = api.depots or {}
    if len(deps) >= 3:
        return
    cap = api.capital
    capd = deps.get(cap) or deps.get(str(cap)) or {}
    if (capd.get("load", 0) or 0) <= 40:
        return
    if (api.stock or {}).get("res", 0) < RESERVE + 300:
        return
    provs = api.provs or {}
    dist = {cap: 0}
    frontier = [cap]
    while frontier:
        nxt = []
        for p in frontier:
            if dist[p] >= 6:
                continue
            pr = provs.get(p)
            if not pr:
                continue
            for x in pr.get("nbrs", []) or []:
                q = _nb(x)
                if q is None or q in dist:
                    continue
                dist[q] = dist[p] + 1
                nxt.append(q)
        frontier = nxt
    border = api.border or {}
    best = None
    for pid, d in dist.items():
        if d < 3 or d > 6:
            continue
        pr = provs.get(pid)
        if not pr or pr.get("owner") != "me" or not pr.get("supplied"):
            continue
        if pid in border or pid in deps or str(pid) in deps or pr.get("harsh"):
            continue
        score = (2.0 if pr.get("city") else 0.0) - abs(d - 4) * 0.5
        if best is None or score > best[0]:
            best = (score, pid)
    if best is None:
        return
    r = api.cmd("depot P%d" % best[1])
    if str(r).startswith("ok"):
        mem["depot_t"] = api.t
        if (capd.get("weight", 1) or 1) < 2:
            api.cmd("depot P%d 2" % cap)


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
                    cool[q] = t + 12
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
            if _pacted(api, q):
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
    else:
        cool[q] = t + 24
        api.count("prepare_refused")


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
        _trade(api, stock, mem)
    except Exception:
        pass
    try:
        _plan_save(api, mem)
    except Exception:
        mem["save"] = 0
    try:
        _economy(api, stock, mem)
    except Exception:
        pass
    try:
        _research(api, stock, mem)
    except Exception:
        pass
    try:
        _recruit(api, stock, api.units, mem)
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
        _refit(api, stock, mem)
    except Exception:
        pass
    try:
        _depot(api, mem)
    except Exception:
        pass
    mem["calls"] = mem.get("calls", 0) + 1
```

```feedback
Upkeep is the hidden limit: the purse ran dry around day 600 with 20k units, and api.income only shows the net figure. A per-unit upkeep forecast (api.budget days_left at a given army size) would help. Refit is blocked for most of the army because readiness stays low near the front; a refit queue that pulls units to the rear would be useful. Failed assaults that never reach the target are hard to diagnose from the review alone; a per-assault reason would help.
```

REVIEW: standard