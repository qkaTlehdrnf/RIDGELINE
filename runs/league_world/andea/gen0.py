RESERVE = 40
MIX = {"inf": 0.28, "grn": 0.10, "mtn": 0.08, "mot": 0.08, "art": 0.12,
       "arm": 0.12, "eng": 0.05, "atg": 0.05, "mec": 0.05}
RESEARCH = ["farming", "conscription", "inf.weapons", "art.weapons", "arm.weapons",
            "mining", "inf.protection", "arm.protection", "drill", "logistics",
            "medicine", "drilling", "industry", "discipline", "mot.mobility", "arm.mobility"]
RES_KEYS = ("steel", "oil", "rare")


def _ok(api, line):
    try:
        return api.cmd(line)
    except Exception:
        return ""


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _budget(api):
    b = {"res": api.stock.get("res", 0), "mp": api.mp}
    for k in RES_KEYS:
        b[k] = api.stock.get(k, 0)
    return b


def _can(api, b, typ, reserve):
    uc = api.unit_costs.get(typ)
    if not uc:
        return False
    if b["res"] - uc.get("res", 0) < reserve:
        return False
    if b["mp"] < uc.get("mp", 0):
        return False
    for k in RES_KEYS:
        if b[k] < uc.get(k, 0):
            return False
    return True


def _spend(api, b, typ):
    uc = api.unit_costs[typ]
    b["res"] -= uc.get("res", 0)
    b["mp"] -= uc.get("mp", 0)
    for k in RES_KEYS:
        b[k] -= uc.get(k, 0)


def _refit(api, mem, combat, ids):
    refit = set(i for i in mem.get("refit", []) if i in ids)
    moves = []
    for u in combat:
        i = u["id"]
        s = u.get("str", 100)
        if i in refit:
            if s >= 85:
                refit.discard(i)
        elif s < 40 and u.get("prov") != api.capital and not u.get("path"):
            refit.add(i)
            moves.append(i)
    if moves:
        _ok(api, "move %s P%d" % (_sel(moves), api.capital))
    mem["refit"] = list(refit)
    return refit


def _recruit(api, counts):
    b = _budget(api)
    if counts.get("rec", 0) < 1 and _can(api, b, "rec", RESERVE):
        if _ok(api, "recruit rec 1 P%d" % api.capital).startswith("ok"):
            _spend(api, b, "rec")
            counts["rec"] = counts.get("rec", 0) + 1
    for _ in range(3):
        total = sum(counts.get(t, 0) for t in MIX)
        best = None
        bd = -1e9
        for typ, share in MIX.items():
            if not _can(api, b, typ, RESERVE):
                continue
            d = share * (total + 1) - counts.get(typ, 0)
            if d > bd:
                bd = d
                best = typ
        if best is None:
            break
        r = _ok(api, "recruit %s 1 P%d" % (best, api.capital))
        if not r.startswith("ok"):
            break
        _spend(api, b, best)
        counts[best] = counts.get(best, 0) + 1


def _research(api):
    if len(api.research) >= 2 or api.stock.get("res", 0) < 150:
        return
    busy = set(r[0] for r in api.research)
    for line in RESEARCH:
        if line in busy:
            continue
        info = api.tech.get(line)
        if not info:
            continue
        if info.get("status") != "open" or info.get("level", 0) >= 3:
            continue
        cost = info.get("cost")
        if not cost:
            continue
        ok = True
        for k, v in cost.items():
            need = v + (RESERVE if k == "res" else 0)
            if api.stock.get(k, 0) < need:
                ok = False
                break
        if ok:
            _ok(api, "research " + line)
            return


def _civil(api, combat, idle):
    used = set()
    neutral = set(api.neutral_border)
    rec = [u["id"] for u in api.units
           if u.get("type") == "rec" and not u.get("path") and not u.get("explore")]
    if api.unexplored and rec:
        _ok(api, "explore " + _sel(rec))
    expanders = [u for u in combat if u.get("expand")]
    want = min(6, len(neutral))
    need = want - len(expanders)
    if need > 0:
        cands = [u for u in idle if u.get("prov") in neutral and u.get("str", 0) >= 60]
        pick = [u["id"] for u in cands[:min(need, 3)]]
        if pick:
            _ok(api, "expand " + _sel(pick))
            used.update(pick)
    return used


def _attack(api, mem, combat, refit):
    if api.t % 3:
        return
    prep = mem.setdefault("prep", {})
    enemy = api.enemy or {}
    for P in list(prep.keys()):
        if P not in enemy or api.t - prep[P] > 12:
            del prep[P]
    for key, e in enemy.items():
        try:
            P = int(key)
        except Exception:
            continue
        sE = e.get("str", 0)
        if sE <= 0:
            continue
        adj = []
        for u in combat:
            if u["id"] in refit or u.get("expand") or u.get("explore"):
                continue
            if u.get("state") not in ("ready", "defending", "preparing"):
                continue
            if u.get("dry") or u.get("str", 0) < 50:
                continue
            nbrs = api.provs.get(u.get("prov"), {}).get("nbrs", [])
            if P in nbrs:
                adj.append(u)
        if len(adj) < 2:
            continue
        sMe = sum(u.get("str", 0) for u in adj)
        ratio = 2.0 if e.get("exact") else 2.8
        if sMe < ratio * sE:
            continue
        ids = [u["id"] for u in adj]
        t0 = prep.get(P)
        if t0 is None:
            _ok(api, "prepare %s P%d" % (_sel(ids), P))
            prep[P] = api.t
        elif api.t - t0 >= 4:
            _ok(api, "move %s P%d" % (_sel(ids), P))
            del prep[P]
        return


def tick(api):
    mem = api.mem
    combat = [u for u in api.units if u.get("type") != "rec"]
    ids = set(u["id"] for u in api.units)
    counts = {}
    for u in api.units:
        counts[u.get("type")] = counts.get(u.get("type"), 0) + 1

    refit = set()
    try:
        refit = _refit(api, mem, combat, ids)
    except Exception:
        refit = set(mem.get("refit", []))

    try:
        _recruit(api, counts)
    except Exception:
        pass

    try:
        _research(api)
    except Exception:
        pass

    idle = [u for u in combat
            if u["id"] not in refit and not u.get("path")
            and u.get("state") == "ready" and not u.get("front")
            and not u.get("expand") and not u.get("explore")]

    used = set()
    try:
        used = _civil(api, combat, idle)
    except Exception:
        pass

    try:
        _attack(api, mem, combat, refit)
    except Exception:
        pass

    try:
        front_ids = [u["id"] for u in idle if u["id"] not in used]
        if front_ids:
            _ok(api, "front " + _sel(front_ids))
    except Exception:
        pass

    mem["calls"] = mem.get("calls", 0) + 1
