RES_KEEP = 30
TECH_ORDER = ["farming", "inf.weapons", "inf.protection", "conscription",
              "medicine", "mining", "arm.weapons", "logistics", "drill",
              "discipline", "inf.mobility", "arm.protection", "fieldworks"]
DOWN = {0: 1.0, 1: 1.0, 2: 1.5, 3: 2.0}
ATTACK_STR = 60
LINE_TYPES = ("inf", "mtn", "arm", "mot", "mec", "grn", "hvt")


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


def _can(api, kind, n=1):
    uc = api.unit_costs.get(kind)
    if not uc:
        return False
    if api.res < uc.get("res", 0) * n + RES_KEEP:
        return False
    if api.mp < uc.get("mp", 0) * n:
        return False
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) < uc.get(k, 0) * n:
            return False
    return True


def _recruit(api, units):
    own = sum(1 for p in api.provs.values() if p.get("owner") == "me")
    target = min(60, 10 + 2 * own)
    total = len(units)
    if total >= target:
        return
    kinds = [u["type"] for u in units]
    n_rec = kinds.count("rec")
    n_arm = kinds.count("arm")
    n_art = kinds.count("art")
    if n_rec < 2:
        pick = "rec"
    elif total < 8:
        pick = "inf"
    elif n_arm < 0.2 * total:
        pick = "arm"
    elif n_art < 0.1 * total:
        pick = "art"
    else:
        pick = "inf"
    if not _can(api, pick):
        pick = "inf"
        if not _can(api, pick):
            return
    n = 1
    rc = api.unit_costs.get(pick, {}).get("res", 0)
    if api.res > 3 * rc + RES_KEEP + 60 and _can(api, pick, 2):
        n = 2
    api.cmd("recruit %s %d P%d" % (pick, n, api.capital))


def _attack(api, m, t, units, byid, free):
    if m.get("plan") is not None:
        pl = m["plan"]
        alive = [i for i in pl["ids"] if i in byid]
        if not alive:
            m["plan"] = None
        elif t - pl["t0"] >= 12:
            api.cmd("move %s P%d" % (_sel(alive), pl["T"]))
            m["plan"] = None
        return

    mine_provs = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    best = None
    for T, e in api.enemy.items():
        if T in mine_provs:
            continue
        pr = api.provs.get(T)
        if not pr:
            continue
        nbrs = pr.get("nbrs", [])
        if not any(n in mine_provs for n in nbrs):
            continue
        adj = [u for u in free
               if u["prov"] in nbrs and u["type"] != "rec"
               and u.get("str", 0) >= ATTACK_STR and u.get("rdy", 0) >= 60
               and u.get("state") == "ready"]
        if not adj:
            continue
        att = sum(u.get("str", 0) for u in adj)
        est = e.get("str", 0) or 1
        if att < 1.5 * est:
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
        if p >= 0.6 and (best is None or p > best[0]):
            best = (p, T, adj)
    if best is not None:
        p, T, adj = best
        ids = [u["id"] for u in adj]
        api.cmd("prepare %s P%d" % (_sel(ids), T))
        m["plan"] = {"T": T, "t0": t, "ids": ids}


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
        if api.res < cost.get("res", 0) + RES_KEEP + 40:
            continue
        ok = True
        for k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) < cost.get(k, 0):
                ok = False
        if not ok:
            continue
        api.cmd("research %s" % line)
        return


def tick(api):
    m = api.mem
    t = api.t
    units = api.units
    byid = dict((u["id"], u) for u in units)
    capital = api.capital

    for k in ("refit", "grouped"):
        if k not in m:
            m[k] = []
    if "plan" not in m:
        m["plan"] = None

    # 1. recruitment
    if t % 4 == 0:
        try:
            _recruit(api, units)
        except Exception:
            pass

    # 2. scouting with rec
    try:
        recs = [u for u in units if u["type"] == "rec" and not u.get("path")
                and not u.get("explore") and not u.get("expand")]
        if recs:
            api.cmd("explore %s" % _sel([u["id"] for u in recs]))
    except Exception:
        pass

    # 3. attack planning (before expansion so planned units are not reassigned)
    try:
        free = [u for u in units if not u.get("path")
                and u.get("state") not in ("preparing", "assault", "digging", "pinned", "routing")]
        _attack(api, m, t, units, byid, free)
    except Exception:
        pass

    busy = set(m["plan"]["ids"]) if m.get("plan") else set()

    # 4. refit damaged units, return recovered ones
    try:
        refit = [i for i in m["refit"] if i in byid]
        back = []
        for i in refit:
            if byid[i].get("str", 100) >= 85:
                back.append(i)
        refit = [i for i in refit if i not in back]
        m["refit"] = refit
        new = [u["id"] for u in units
               if u["type"] != "rec" and u.get("str", 100) < 35
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
        recs = [u["id"] for u in idle if u["type"] == "rec"]
        combat = [u["id"] for u in idle if u["type"] != "rec"]
        for ch in _chunks(combat, 30):
            api.cmd("expand %s" % _sel(ch))
    except Exception:
        pass

    # 6. formation: group line units every 12 hours
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
