RES_KEEP = 120
MAX_UNITS = 1500
ATTACK_STR = 45
ATTACK_RDY = 45
MAX_PLANS = 6
PREP_HOURS = 6
MIN_RATIO = 1.3
P_MIN = 0.45
REFIT_BELOW = 35
REFIT_DONE = 85

TECH_ORDER = ["inf.weapons", "farming", "inf.protection", "conscription",
              "medicine", "logistics", "mining", "arm.weapons", "drill",
              "discipline", "industry", "inf.mobility", "arm.protection",
              "fieldworks", "staffwork"]

WEIGHT = {"inf": 0.40, "arm": 0.15, "art": 0.12, "mot": 0.10,
          "mec": 0.06, "eng": 0.05, "atg": 0.04, "grn": 0.04, "rec": 0.02}

LINE_TYPES = ("inf", "mtn", "arm", "mot", "mec", "grn", "hvt", "art", "eng", "atg")
DOWN = {0: 1.0, 1: 1.0, 2: 1.5, 3: 2.0}


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
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    n_units = len(units)
    spent = {}
    made = 0
    for _ in range(6):
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


def _plan(api, m, t, free):
    keep = []
    for pl in m["plans"]:
        alive = [i for i in pl["ids"] if i in api.mem_byid]
        if not alive:
            continue
        if t - pl["t0"] >= PREP_HOURS:
            api.cmd("move %s P%d" % (_sel(alive), pl["T"]))
            continue
        keep.append({"T": pl["T"], "t0": pl["t0"], "ids": alive})
    m["plans"] = keep
    if len(keep) >= MAX_PLANS:
        return

    busy_T = set(p["T"] for p in keep)
    used = set(i for p in keep for i in p["ids"])
    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    cands = []
    for T, e in api.enemy.items():
        if T in mine or T in busy_T:
            continue
        pr = api.provs.get(T)
        if not pr:
            continue
        nbrs = pr.get("nbrs", [])
        if not any(n in mine for n in nbrs):
            continue
        adj = [u for u in free
               if u["id"] not in used and u["prov"] in nbrs
               and u["type"] != "rec"
               and u.get("str", 0) >= ATTACK_STR and u.get("rdy", 0) >= ATTACK_RDY]
        if not adj:
            continue
        att = sum(u.get("str", 0) for u in adj)
        est = e.get("str", 0) or 1
        if att < MIN_RATIO * est:
            continue
        lr = math.log((att + 1.0) / (est + 1.0))
        tdfn = DOWN.get(pr.get("elev", 0), 1.0)
        fort = pr.get("fort", 0) or 0
        city = 1.0 if pr.get("city") else 0.0
        heavy = sum(1 for u in adj if u["type"] in ("arm", "art", "eng", "hvt")) / float(len(adj))
        rdy = sum(u.get("rdy", 0) for u in adj) / float(len(adj)) / 100.0
        dirs = float(len(set(u["prov"] for u in adj)))
        feats = [lr, tdfn, fort, city, 0.0, rdy, heavy, dirs]
        mod = api.model or {}
        if "w" in mod and len(mod.get("w", [])) == 8:
            z = mod["b"]
            for i in range(8):
                z += mod["w"][i] * (feats[i] - mod["mean"][i]) / mod["std"][i]
            p = _sig(z)
        else:
            p = _sig(2.0 * (lr - 0.4 * (tdfn - 1.0) - 0.5 * fort) - 0.5)
        if p >= P_MIN:
            cands.append((p, T, adj))

    cands.sort(key=lambda c: c[0], reverse=True)
    for p, T, adj in cands:
        if len(keep) >= MAX_PLANS:
            break
        adj = [u for u in adj if u["id"] not in used]
        if not adj or T in busy_T:
            continue
        ids = [u["id"] for u in adj]
        api.cmd("prepare %s P%d" % (_sel(ids), T))
        keep.append({"T": T, "t0": t, "ids": ids})
        used.update(ids)
        busy_T.add(T)
    m["plans"] = keep


def _research(api):
    if len(api.research) >= 2:
        return
    running = set(r[0] for r in api.research)
    has_arm = any(u["type"] == "arm" for u in api.units)
    for line in TECH_ORDER:
        if line in running:
            continue
        if line.startswith("arm.") and not has_arm:
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
    byid = dict((u["id"], u) for u in units)
    api.mem_byid = byid
    capital = api.capital

    for k in ("refit", "grouped", "plans"):
        if k not in m:
            m[k] = []

    # 1. recruitment: spend what we have, every 2 hours
    if t % 2 == 0:
        try:
            _recruit(api, units)
        except Exception:
            pass

    # 2. scouting with rec
    try:
        recs = [u["id"] for u in units if u["type"] == "rec" and not u.get("path")
                and not u.get("explore") and not u.get("expand")]
        if recs:
            api.cmd("explore %s" % _sel(recs))
    except Exception:
        pass

    # 3. prepared attacks (several at once)
    free = [u for u in units if not u.get("path")
            and u.get("state") not in ("preparing", "assault", "digging", "pinned", "routing")
            and u["id"] not in set(m["refit"])]
    try:
        _plan(api, m, t, free)
    except Exception:
        pass

    busy = set(i for p in m["plans"] for i in p["ids"])

    # 4. refit damaged units, return recovered ones
    try:
        refit = [i for i in m["refit"] if i in byid and byid[i].get("str", 100) < REFIT_DONE]
        m["refit"] = refit
        new = [u["id"] for u in units
               if u["type"] != "rec" and u.get("str", 100) < REFIT_BELOW
               and u["id"] not in refit and u["id"] not in busy]
        if new:
            api.cmd("move %s P%d" % (_sel(new), capital))
            m["refit"] = refit + new
    except Exception:
        pass

    # 5. expansion for idle units (falls back to front when no neutral land)
    try:
        refit_set = set(m["refit"])
        idle = [u for u in units if not u.get("path") and not u.get("front")
                and not u.get("expand") and not u.get("explore")
                and u["id"] not in refit_set and u["id"] not in busy
                and u.get("state") in ("ready", "refitting", None)]
        combat = [u["id"] for u in idle if u["type"] != "rec"]
        for ch in _chunks(combat, 30):
            api.cmd("expand %s" % _sel(ch))
    except Exception:
        pass

    # 6. formations: group line units every 12 hours
    try:
        if t % 12 == 0:
            core = [u["id"] for u in units if u["type"] in LINE_TYPES
                    and u["id"] not in m["refit"]]
            fresh = [i for i in core if i not in m["grouped"]]
            if fresh:
                if m["grouped"]:
                    api.cmd("group core + %s" % _sel(fresh))
                else:
                    api.cmd("group core %s" % _sel(fresh))
                m["grouped"] = m["grouped"] + fresh
    except Exception:
        pass

    # 7. research
    try:
        _research(api)
    except Exception:
        pass

    m["calls"] = m.get("calls", 0) + 1
