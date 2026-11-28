RES_KEEP = 90
MAX_UNITS = 2600
ATTACK_STR = 50
ATTACK_RDY = 75
MAX_PLANS = 6
PREP_HOURS = 30
MIN_RATIO = 2.0
MIN_ATTACKERS = 3
HEAVY_FORT = 3
HEAVY_FORT_ATTACKERS = 6
P_MIN = 0.6
REFIT_BELOW = 35
REFIT_DONE = 85
OFFER_EVERY = 72
PACT_HOURS = 240
MAX_DEPOTS = 4
DEV_RES_FLOOR = 300
MAX_WORKS = 2
MIN_DAYS_LEFT = 20

DISC_ORDER = ["iron_working", "horse_riding", "masonry", "roads", "siege_engines",
              "crop_rotation", "pikes_crossbows", "stirrup", "hillmen", "trebuchet",
              "castles", "banking", "gunpowder", "matchlock", "steam_power",
              "rifling", "steel_guns", "field_engineering", "combustion",
              "machine_guns", "tanks", "heavy_artillery", "mechanisation",
              "assault_rifles", "rocket_artillery", "heavy_armour", "anti_tank_guns"]
DISC_SKIP = set(["galleys", "navigation", "sailing", "ships_of_the_line", "ironclads",
                 "dreadnoughts", "submarines", "carriers", "flight", "bombers",
                 "jet_engines", "rocketry", "satellites", "ballistic_missiles",
                 "guided_weapons"])

TECH_ORDER = ["farming", "inf.weapons", "inf.protection", "industry",
              "mining", "conscription", "logistics", "medicine", "drill",
              "discipline", "fieldworks", "staffwork", "art.weapons",
              "arm.weapons", "inf.mobility", "arm.protection"]

WEIGHT = {"inf": 0.18, "mil": 0.04, "rec": 0.02, "cav": 0.08, "mtn": 0.08,
          "mot": 0.14, "arm": 0.18, "art": 0.12, "mec": 0.08, "eng": 0.04,
          "atg": 0.04, "grn": 0.06, "hvt": 0.04, "rkt": 0.03}

LINE_TYPES = ("inf", "mtn", "arm", "mot", "mec", "grn", "hvt", "art", "eng",
              "atg", "cav", "mil")
DOWN = {0: 1.0, 1: 1.0, 2: 1.5, 3: 2.0}
BAD_STATES = ("preparing", "assault", "digging", "pinned", "routing")


def _sig(x):
    if x > 30:
        x = 30.0
    if x < -30:
        x = -30.0
    return 1.0 / (1.0 + math.exp(-x))


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _chunks(xs, n):
    return [xs[i:i + n] for i in range(0, len(xs), n)]


def _num(x, default):
    if isinstance(x, dict):
        return x.get("res", default)
    if isinstance(x, (int, float)):
        return x
    return default


def _pact_on(api, f):
    p = api.pacts.get(f)
    if not p:
        return False
    ends = p.get("ends")
    return ends is None or ends > api.t


def _fort_eff(fort, adj):
    n = float(len(adj)) or 1.0
    art = sum(1 for u in adj if u["type"] == "art") / n
    eng = sum(1 for u in adj if u["type"] == "eng") / n
    return max(0.0, fort * (1.0 - 0.6 * art - 0.4 * eng))


def _can_grow(api):
    bud = api.budget or {}
    dl = bud.get("days_left")
    return dl is None or dl > MIN_DAYS_LEFT


def _diplomacy(api, m):
    for o in api.offers_in:
        if o.get("kind") == "pact":
            api.cmd("accept %d" % o["id"])
    offered = m.setdefault("offered", {})
    for f in api.met:
        if _pact_on(api, f):
            continue
        if api.t - offered.get(f, -10000) < OFFER_EVERY:
            continue
        offered[f] = api.t
        api.cmd("offer %s pact %d" % (f, PACT_HOURS))


