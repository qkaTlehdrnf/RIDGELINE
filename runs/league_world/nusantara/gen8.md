**Reasoning**

The war was a solid result (17th of 31, 97 provinces), but the review shows three problems I can fix without changing the core strategy:

1. **Unused rubber.** Rubber piled up to 4,674 while steel and oil ran short. The research order front-loads steel- and oil-heavy lines, and rubber-cheap lines (logistics, medicine, drill, mobility) come late. I move the rubber-friendly lines earlier.
2. **Sparse wave data.** Assaults succeeded 6 of 14 times, and the review has no counters for why waves launched or aborted. I add `api.count` tallies so the next review shows which conditions gate attacks.
3. **Tangled dispatch.** The `tick` wrapper special-cases each function. I simplify it so every stage is isolated and exceptions are logged to tallies rather than silently swallowed.

I keep the expansion, pact acceptance, refit-before-recruit, depot, and prepared-wave logic, since those worked. I make no claims about the unverified rule changes.

```python
# Nusantara standing orders, v9.
# Land is the score. Expand while neutral land lasts, hold a strong front,
# accept peace offers, keep the army current (refit before recruiting),
# open forward depots early, and attack with prepared, superior waves
# against low, lightly fortified, non-uphill targets.
# Research favours lines that spend the rubber we actually have.

BASE_MIX = [
    ("inf", 0.30), ("grn", 0.05), ("cav", 0.05), ("mtn", 0.05),
    ("art", 0.10), ("eng", 0.07), ("atg", 0.05), ("mot", 0.08),
    ("arm", 0.11), ("mec", 0.06), ("hvt", 0.03), ("mil", 0.04),
]

HEAVY_MIX = [
    ("inf", 0.26), ("grn", 0.05), ("cav", 0.04), ("mtn", 0.04),
    ("art", 0.13), ("eng", 0.06), ("atg", 0.07), ("mot", 0.11),
    ("arm", 0.13), ("mec", 0.07), ("hvt", 0.05),
]

# Rubber-heavy and cheap lines come first; they were idle in the last war.
RESEARCH = [
    "farming", "mining", "drilling", "logistics", "medicine",
    "inf.protection", "arm.protection", "mec.protection", "drill",
    "arm.weapons", "art.weapons", "mot.mobility", "conscription",
    "mot.weapons", "inf.weapons", "refining", "industry", "discipline",
    "staffwork", "fieldworks", "atg.weapons", "inf.mobility", "arm.mobility",
]

TERR_DEF = [("mountain", 2.0), ("hill", 1.5), ("forest", 1.25), ("plain", 1.0)]

MAX_WAVES = 3
WAVE_CAP = 20
MIN_READY = 70
MIN_BONUS = 15
PREP_MIN_H = 12
PREP_ABORT_H = 40
MIN_RATIO = 2.5
MAX_FORT = 1
REFIT_PER_TICK = 60
REFIT_RESERVE = 80
DEPOT_LOAD = 30
DEPOT_MIN_RES = 200
MAX_DEPOTS = 4


def _count(api, name, n=1):
    try:
        api.count(name, n)
    except Exception:
        pass


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _bonus(u):
    # plan bonus may be a fraction (0-1) or a percent (0-50)
    b = float(u.get("bonus", 0) or 0)
    if b <= 2.0:
        b *= 100.0
    return b


def _neighbour_factions(api):
    nb = set()
    for p, pv in api.provs.items():
        if pv.get("owner") != "me":
            continue
        for n in pv.get("nbrs", []):
            f = api.owner_name.get(n)
            if f:
                nb.add(f)
    return nb


def _diplomacy(api, mem):
    # accept pacts; take cheap offers that pay us in something other than res
    for o in list(api.offers_in):
        if o.get("kind") == "pact":
            api.cmd("accept %d" % o["id"])
            continue
        give = o.get("you_give", {}) or {}
        recv = o.get("they_give", {}) or {}
        cheap = give.get("res", 0) <= 150
        pays = any(k != "res" for k in recv)
        if cheap and pays:
            api.cmd("accept %d" % o["id"])
        else:
            api.cmd("reject %d" % o["id"])

    # propose pacts only to factions we do not border
    pt = mem.setdefault("pact_t", {})
    sent = [o.get("to") for o in api.offers_out]
    nb = _neighbour_factions(api)
    for f in api.met:
        if f in api.pacts or f in sent or f in nb:
            continue
        if api.t - pt.get(f, -999) < 96:
            continue
        pt[f] = api.t
        api.cmd("offer %s pact 240" % f)


def _research(api):
    if len(api.research) >= 2:
        return
    for line in RESEARCH:
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        cost = t.get("cost")
        if not cost:
            continue
        ok = True
        for k in cost:
            have = api.res if k == "res" else api.stock.get(k, 0)
            if have < cost[k] + 60:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research %s" % line)
        if r.startswith("ok"):
            return


def _depots(api, mem):
    if api.res < DEPOT_MIN_RES or len(api.depots) >= MAX_DEPOTS:
        return
    if api.t - mem.get("depot_t", -999) < 48:
        return
    overloaded = any((d.get("load", 0) or 0) > DEPOT_LOAD for d in api.depots.values())
    if not overloaded and len(api.depots) >= 1 and api.t % 96 != 0:
        return
    border = api.border
    best = None
    bestv = 0
    for p, pv in api.provs.items():
        if p in api.depots or p == api.capital:
            continue
        if pv.get("owner") != "me" or not pv.get("supplied"):
            continue
        v = (2 if pv.get("city") else 0) + (1 if p in border else 0)
        if v > bestv:
            best = p
            bestv = v
    if best is None:
        return
    r = api.cmd("depot P%d 1" % best)
    if r.startswith("ok"):
        mem["depot_t"] = api.t
        _count(api, "depot_opened")


def _refit(api):
    if api.old_units <= 0:
        return
    budget = api.res - REFIT_RESERVE
    if budget <= 0:
        return
    stock = dict(api.stock)
    by_type = {}
    n = 0
    for u in api.units:
        if n >= REFIT_PER_TICK:
            break
        if not u.get("old") or u["type"] == "rec":
            continue
        if u.get("path") or u.get("state") != "ready" or u.get("plan", -1) >= 0:
            continue
        pv = api.provs.get(u["prov"], {})
        if pv.get("owner") != "me" or not pv.get("supplied"):
            continue
        rc = api.refit_cost.get(u["type"], {})
        if rc.get("res", 0) > budget:
            continue
        if any(stock.get(k, 0) < rc.get(k, 0) for k in ("steel", "oil", "rare")):
            continue
        budget -= rc.get("res", 0)
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - rc.get(k, 0)
        by_type.setdefault(u["type"], []).append(u["id"])
        n += 1
    for typ in by_type:
        api.cmd("refit %s" % _sel(by_type[typ]))
        _count(api, "refit_" + typ, len(by_type[typ]))


def _mix(api):
    st = api.stock
    if st.get("steel", 0) >= 250 and st.get("oil", 0) >= 100:
        return HEAVY_MIX
    return BASE_MIX


def _recruit(api):
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    nonrec = sum(v for k, v in counts.items() if k != "rec")

    res_left = api.res
    mp_left = api.mp
    stock_left = dict(api.stock)

    def can(typ, reserve):
        c = api.costs.get(typ)
        if not c:
            return False
        if res_left - c[0] < reserve or mp_left < c[1]:
            return False
        uc = api.unit_costs.get(typ, {})
        for k in ("steel", "oil", "rare"):
            if stock_left.get(k, 0) < uc.get(k, 0):
                return False
        return True

    def spend(typ):
        c = api.costs.get(typ)
        uc = api.unit_costs.get(typ, {})
        for k in ("steel", "oil", "rare"):
            stock_left[k] = stock_left.get(k, 0) - uc.get(k, 0)
        return c[0], c[1]

    if counts.get("rec", 0) < 3 and can("rec", 40):
        dr, dm = spend("rec")
        res_left -= dr
        mp_left -= dm
        r = api.cmd("recruit rec P%d" % api.capital)
        counts["rec"] = counts.get("rec", 0) + 1
        if not r.startswith("ok"):
            return

    mix = _mix(api)
    for _ in range(4):
        best = None
        bestv = -1e9
        for typ, share in mix:
            if not can(typ, 60):
                continue
            deficit = share * (nonrec + 1) - counts.get(typ, 0)
            if deficit > bestv:
                best = typ
                bestv = deficit
        if best is None or bestv < 0:
            break
        dr, dm = spend(best)
        res_left -= dr
        mp_left -= dm
        r = api.cmd("recruit %s P%d" % (best, api.capital))
        if not r.startswith("ok"):
            _count(api, "recruit_refused")
            break
        counts[best] = counts.get(best, 0) + 1
        nonrec += 1
        _count(api, "recruit_" + best)


def _orders(api, mem):
    waves_ids = []
    for w in mem.get("waves", {}).values():
        waves_ids.extend(w["ids"])

    scouts = []
    idle = []
    for u in api.units:
        if u["type"] == "rec":
            if not u.get("path") and not u.get("explore") and u["id"] not in waves_ids:
                scouts.append(u["id"])
            continue
        if u.get("path") or u["id"] in waves_ids:
            continue
        if u.get("plan", -1) >= 0:
            continue
        if u.get("front") or u.get("expand") or u.get("explore"):
            continue
        idle.append(u["id"])

    if scouts:
        api.cmd("explore %s" % _sel(scouts))

    if idle:
        if api.neutral_border:
            api.cmd("expand %s" % _sel(idle))
        else:
            api.cmd("front %s" % _sel(idle))


def _attacks(api, mem):
    t = api.t
    waves = mem.setdefault("waves", {})
    alive = {u["id"]: u for u in api.units}

    for n in list(waves.keys()):
        w = waves[n]
        ids = [i for i in w["ids"] if i in alive]
        pv = api.provs.get(int(n), {})
        if not ids or pv.get("owner") == "me":
            if pv.get("owner") == "me":
                _count(api, "wave_taken")
            del waves[n]
            continue
        w["ids"] = ids
        if w["stage"] == "prep":
            tot_b = 0.0
            tot_r = 0.0
            for i in ids:
                tot_b += _bonus(alive[i])
                tot_r += alive[i].get("rdy", 0)
            avg_bonus = tot_b / float(len(ids))
            avg_rdy = tot_r / float(len(ids))
            waited = t - w["t0"]
            go = (avg_bonus >= MIN_BONUS and avg_rdy >= MIN_READY) or \
                 (waited >= PREP_MIN_H and avg_rdy >= MIN_READY)
            if go:
                api.cmd("move %s P%d" % (_sel(ids), int(n)))
                w["stage"] = "move"
                w["t0"] = t
                _count(api, "wave_launch")
            elif waited >= PREP_ABORT_H:
                home = w.get("from", api.capital)
                if api.provs.get(home, {}).get("owner") != "me":
                    home = api.capital
                api.cmd("move %s P%d" % (_sel(ids), int(home)))
                del waves[n]
                _count(api, "wave_abort_prep")
        else:
            tot_s = 0.0
            moving = False
            for i in ids:
                tot_s += alive[i].get("str", 0)
                if alive[i].get("path"):
                    moving = True
            worn = tot_s < 0.5 * max(1, len(ids)) * 100
            if (not moving) and (t - w["t0"] >= 6 or worn):
                home = w.get("from", api.capital)
                if api.provs.get(home, {}).get("owner") != "me":
                    home = api.capital
                api.cmd("move %s P%d" % (_sel(ids), int(home)))
                del waves[n]
                _count(api, "wave_worn" if worn else "wave_pulled_back")

    if len(waves) >= MAX_WAVES or api.res < 60:
        return

    committed = []
    for w in waves.values():
        committed.extend(w["ids"])

    by_prov = {}
    for u in api.units:
        if u["type"] == "rec" or u["id"] in committed:
            continue
        if u.get("path") or u.get("state") != "ready":
            continue
        if u.get("rdy", 0) < MIN_READY:
            continue
        by_prov.setdefault(u["prov"], []).append(u)

    best = None
    bestv = 0.0
    for p in by_prov:
        lst = by_prov[p]
        pv = api.provs.get(p)
        if not pv or pv.get("owner") != "me":
            continue
        if (pv.get("stock", 0) or 0) < 30:
            continue
        s_total = sum(u.get("str", 0) for u in lst)
        if len(lst) < 4 or s_total < 250:
            continue
        for n in pv.get("nbrs", []):
            if n in waves:
                continue
            nv = api.provs.get(n)
            if not nv or nv.get("owner") != "enemy":
                continue
            if api.owner_name.get(n) in api.pacts:
                continue
            info = api.enemy.get(n)
            if not info:
                continue
            fort = nv.get("fort", 0) or 0
            if fort > MAX_FORT:
                continue
            elev = (nv.get("elev", 0) or 0) - (pv.get("elev", 0) or 0)
            if elev > 0:
                continue
            e = info.get("str", 0)
            terr = str(nv.get("terrain", ""))
            dm = 1.0
            for k, v in TERR_DEF:
                if k in terr:
                    dm = v
                    break
            if nv.get("city"):
                dm += 0.25
            e_eff = e * dm * (1.0 + 0.25 * fort)
            s_eff = s_total
            if elev < 0:
                s_eff = s_total * (1.08 ** (-elev))
            if s_eff < MIN_RATIO * e_eff + 120:
                continue
            v = s_eff / (e_eff + 1.0)
            if v > bestv:
                best = (p, n, lst)
                bestv = v

    if best is None:
        return
    p, n, lst = best
    lst = sorted(lst, key=lambda u: -u.get("str", 0))[:WAVE_CAP]
    ids = [u["id"] for u in lst]
    sel = _sel(ids)
    api.cmd("group w%d %s" % (int(n), sel))
    r = api.cmd("prepare %s P%d" % (sel, int(n)))
    if r.startswith("ok"):
        waves[n] = {"ids": ids, "stage": "prep", "t0": t, "from": p}
        _count(api, "wave_prepare")


def tick(api):
    mem = api.mem
    try:
        _diplomacy(api, mem)
    except Exception:
        _count(api, "err_diplomacy")
    try:
        _research(api)
    except Exception:
        _count(api, "err_research")
    try:
        _depots(api, mem)
    except Exception:
        _count(api, "err_depots")
    try:
        _refit(api)
    except Exception:
        _count(api, "err_refit")
    try:
        _recruit(api)
    except Exception:
        _count(api, "err_recruit")
    try:
        _attacks(api, mem)
    except Exception:
        _count(api, "err_attacks")
    try:
        _orders(api, mem)
    except Exception:
        _count(api, "err_orders")
    mem["calls"] = mem.get("calls", 0) + 1
```

```feedback
Rubber piled up unused (4,674 at war end) while steel and oil ran short; a per-line view of which resources each line can use, given current stock, would make such mismatches easier to spot. A "q army" field for the tick a wave was blocked (ratio, readiness, stock) would help tune attacks without guessing. api.count works but is capped at 60 names and reviews only show totals; per-tick timelines of tallies would be useful. The `front` standing order reshuffles units, which costs readiness; an explicit "garrison here" order would help.
```

REVIEW: standard