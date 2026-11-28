The last war ended in elimination. Recruitment was refused 276 times for lack of steel, and the four depots were lost one by one, taking the whole treasury with them. This revision makes three changes. Recruitment stops retrying a unit type for 48 hours after a refusal. The treasury gets spread over several interior depots, away from enemy borders, so one loss cannot wipe it out. Research keeps a larger reserve so units stay affordable. Attack and front logic stay as before, since they were not the main failure.

```python
PRIO = ["farming", "inf.weapons", "inf.protection", "medicine", "mining", "logistics",
        "discipline", "art.weapons", "arm.weapons", "fieldworks", "drill", "conscription",
        "industry", "staffwork", "drilling", "refining", "arm.protection", "inf.mobility",
        "mot.mobility", "eng.protection", "art.protection", "mtn.protection",
        "mec.weapons", "hvt.weapons"]

DISC = ["iron_working", "horse_riding", "masonry", "roads", "siege_engines", "galleys",
        "crop_rotation", "stirrup", "pikes_crossbows", "banking", "castles", "trebuchet",
        "sailing", "hillmen", "gunpowder", "matchlock", "steam_power", "rifling",
        "grenadiers", "dragoons", "steel_guns", "field_engineering", "railways",
        "combustion", "machine_guns", "tanks", "flight", "heavy_artillery",
        "mechanisation", "anti_tank_guns", "assault_rifles", "heavy_armour",
        "rocket_artillery", "jet_engines", "navigation", "ships_of_the_line", "ironclads",
        "bombers", "submarines", "dreadnoughts", "carriers", "composite_armour",
        "rocketry", "satellites", "ballistic_missiles", "guided_weapons"]

SHARE = {"inf": 0.26, "mil": 0.03, "cav": 0.03, "mtn": 0.05, "art": 0.12, "eng": 0.04,
         "grn": 0.07, "mot": 0.05, "arm": 0.09, "atg": 0.03, "mec": 0.05, "hvt": 0.04,
         "rkt": 0.03}
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


def blocked(api, typ):
    return api.mem.get("blk", {}).get(typ, -1) > api.t


def block(api, typ, hours=48):
    api.mem.setdefault("blk", {})[typ] = api.t + hours


def unit_ok(api, typ, reserve_res, reserve_mp):
    if blocked(api, typ):
        return False
    uc = api.unit_costs.get(typ)
    if not uc:
        return False
    if api.mp < uc.get("mp", 0) + reserve_mp:
        return False
    return stock_ok(api, uc, reserve_res)


def research(api):
    tree = api.tree or {}
    running = len(api.research or [])
    if running >= 2:
        return
    n_disc = sum(1 for d in tree.values() if d.get("status") == "researching")
    if n_disc < 2:
        for name in DISC:
            d = tree.get(name)
            if not d or d.get("status") != "open":
                continue
            c = d.get("cost") or {}
            if api.res >= c.get("res", 0) + 2000:
                if api.cmd("research " + name).startswith("ok"):
                    running += 1
                    break
    if running >= 2 or api.res < 4000:
        return
    busy = set(r[0] for r in (api.research or []))
    order = PRIO + [k for k in api.tech.keys() if k not in PRIO]
    for line in order:
        if running >= 2:
            return
        t = api.tech.get(line)
        if not t or line in busy or t.get("status") != "open":
            continue
        c = t.get("cost")
        if not c:
            continue
        if stock_ok(api, c, 2000):
            if api.cmd("research " + line).startswith("ok"):
                running += 1
                busy.add(line)


def economy(api):
    if api.t - api.mem.get("econ_t", -99) < 12:
        return
    if api.res < 3000 or api.income < 20:
        return
    eco = api.economy if isinstance(api.economy, dict) else {}
    works = eco.get("works", []) or []
    if len(works) >= 4:
        return
    busy = set()
    for w in works:
        try:
            busy.add(w[1])
        except Exception:
            pass
    cands = []
    for p in eco.get("provs", []) or []:
        try:
            pid = p.get("prov")
            if pid is None or pid in busy:
                continue
            y = p.get("yield_now", 0) or 0
            bonus = 5.0 if p.get("city") else 0.0
            dev = p.get("dev", 0) or 0
            room = p.get("room", 0) or 0
            infra = p.get("infra", 0) or 0
            if p.get("can_dev") and dev + 1 <= room and dev < 6:
                cands.append((y + bonus + 2.0, "develop", pid))
            if p.get("can_infra") and infra < 3 and api.stock.get("steel", 0) >= 40:
                cands.append((y + bonus, "build", pid))
        except Exception:
            continue
    cands.sort(reverse=True)
    tries = 0
    for _, verb, pid in cands:
        if tries >= 2:
            break
        tries += 1
        r = api.cmd("%s P%d" % (verb, pid))
        if r.startswith("ok"):
            api.mem["econ_t"] = api.t
            api.count(verb + "_ordered")
            return


def interior(api, pid, pv):
    # own, supplied, no enemy next door, not a border or harsh province
    if pv.get("owner") != "me" or not pv.get("supplied", False):
        return False
    if pv.get("harsh") or pv.get("terrain") == "mountain":
        return False
    if pid in api.border:
        return False
    for q in pv.get("nbrs", []) or []:
        qv = api.provs.get(q, {})
        if qv.get("owner") == "enemy":
            return False
    return True


def depots(api):
    # Spread the treasury over several interior depots so one loss cannot take it all.
    if api.t - api.mem.get("depot_t", -99) < 48:
        return
    deps = api.depots or {}
    if not deps or api.res < 4000:
        return
    overloaded = any((d.get("load", 0) or 0) > 25 for d in deps.values())
    want_more = len(deps) < 4 and api.res >= 6000
    if not (overloaded or want_more) or len(deps) >= 6:
        return
    cands = []
    for pid, pv in api.provs.items():
        if pid in deps or not interior(api, pid, pv):
            continue
        score = (pv.get("stock", 0) or 0) + (300 if pv.get("city") else 0)
        cands.append((score, pid))
    cands.sort(reverse=True)
    for _, pid in cands[:15]:
        if all(len(api.path(pid, d) or []) >= 4 for d in deps):
            r = api.cmd("depot P%d 1" % pid)
            if r.startswith("ok"):
                api.mem["depot_t"] = api.t
                api.count("depot_opened")
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
    for u in cands[:400]:
        if len(pick) >= 150:
            break
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


def try_recruit(api, typ):
    r = api.cmd("recruit %s P%d" % (typ, api.capital))
    if r.startswith("ok"):
        return True
    # a refusal (usually missing steel/oil/rare the depot does not hold): stop asking for a while
    block(api, typ, 48)
    return False


def recruit(api, units):
    if api.income < 0:
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    if counts.get("rec", 0) < 2 and api.t - api.mem.get("rec_t", -99) >= 24 \
            and unit_ok(api, "rec", 20, 20):
        if try_recruit(api, "rec"):
            api.mem["rec_t"] = api.t
    total = len(units)
    reserve_res = 5000
    for _ in range(40):
        best, bd = None, 0.0
        for typ, sh in SHARE.items():
            if typ == "atg" and not api.mem.get("armour"):
                continue
            if typ == "hvt" and (not api.mem.get("armour") or api.income_by.get("rare", 0) <= 0):
                continue
            if typ == "arm" and api.income_by.get("steel", 0) <= 0:
                continue
            if typ == "mec" and api.income_by.get("steel", 0) <= 0:
                continue
            if typ == "mot" and api.income_by.get("oil", 0) <= 0:
                continue
            d = sh * (total + 1) - counts.get(typ, 0)
            if d > bd and unit_ok(api, typ, reserve_res, 800):
                best, bd = typ, d
        if best is None:
            break
        if not try_recruit(api, best):
            continue
        counts[best] = counts.get(best, 0) + 1
        total += 1


def attacks(api, units):
    plan = api.mem.setdefault("plan", {})
    byid = {u["id"]: u for u in units}
    pacts = active_pacts(api)

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
        if mine < 3.0 * en + 60:
            api.cmd("hold " + idlist(alive))
            del plan[tgt]
            continue
        bonus = max(byid[i].get("bonus", 0) for i in alive)
        if api.t - p["t"] >= 18 or bonus >= 30:
            api.cmd("move %s P%d" % (idlist(alive), tgt))
            del plan[tgt]
            continue
        p["ids"] = alive

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
                continue
            fort = tp.get("fort", 0) or 0
            if fort >= 3:
                continue
            adj = []
            for q in tp.get("nbrs", []):
                adj.extend(by_prov.get(q, []))
            if not adj:
                continue
            mine = sum(u.get("str", 0) for u in adj)
            en = api.enemy[tgt].get("str", 0) if tgt in api.enemy else 40
            need = 4.0 + 2.0 * fort
            if mine < need * en + 100:
                continue
            score = (mine / (en + 20.0)) / (1.0 + fort)
            if best is None or score > best[0]:
                best = (score, tgt, adj)
        if best:
            _, tgt, adj = best
            adj = sorted(adj, key=lambda u: -u.get("str", 0))[:24]
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
    try:
        economy(api)
    except Exception:
        pass
    try:
        depots(api)
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
to haedong: Zhongyuan keeps the pact and wants fair trade. Our roads and markets can join; offer access if you agree.
```

REVIEW: standard