def _depots(api, t):
    if t % 48 != 0:
        return
    d = api.depots or {}
    if not d or len(d) >= MAX_DEPOTS:
        return
    if any((v.get("opens_in") or 0) > 0 for v in d.values()):
        return
    hot = False
    for v in d.values():
        cap = v.get("capacity") or 60
        if (v.get("load") or 0) > 0.8 * cap:
            hot = True
    if not hot:
        return
    if api.res < 150 + RES_KEEP:
        return
    best = None
    bestscore = -1
    checked = 0
    for p, pr in api.provs.items():
        if pr.get("owner") != "me" or p in d or p == api.capital:
            continue
        if not pr.get("supplied"):
            continue
        checked += 1
        if checked > 60:
            break
        path = api.path(api.capital, p)
        if not path:
            continue
        steps = len(path) - 1
        if steps < 3 or steps > 8:
            continue
        score = steps + (2 if pr.get("city") else 0)
        if score > bestscore:
            bestscore = score
            best = p
    if best is not None:
        api.cmd("depot P%d 1" % best)


def _economy(api, t):
    if t % 24 != 0:
        return
    econ = api.economy or {}
    works = econ.get("works") or []
    if len(works) >= MAX_WORKS:
        return
    if api.res < DEV_RES_FLOOR + RES_KEEP:
        return
    for pr in econ.get("provs") or []:
        if (pr.get("room") or 0) <= 0:
            continue
        if pr.get("dev_cost") is None:
            continue
        cost = _num(pr.get("dev_cost"), 60)
        if api.res - cost < RES_KEEP + 150:
            continue
        api.cmd("develop P%d" % pr["prov"])
        break
    if api.stock.get("steel", 0) >= 80 and api.res >= DEV_RES_FLOOR + RES_KEEP:
        for pr in econ.get("provs") or []:
            if (pr.get("infra") or 0) >= 3:
                continue
            if pr.get("infra_cost") is None:
                continue
            if (pr.get("yield_now") or 0) <= 0:
                continue
            api.cmd("build P%d" % pr["prov"])
            break


def _afford(api, kind, spent):
    uc = api.unit_costs.get(kind)
    if not uc:
        return False
    if api.res < uc.get("res", 0) + RES_KEEP + spent.get("res", 0):
        return False
    if api.mp < uc.get("mp", 0) + spent.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) < uc.get(k, 0) + spent.get(k, 0):
            return False
    return True


def _book(api, spent, kind):
    uc = api.unit_costs.get(kind, {})
    for k in ("res", "mp", "steel", "oil", "rare"):
        spent[k] = spent.get(k, 0) + uc.get(k, 0)


def _recruit(api, units):
    if not _can_grow(api):
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    n_units = len(units)
    spent = {}
    made = 0
    for _ in range(8):
        if n_units + made >= MAX_UNITS:
            break
        best = None
        if counts.get("rec", 0) < 2 and _afford(api, "rec", spent):
            best = "rec"
        else:
            total = n_units + made + 1
            bestdef = -1e9
            for k, w in WEIGHT.items():
                if not _afford(api, k, spent):
                    continue
                d = w * total - counts.get(k, 0)
                if d > bestdef:
                    bestdef = d
                    best = k
        if best is None:
            break
        _book(api, spent, best)
        counts[best] = counts.get(best, 0) + 1
        made += 1
        api.cmd("recruit %s 1 P%d" % (best, api.capital))


def _refit(api, units, skip):
    spent = {}
    picks = []
    for u in units:
        if not u.get("old") or u.get("path") or u["id"] in skip:
            continue
        if u["type"] == "rec" or u.get("state") not in ("ready", None):
            continue
        if not u.get("supplied", False):
            continue
        if u.get("front") is None and u.get("fighting"):
            continue
        rc = api.refit_cost.get(u["type"]) or {}
        if api.res - spent.get("res", 0) < rc.get("res", 0) + RES_KEEP:
            continue
        ok = True
        for k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) - spent.get(k, 0) < rc.get(k, 0):
                ok = False
        if not ok:
            continue
        for k in ("res", "steel", "oil", "rare"):
            spent[k] = spent.get(k, 0) + rc.get(k, 0)
        picks.append(u["id"])
        if len(picks) >= 40:
            break
    for ch in _chunks(picks, 20):
        api.cmd("refit %s" % _sel(ch))


