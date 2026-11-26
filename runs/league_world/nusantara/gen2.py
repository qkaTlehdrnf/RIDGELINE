# Nusantara standing orders, v3.
# Land is the score: expand while neutral land lasts, refit obsolete units from the rear,
# attack only with a large margin against low forts, and keep peace where offered.

BASE_MIX = [
    ("inf", 0.30), ("grn", 0.05), ("cav", 0.05), ("mtn", 0.05),
    ("art", 0.09), ("eng", 0.06), ("atg", 0.05), ("mot", 0.08),
    ("arm", 0.12), ("mec", 0.06), ("hvt", 0.03), ("mil", 0.04),
]

HEAVY_MIX = [
    ("inf", 0.26), ("grn", 0.05), ("cav", 0.04), ("mtn", 0.04),
    ("art", 0.12), ("eng", 0.05), ("atg", 0.07), ("mot", 0.11),
    ("arm", 0.14), ("mec", 0.07), ("hvt", 0.05),
]

RESEARCH = [
    "farming", "mining", "conscription", "drilling",
    "inf.protection", "arm.protection", "mec.protection",
    "arm.weapons", "art.weapons", "mot.mobility", "logistics",
    "medicine", "industry", "refining", "inf.weapons", "mot.weapons",
    "discipline", "drill", "staffwork", "fieldworks",
    "atg.weapons", "inf.mobility", "arm.mobility",
]

TERR_DEF = [("mountain", 2.0), ("hill", 1.5), ("forest", 1.25), ("plain", 1.0)]

MAX_WAVES = 2
WAVE_CAP = 16
MIN_READY = 80
MIN_BONUS = 25
MIN_RATIO = 3.0
MAX_FORT = 1
REFIT_PER_TICK = 40


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _diplomacy(api, mem):
    for o in list(api.offers_in):
        if o.get("kind") == "pact":
            api.cmd("accept %d" % o["id"])
            continue
        give = o.get("you_give", {}) or {}
        recv = o.get("they_give", {}) or {}
        if "res" in give and give.get("res", 0) <= 150 and any(k != "res" for k in recv):
            api.cmd("accept %d" % o["id"])
        else:
            api.cmd("reject %d" % o["id"])
    pt = mem.setdefault("pact_t", {})
    sent = set(o.get("to") for o in api.offers_out)
    for f in api.met:
        if f in api.pacts or f in sent:
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
        for k, v in cost.items():
            have = api.res if k == "res" else api.stock.get(k, 0)
            if have < v + 60:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research %s" % line)
        if r.startswith("ok"):
            return


def _refit(api):
    if api.res < 400 or api.old_units <= 0:
        return
    border = set(api.border.keys())
    budget = api.res - 300
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
        if pv.get("owner") != "me" or not pv.get("supplied") or u["prov"] in border:
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
    for typ, ids in by_type.items():
        api.cmd("refit %s" % _sel(ids))


def _mix(api):
    st = api.stock
    rich = st.get("steel", 0) >= 400 and st.get("oil", 0) >= 150
    return HEAVY_MIX if rich else BASE_MIX


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
        best, bestv = None, -1e9
        for typ, share in mix:
            if not can(typ, 60):
                continue
            deficit = share * (nonrec + 1) - counts.get(typ, 0)
            if deficit > bestv:
                best, bestv = typ, deficit
        if best is None or bestv < 0:
            break
        dr, dm = spend(best)
        res_left -= dr
        mp_left -= dm
        r = api.cmd("recruit %s P%d" % (best, api.capital))
        if not r.startswith("ok"):
            break
        counts[best] = counts.get(best, 0) + 1
        nonrec += 1


def _orders(api, mem):
    waves_ids = set()
    for w in mem.get("waves", {}).values():
        waves_ids.update(w["ids"])

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
        # Land is the score: claim neutral provinces first, hold the front otherwise.
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
            del waves[n]
            continue
        w["ids"] = ids
        if w["stage"] == "prep":
            avg_bonus = sum(alive[i].get("bonus", 0) for i in ids) / float(len(ids))
            avg_rdy = sum(alive[i].get("rdy", 0) for i in ids) / float(len(ids))
            if (avg_bonus >= MIN_BONUS and avg_rdy >= MIN_READY) or t - w["t0"] >= 24:
                api.cmd("move %s P%d" % (_sel(ids), int(n)))
                w["stage"] = "move"
                w["t0"] = t
        else:
            worn = sum(alive[i].get("str", 0) for i in ids) < 0.5 * max(1, len(ids)) * 100
            if all(not alive[i].get("path") for i in ids) and (t - w["t0"] >= 6 or worn):
                home = w.get("from", api.capital)
                if api.provs.get(home, {}).get("owner") != "me":
                    home = api.capital
                api.cmd("move %s P%d" % (_sel(ids), int(home)))
                del waves[n]

    if len(waves) >= MAX_WAVES or api.res < 60:
        return

    committed = set()
    for w in waves.values():
        committed.update(w["ids"])

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
    for p, lst in by_prov.items():
        pv = api.provs.get(p)
        if not pv or pv.get("owner") != "me":
            continue
        if (pv.get("stock", 0) or 0) < 30:
            continue
        s_total = sum(u.get("str", 0) for u in lst)
        if len(lst) < 3 or s_total < 200:
            continue
        for n in pv.get("nbrs", []):
            if n in waves:
                continue
            nv = api.provs.get(n)
            if not nv or nv.get("owner") != "enemy":
                continue
            info = api.enemy.get(n)
            if not info:
                continue
            fort = nv.get("fort", 0) or 0
            if fort > MAX_FORT:
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
            elev = (nv.get("elev", 0) or 0) - (pv.get("elev", 0) or 0)
            s_eff = s_total * (0.9 ** max(0, elev)) * (1.08 ** max(0, -elev))
            if s_eff < MIN_RATIO * e_eff + 80:
                continue
            v = s_eff / (e_eff + 1.0)
            if v > bestv:
                best, bestv = (p, n, lst), v

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


def tick(api):
    mem = api.mem
    for fn in (
        lambda: _diplomacy(api, mem),
        lambda: _research(api),
        lambda: _refit(api),
        lambda: _recruit(api),
        lambda: _attacks(api, mem),
        lambda: _orders(api, mem),
    ):
        try:
            fn()
        except Exception:
            pass
    mem["calls"] = mem.get("calls", 0) + 1
