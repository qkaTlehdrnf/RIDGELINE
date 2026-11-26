**Reasoning**

Last war we finished 2nd of 30 with about 444 provinces, but the record shows three problems. Assaults rarely succeed (5 of 137 taken), so the front stalls. We hoarded resources we never spent: about 70k res, 11k steel, 8k oil and 19k manpower sat idle at the end. And 504 of 1591 units were still on outdated models. The other factions also offered us pacts repeatedly, and we never answered them.

Changes in this version:
- **Spend the bank:** recruit up to 14 or 24 units per tick when resources and manpower are high, instead of 3 or 6.
- **Refit faster:** refit up to 80 candidates every 6 hours, down from 40 every 12 hours.
- **Research everything:** after PRIO, start any other open line, so the bank goes into upgrades.
- **Accept pacts:** accept pact offers from factions we have not already paired with. Attacks skip provinces owned by active pact partners, and a plan is dropped if a pact forms with its target's owner. This frees resources for expansion into neutral land.
- **Stricter assaults:** start plans only with units at readiness 70 or above.

I have not verified any of this against the engine. The letters block below invites the four factions that offered peace.

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


def active_pacts(api):
    out = set()
    for f, p in api.pacts.items():
        if isinstance(p, dict) and not p.get("broken_by"):
            out.add(f)
    return out


def diplomacy(api):
    if api.t - api.mem.get("dip_t", -99) < 6:
        return
    api.mem["dip_t"] = api.t
    pacts = active_pacts(api)
    for o in api.offers_in:
        if o.get("kind") == "pact" and o.get("frm") not in pacts:
            r = api.cmd("accept %s" % o.get("id"))
            if r.startswith("ok"):
                pacts.add(o.get("frm"))


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
    order = PRIO + [k for k in api.tech.keys() if k not in PRIO]
    for line in order:
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
    if api.t - api.mem.get("refit_t", -99) < 6:
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
    for u in cands[:80]:
        rc = rc_all.get(u["type"])
        if not rc:
            continue
        trial = {k: spend[k] + rc.get(k, 0) for k in spend}
        if api.res - trial["res"] < 5000:
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
    n_max = 3
    if api.res > 15000 and api.mp > 4000:
        n_max = 6
    if api.res > 30000 and api.mp > 6000:
        n_max = 14
    if api.res > 60000 and api.mp > 10000:
        n_max = 24
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
    pacts = active_pacts(api)

    # resolve running plans
    for tgt in list(plan.keys()):
        p = plan[tgt]
        alive = [i for i in p["ids"] if i in byid]
        pv = api.provs.get(tgt, {})
        if pv.get("owner") == "me" or not alive:
            del plan[tgt]
            continue
        if api.owner_name.get(tgt) in pacts:
            api.cmd("hold " + idlist(alive))
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

    # start a new plan: enemy land only (not pact partners), concentrated stacks
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
            if u.get("str", 0) < 50 or u.get("rdy", 0) < 70:
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
            if api.owner_name.get(tgt) in pacts:
                continue
            if tp.get("owner") != "enemy" and tgt not in api.enemy:
                continue  # neutral land is expand's job
            fort = tp.get("fort", 0) or 0
            if fort >= 3:
                continue
            adj = []
            for q in tp.get("nbrs", []):
                adj.extend(by_prov.get(q, []))
            if not adj:
                continue
            mine = sum(u.get("str", 0) for u in adj)
            if tgt in api.enemy:
                en = api.enemy[tgt].get("str", 0)
            else:
                en = 40
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
        diplomacy(api)
    except Exception:
        pass
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

```letters
to hindustan: Zhongyuan accepts your peace. We will take any pact you offer and keep our fire off your provinces; let us both grow on the open land instead of trading losses.
to siberia: Zhongyuan accepts your standing non-aggression offer. Our orders will take pacts and keep our fire off yours; we seek neutral land, not war with you.
to yamato: Zhongyuan agrees to peace. We will accept your pact and keep our fire off your provinces while both of us take free land.
to nusantara: Zhongyuan accepts your peace until the land race ends. We will take your pact offers and keep our fire off your provinces.
```