def _plan(api, m, t, free, byid):
    keep = []
    for pl in m["plans"]:
        alive = [i for i in pl["ids"] if i in byid]
        if not alive:
            continue
        if t - pl["t0"] >= PREP_HOURS:
            api.cmd("move %s P%d" % (_sel(alive), pl["T"]))
            continue
        keep.append({"T": pl["T"], "t0": pl["t0"], "ids": alive})
    if len(keep) >= MAX_PLANS:
        m["plans"] = keep
        return

    busy_T = set(p["T"] for p in keep)
    used = set(i for p in keep for i in p["ids"])
    byprov = {}
    for u in free:
        if u["id"] in used or u["type"] == "rec":
            continue
        if u.get("str", 0) < ATTACK_STR or u.get("rdy", 0) < ATTACK_RDY:
            continue
        byprov.setdefault(u["prov"], []).append(u)
    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")

    cands = []
    for T, e in api.enemy.items():
        if T in mine or T in busy_T:
            continue
        pr = api.provs.get(T)
        if not pr:
            continue
        owner = api.owner_name.get(T)
        if owner is not None and _pact_on(api, owner):
            continue
        nbrs = pr.get("nbrs", [])
        if not any(n in mine for n in nbrs):
            continue
        adj = []
        for n in nbrs:
            lst = byprov.get(n)
            if lst:
                adj.extend(lst)
        if len(adj) < MIN_ATTACKERS:
            continue
        fort = pr.get("fort", 0) or 0
        if fort >= HEAVY_FORT and len(adj) < HEAVY_FORT_ATTACKERS:
            continue
        att = sum(u.get("str", 0) for u in adj)
        est = e.get("str", 0) or 1
        fe = _fort_eff(fort, adj)
        need = MIN_RATIO * (1.25 ** fe)
        if att < need * est:
            continue
        lr = math.log((att + 1.0) / (est + 1.0))
        tdfn = DOWN.get(pr.get("elev", 0), 1.0)
        city = 1.0 if pr.get("city") else 0.0
        heavy = sum(1 for u in adj if u["type"] in ("arm", "art", "eng", "hvt")) / float(len(adj))
        rdy = sum(u.get("rdy", 0) for u in adj) / float(len(adj)) / 100.0
        dirs = float(len(set(u["prov"] for u in adj)))
        feats = [lr, tdfn, fe, city, 0.0, rdy, heavy, dirs]
        mod = api.model or {}
        if "w" in mod and len(mod.get("w", [])) == 8:
            z = mod["b"]
            for i in range(8):
                z += mod["w"][i] * (feats[i] - mod["mean"][i]) / mod["std"][i]
            p = _sig(z)
        else:
            p = _sig(2.0 * (lr - 0.4 * (tdfn - 1.0) - 0.5 * fe) - 0.5)
        if p >= P_MIN:
            cands.append((p, T, adj))

    cands.sort(key=lambda c: c[0], reverse=True)
    for p, T, adj in cands:
        if len(keep) >= MAX_PLANS:
            break
        adj = [u for u in adj if u["id"] not in used]
        if len(adj) < MIN_ATTACKERS or T in busy_T:
            continue
        ids = [u["id"] for u in adj]
        api.cmd("prepare %s P%d" % (_sel(ids), T))
        keep.append({"T": T, "t0": t, "ids": ids})
        used.update(ids)
        busy_T.add(T)
    m["plans"] = keep


def _discover(api):
    tree = api.tree or {}
    best = None
    bestkey = None
    for d, info in tree.items():
        if info.get("status") != "open" or d in DISC_SKIP:
            continue
        need = _num(info.get("res_now"), _num(info.get("cost"), 1e9))
        if api.res - need < RES_KEEP:
            continue
        if d in DISC_ORDER:
            key = (0, DISC_ORDER.index(d))
        else:
            key = (1, need)
        if bestkey is None or key < bestkey:
            bestkey = key
            best = d
    if best is None:
        return False
    api.cmd("research %s" % best)
    return True


