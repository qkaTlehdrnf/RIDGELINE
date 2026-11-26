The last war ended second, with 446 provinces. Three things stood out. Neutral land ran out by about day 45, after which the game stalled. Assaults succeeded only 5 times in 113 attempts. Nearly 500 units were still on outdated models, and the bank held about 79k res, 15k steel and 22k manpower unspent. The revised policy spends that surplus with larger recruit batches and heavier armour, refits idle old-model units in the rear, and stops assaulting forts at level 3 or higher. The research order and expansion logic are unchanged. These are untested edits to a policy that has not been run since, so I cannot confirm the gains.

```python
PRIO = ["farming", "inf.weapons", "inf.protection", "medicine", "mining", "logistics",
        "discipline", "art.weapons", "arm.weapons", "fieldworks", "drill", "conscription",
        "industry", "staffwork", "drilling", "refining", "arm.protection", "inf.mobility",
        "mot.mobility", "eng.protection", "art.protection", "mtn.protection",
        "mec.weapons", "hvt.weapons"]

SHARE = {"inf": 0.32, "mtn": 0.06, "art": 0.12, "eng": 0.05, "grn": 0.07,
         "mot": 0.05, "arm": 0.08, "atg": 0.04, "mec": 0.05, "cav": 0.02, "hvt": 0.04}
ARMOUR = ("arm", "hvt", "mec")
EXPAND_OK = ("inf", "mil", "mtn", "grn", "mot", "cav", "mec")


def ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def idlist(lst):
    return ",".join(str(i) for i in lst)


def scan(api):
    if api.mem.get("armour"):
        return
    for v in api.enemy.values():
        s = str(v.get("types", ""))
        if any(a in s for a in ARMOUR):
            api.mem["armour"] = True
            return


def stock_ok(api, c, reserve_res):
    if api.res < c.get("res", 0) + reserve_res:
        return False
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) < c.get(k, 0):
            return False
    return True


def unit_ok(api, typ, reserve_res, reserve_mp):
    uc = api.unit_costs.get(typ)
    if not uc:
        return False
    if api.mp < uc.get("mp", 0) + reserve_mp:
        return False
    return stock_ok(api, uc, reserve_res)


def research(api):
    if len(api.research) >= 2:
        return
    busy = set(r[0] for r in api.research)
    for line in PRIO:
        t = api.tech.get(line)
        if not t or line in busy:
            continue
        if t.get("status") != "open":
            continue
        c = t.get("cost")
        if not c:
            continue
        if stock_ok(api, c, 80):
            api.cmd("research " + line)
            return


def refit(api, units):
    # Re-equip idle old-model units in the rear; refit costs 35% of price.
    if api.t - api.mem.get("refit_t", -99) < 12:
        return
    if not getattr(api, "old_units", 0):
        return
    cands = []
    for u in units:
        if not u.get("old") or u.get("state") != "ready" or u.get("path"):
            continue
        pv = api.provs.get(u.get("prov"), {})
        if pv.get("owner") != "me" or not u.get("supplied", True):
            continue
        cands.append(u)
    cands.sort(key=lambda u: -u.get("str", 0))
    rc_all = getattr(api, "refit_cost", {}) or {}
    spend = {"res": 0, "steel": 0, "oil": 0, "rare": 0}
    pick = []
    for u in cands[:40]:
        rc = rc_all.get(u["type"])
        if not rc:
            continue
        trial = {k: spend[k] + rc.get(k, 0) for k in spend}
        if api.res - trial["res"] < 3000:
            break
        ok = True
        for k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) - trial[k] < 0:
                ok = False
                break
        if not ok:
            continue
        spend = trial
        pick.append(u["id"])
    if pick:
        api.cmd("refit " + idlist(pick))
        api.mem["refit_t"] = api.t


def recruit(api, units):
    if api.income < 0:
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    if counts.get("rec", 0) < 2 and api.t - api.mem.get("rec_t", -99) >= 24 \
            and unit_ok(api, "rec", 20, 20):
        if api.cmd("recruit rec P%d" % api.capital).startswith("ok"):
            api.mem["rec_t"] = api.t
    total = len(units)
    surplus = api.res > 15000 and api.mp > 4000
    n_max = 6 if surplus else 3
    for _ in range(n_max):
        best, bd = None, 0.0
        for typ, sh in SHARE.items():
            if typ == "atg" and not api.mem.get("armour"):
                continue
            if typ == "hvt" and (not api.mem.get("armour") or api.income_by.get("rare", 0) <= 0):
                continue
            if typ == "arm" and api.income_by.get("steel", 0) <= 0:
                continue
            if typ == "mot" and api.income_by.get("oil", 0) <= 0:
                continue
            d = sh * (total + 1) - counts.get(typ, 0)
            if d > bd and unit_ok(api, typ, 25, 30):
                best, bd = typ, d
        if best is None:
            break
        r = api.cmd("recruit %s P%d" % (best, api.capital))
        if not r.startswith("ok"):
            break
        counts[best] = counts.get(best, 0) + 1
        total += 1


def attacks(api, units):
    plan = api.mem.setdefault("plan", {})
    byid = {u["id"]: u for u in units}

    # resolve running plans
    for tgt in list(plan.keys()):
        p = plan[tgt]
        alive = [i for i in p["ids"] if i in byid]
        pv = api.provs.get(tgt, {})
        if pv.get("owner") == "me" or not alive:
            del plan[tgt]
            continue
        mine = sum(byid[i].get("str", 0) for i in alive)
        en = api.enemy.get(tgt, {}).get("str", 0)
        if mine < 2.5 * en + 40:
            api.cmd("hold " + idlist(alive))
            del plan[tgt]
            continue
        bonus = max(byid[i].get("bonus", 0) for i in alive)
        if api.t - p["t"] >= 18 or bonus >= 30:
            api.cmd("move %s P%d" % (idlist(alive), tgt))
            del plan[tgt]
            continue
        p["ids"] = alive

    # start a new plan: enemy land only, concentrated stacks, strong ratio
    if len(plan) < 2:
        busy = set(i for p in plan.values() for i in p["ids"])
        by_prov = {}
        for u in units:
            if u["id"] in busy or u.get("path"):
                continue
            if u.get("type") == "rec":
                continue
            if u.get("plan", -1) not in (-1, None):
                continue
            if u.get("state") not in ("ready", "defending"):
                continue
            if u.get("str", 0) < 50 or u.get("rdy", 0) < 60:
                continue
            by_prov.setdefault(u["prov"], []).append(u)
        cands = set()
        for pid in by_prov:
            for q in api.provs.get(pid, {}).get("nbrs", []):
                cands.add(q)
        best = None
        for tgt in cands:
            if tgt in plan:
                continue
            tp = api.provs.get(tgt)
            if not tp or tp.get("owner") == "me":
                continue
            if tp.get("owner") != "enemy" and tgt not in api.enemy:
                continue  # neutral land is expand's job
            fort = tp.get("fort", 0) or 0
            if fort >= 3:
                continue  # assaults on level-3 forts have not succeeded
            adj = []
            for q in tp.get("nbrs", []):
                adj.extend(by_prov.get(q, []))
            if not adj:
                continue
            mine = sum(u.get("str", 0) for u in adj)
            if tgt in api.enemy:
                en = api.enemy[tgt].get("str", 0)
            else:
                en = 40  # assumed garrison, not seen
            need = 3.5 + 2.0 * fort
            if mine < need * en + 80:
                continue
            score = (mine / (en + 20.0)) / (1.0 + fort)
            if best is None or score > best[0]:
                best = (score, tgt, adj)
        if best:
            _, tgt, adj = best
            adj = sorted(adj, key=lambda u: -u.get("str", 0))[:16]
            api.cmd("prepare %s P%d" % (ids(adj), tgt))
            plan[tgt] = {"t": api.t, "ids": [u["id"] for u in adj]}

    return set(i for p in plan.values() for i in p["ids"])


def orders(api, units, busy):
    rec_idle = [u for u in units if u["type"] == "rec" and not u.get("explore")
                and not u.get("path") and u["id"] not in busy]
    if rec_idle and api.unexplored:
        api.cmd("explore " + ids(rec_idle))

    neutral = len(api.neutral_border)
    n_exp = sum(1 for u in units if u.get("expand"))
    want = min(neutral * 2, len(units) // 3)
    exp_l, fr_l = [], []
    for u in units:
        if u["type"] == "rec" or u["id"] in busy:
            continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("path"):
            continue
        if u.get("state") not in ("ready", "refitting"):
            continue
        if neutral and n_exp < want and u["type"] in EXPAND_OK:
            exp_l.append(u)
            n_exp += 1
        else:
            fr_l.append(u)
    if exp_l:
        api.cmd("expand " + ids(exp_l))
    if fr_l:
        api.cmd("front " + ids(fr_l))


def tick(api):
    units = list(api.units)
    try:
        scan(api)
    except Exception:
        pass
    try:
        research(api)
    except Exception:
        pass
    busy = set()
    try:
        busy = attacks(api, units)
    except Exception:
        busy = set(i for p in api.mem.get("plan", {}).values() for i in p["ids"])
    try:
        orders(api, units, busy)
    except Exception:
        pass
    try:
        refit(api, units)
    except Exception:
        pass
    try:
        recruit(api, units)
    except Exception:
        pass
```