def _research(api):
    if len(api.research) >= 2:
        return
    if _discover(api):
        return
    if len(api.research) >= 2:
        return
    running = set(r[0] for r in api.research)
    has_arm = any(u["type"] == "arm" for u in api.units)
    has_art = any(u["type"] == "art" for u in api.units)
    for line in TECH_ORDER:
        if line in running:
            continue
        if line.startswith("arm.") and not has_arm:
            continue
        if line.startswith("art.") and not has_art:
            continue
        info = api.tech.get(line)
        if not info:
            continue
        if info.get("status") in ("dead end", "complete", "researching"):
            continue
        if info.get("level", 0) >= 3:
            continue
        cost = info.get("cost") or {}
        if api.res < cost.get("res", 0) + RES_KEEP:
            continue
        if any(api.stock.get(k, 0) < cost.get(k, 0) for k in ("steel", "oil", "rare")):
            continue
        api.cmd("research %s" % line)
        return


def tick(api):
    m = api.mem
    t = api.t
    units = api.units
    capital = api.capital
    byid = {}
    for u in units:
        byid[u["id"]] = u

    for k in ("refit", "grouped", "plans"):
        if k not in m:
            m[k] = []
    m["grouped"] = [i for i in m["grouped"] if i in byid]
    m["refit"] = [i for i in m["refit"] if i in byid]

    if t % 6 == 0:
        try:
            _diplomacy(api, m)
        except Exception:
            pass
        try:
            skip0 = set(m["refit"]) | set(i for p in m["plans"] for i in p["ids"])
            _refit(api, units, skip0)
        except Exception:
            pass

    try:
        _recruit(api, units)
    except Exception:
        pass

    try:
        _depots(api, t)
    except Exception:
        pass

    try:
        _economy(api, t)
    except Exception:
        pass

    try:
        recs = [u["id"] for u in units if u["type"] == "rec" and not u.get("path")
                and not u.get("explore") and not u.get("expand")]
        if recs:
            api.cmd("explore %s" % _sel(recs))
    except Exception:
        pass

    refit_set = set(m["refit"])
    free = [u for u in units if not u.get("path")
            and u.get("state") not in BAD_STATES
            and u["id"] not in refit_set]
    try:
        _plan(api, m, t, free, byid)
    except Exception:
        pass

    busy = set(i for p in m["plans"] for i in p["ids"])

    try:
        refit = [i for i in m["refit"] if i in byid and byid[i].get("str", 100) < REFIT_DONE]
        new = []
        refit_now = set(refit)
        for u in units:
            if u["type"] == "rec" or u.get("str", 100) >= REFIT_BELOW:
                continue
            if u["id"] in refit_now or u["id"] in busy:
                continue
            new.append(u["id"])
        if new:
            api.cmd("move %s P%d" % (_sel(new), capital))
        m["refit"] = refit + new
    except Exception:
        pass

    try:
        refit_set = set(m["refit"])
        combat = []
        for u in units:
            if u["type"] == "rec":
                continue
            if u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
                continue
            if u["id"] in refit_set or u["id"] in busy:
                continue
            if u.get("state") not in ("ready", "refitting", None):
                continue
            combat.append(u["id"])
        for ch in _chunks(combat, 30):
            api.cmd("expand %s" % _sel(ch))
    except Exception:
        pass

    try:
        if t % 12 == 0:
            gset = set(m["grouped"])
            core = [u["id"] for u in units if u["type"] in LINE_TYPES
                    and u["id"] not in refit_set]
            fresh = [i for i in core if i not in gset]
            if fresh:
                if m["grouped"]:
                    api.cmd("group core + %s" % _sel(fresh))
                else:
                    api.cmd("group core %s" % _sel(fresh))
                m["grouped"] = m["grouped"] + fresh
    except Exception:
        pass

    try:
        _research(api)
    except Exception:
        pass

    m["calls"] = m.get("calls", 0) + 1
