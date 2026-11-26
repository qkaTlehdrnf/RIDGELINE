**Review:** We finished 20th of 30 with 74 provinces, and no assault succeeded in either direction. Neutral land still stood at 77 provinces on day 95, so land ran out late, but expansion was starved. `_civil` only drew expanders from idle units standing in neutral-border provinces. Recruits sit at the capital, so almost no units qualified, and only 4 units were ever on `expand`. Our cap of 20 expanders also left land unclaimed while the frontier was quiet. The pacts, the recruit mix and the attack logic all worked as intended, so I am keeping them.

**Change:** Widen the expansion pool to any ready combat unit with enough strength, prefer units that are not on the front, raise the target to 40 expanders, and pick up to 14 per tick. `expand` already routes each unit to the nearest free neutral province, so units do not need to be on the border first.

```python
RESERVE = 40
MIX = {"inf": 0.28, "grn": 0.10, "mtn": 0.08, "mot": 0.07, "art": 0.09,
       "arm": 0.07, "eng": 0.05, "atg": 0.08, "mec": 0.12, "cav": 0.06}
MIX_HEAVY = {"inf": 0.20, "grn": 0.08, "mtn": 0.06, "mot": 0.10, "art": 0.08,
             "arm": 0.12, "eng": 0.05, "atg": 0.07, "mec": 0.16, "cav": 0.04}
RESEARCH = ["farming", "conscription", "industry", "inf.weapons", "inf.protection",
            "mec.protection", "drill", "atg.weapons", "discipline", "logistics",
            "arm.protection", "art.weapons", "mot.mobility", "medicine", "staffwork",
            "mining", "drilling", "fieldworks"]
RES_KEYS = ("steel", "oil", "rare")
MIN_ADJ = 4
MIN_RDY = 70
MAX_FORT = 2
UNKNOWN_FORT = 1
MIN_RATIO = 2.0
MIN_P = 0.6
MAX_PREP_H = 4
GOOD_BONUS = 25
PACT_RETRY = 48
EXPAND_WANT = 40
EXPAND_MIN_STR = 35
RECRUIT_PER_TICK = 8
REFIT_PER_TICK = 15
EXPAND_PICK = 14
DEPOT_LOAD_FRAC = 0.7
DEPOT_GAP_H = 48


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


def _refit_weak(api, mem, combat, ids):
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


def _refit_old(api, refit_set):
    if not api.old_units:
        return
    rc = api.refit_cost or {}
    b = _budget(api)
    cands = [u for u in api.units if u.get("old") and u.get("type") != "rec"
             and not u.get("path") and u["id"] not in refit_set
             and u.get("state") in ("ready", "defending")]
    cands.sort(key=lambda u: (bool(u.get("front")), -u.get("str", 0)))
    picked = []
    for u in cands:
        if len(picked) >= REFIT_PER_TICK:
            break
        c = rc.get(u.get("type"))
        if not c:
            continue
        ok = b["res"] - c.get("res", 0) >= RESERVE
        for k in RES_KEYS:
            if b[k] < c.get(k, 0):
                ok = False
        if not ok:
            continue
        b["res"] -= c.get("res", 0)
        for k in RES_KEYS:
            b[k] -= c.get(k, 0)
        picked.append(u["id"])
    if picked:
        _ok(api, "refit " + _sel(picked))


def _pick_mix(api):
    s = api.stock
    if s.get("steel", 0) > 600 and s.get("oil", 0) > 600:
        return MIX_HEAVY
    return MIX


def _recruit(api, counts):
    b = _budget(api)
    mix = _pick_mix(api)
    if counts.get("rec", 0) < 2 and _can(api, b, "rec", RESERVE):
        if _ok(api, "recruit rec 1 P%d" % api.capital).startswith("ok"):
            _spend(api, b, "rec")
            counts["rec"] = counts.get("rec", 0) + 1
    for _ in range(RECRUIT_PER_TICK):
        total = sum(counts.get(t, 0) for t in mix)
        best = None
        bd = -1e9
        for typ, share in mix.items():
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


def _pact_active(api, f):
    if not f:
        return False
    p = (api.pacts or {}).get(f)
    if not p or p.get("broken_by"):
        return False
    end = p.get("ends")
    return end is None or end > api.t


def _val(api, what, n):
    # res is what we are short of; surplus steel/oil/rare is worth little to us
    if what == "res":
        return n * 1.0
    if what == "mp":
        return n * 0.8
    s = api.stock.get(what, 0)
    return n * (0.15 if s > 400 else 1.2)


def _diplomacy(api, mem):
    if api.t % 6:
        return
    for o in list(api.offers_in or []):
        oid = o.get("id")
        if oid is None:
            continue
        if o.get("kind") == "pact":
            _ok(api, "accept %s" % oid)
            continue
        if o.get("kind") == "trade":
            give = o.get("they_give", {}) or {}
            take = o.get("you_give", {}) or {}
            gain = sum(_val(api, k, v) for k, v in give.items())
            cost = sum(_val(api, k, v) for k, v in take.items())
            can = all(api.stock.get(k, 0) >= v for k, v in take.items())
            if can and gain >= cost:
                _ok(api, "accept %s" % oid)
            else:
                _ok(api, "reject %s" % oid)
    pending = set(o.get("to") for o in (api.offers_out or []) if o.get("kind") == "pact")
    last = mem.setdefault("pact_t", {})
    for f in api.met or []:
        if _pact_active(api, f) or f in pending:
            continue
        if api.t - last.get(f, -10 ** 9) < PACT_RETRY:
            continue
        last[f] = api.t
        _ok(api, "offer %s pact" % f)


def _depots(api, mem):
    # open a forward depot when the busiest one nears capacity (load slows all it serves)
    if api.t - mem.get("dep_t", -10 ** 9) < DEPOT_GAP_H:
        return
    deps = api.depots or {}
    if not deps:
        return
    worst_id, worst = max(deps.items(),
                          key=lambda kv: kv[1].get("load", 0) / max(1.0, kv[1].get("capacity", 30)))
    cap = max(1.0, worst.get("capacity", 30))
    if worst.get("load", 0) < DEPOT_LOAD_FRAC * cap:
        return
    if api.stock.get("res", 0) < 150 + RESERVE:
        return
    held = set(int(k) for k in deps.keys())
    wid = int(worst_id)
    cands = []
    for pid, pr in api.provs.items():
        pid = int(pid)
        if pid in held or pr.get("owner") != "me" or not pr.get("supplied"):
            continue
        if pr.get("harsh"):
            continue
        nb = pr.get("nbrs", []) or []
        own = sum(1 for n in nb if api.provs.get(n, {}).get("owner") == "me")
        if own < 2:
            continue
        cands.append((own, pid))
    cands.sort(reverse=True)
    best = None
    bd = -1
    for own, pid in cands[:30]:
        p = api.path(wid, pid)
        if not p:
            continue
        hops = len(p) - 1
        if 3 <= hops <= 6 and own > bd:
            bd = own
            best = pid
    if best is None:
        return
    r = _ok(api, "depot P%d" % best)
    if r.startswith("ok"):
        mem["dep_t"] = api.t


def _civil(api, combat, refit):
    used = set()
    rec = [u["id"] for u in api.units
           if u.get("type") == "rec" and not u.get("path") and not u.get("explore")]
    if api.unexplored and rec:
        _ok(api, "explore " + _sel(rec))
    neutral = set(api.neutral_border)
    expanders = [u for u in combat if u.get("expand")]
    want = min(EXPAND_WANT, max(len(neutral), 1) * 2)
    need = want - len(expanders)
    if need > 0:
        # any ready, healthy combat unit may go claim land; units off the front go first
        cands = [u for u in combat
                 if u["id"] not in refit and not u.get("path")
                 and not u.get("expand") and not u.get("explore")
                 and u.get("state") == "ready"
                 and u.get("str", 0) >= EXPAND_MIN_STR]
        cands.sort(key=lambda u: (bool(u.get("front")), -u.get("str", 0)))
        pick = [u["id"] for u in cands[:min(need, EXPAND_PICK)]]
        if pick:
            _ok(api, "expand " + _sel(pick))
            used.update(pick)
    return used


def _terrain_dfn(prov):
    t = str(prov.get("terrain", "")).lower()
    if "mount" in t:
        return 2.0
    if "hill" in t:
        return 1.5
    if "forest" in t:
        return 1.25
    return 1.0


def _win_p(api, P, adj, sE):
    m = api.model or {}
    if not m or "w" not in m:
        return None
    prov = api.provs.get(P, {})
    sA = sum(u.get("str", 0) for u in adj) + 1.0
    feats = m.get("features", [])
    n = len(adj)
    heavy = sum(1 for u in adj if u.get("type") in ("art", "eng", "arm")) / max(1, n)
    dirs = len(set(u.get("prov") for u in adj))
    bonus = max(u.get("bonus", 0) for u in adj) / 100.0
    rdy = sum(u.get("rdy", 100) for u in adj) / (100.0 * n)
    vals = {
        "log_ratio": math.log(sA / (sE + 1.0)),
        "terrain_dfn": _terrain_dfn(prov),
        "fort": float(prov.get("fort", 0) or 0),
        "city": 1.0 if prov.get("city") else 0.0,
        "bonus": bonus,
        "att_rdy": rdy,
        "heavy_share": heavy,
        "dirs": float(dirs),
    }
    w = m.get("w", [])
    mean = m.get("mean", [0.0] * len(w))
    std = m.get("std", [1.0] * len(w))
    z = m.get("b", 0.0)
    for i, f in enumerate(feats):
        if i >= len(w):
            break
        sd = std[i] if std[i] else 1.0
        z += w[i] * (vals.get(f, mean[i]) - mean[i]) / sd
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _attack(api, mem, combat, refit):
    if api.t % 3:
        return
    prep = mem.setdefault("prep", {})
    em = {}
    for key, e in (api.enemy or {}).items():
        try:
            em[int(key)] = e
        except Exception:
            continue
    for P in list(prep.keys()):
        if P not in em or api.t - prep[P]["t"] > 12:
            del prep[P]
    for P, e in sorted(em.items(), key=lambda kv: kv[1].get("str", 0)):
        sE = e.get("str", 0)
        if sE <= 0 or not e.get("exact", False):
            continue
        prov = api.provs.get(P, {})
        fort = prov.get("fort")
        if fort is None:
            fort = UNKNOWN_FORT
        if _pact_active(api, api.owner_name.get(P)):
            continue
        adj = []
        for u in combat:
            if u["id"] in refit or u.get("expand") or u.get("explore"):
                continue
            if u.get("state") not in ("ready", "defending", "preparing"):
                continue
            if u.get("dry") or u.get("str", 0) < 50:
                continue
            if P in api.provs.get(u.get("prov"), {}).get("nbrs", []):
                adj.append(u)
        if len(adj) < MIN_ADJ:
            continue
        n_art = sum(1 for u in adj if u.get("type") == "art")
        if fort > MAX_FORT and n_art < 3:
            continue
        avg_rdy = sum(u.get("rdy", 100) for u in adj) / len(adj)
        if avg_rdy < MIN_RDY:
            continue
        sA = sum(u.get("str", 0) for u in adj)
        if sA < MIN_RATIO * sE:
            continue
        p = _win_p(api, P, adj, sE)
        if p is None:
            p = 0.7
        if p < MIN_P:
            continue
        ids = [u["id"] for u in adj]
        rec_p = prep.get(P)
        if rec_p is None:
            _ok(api, "prepare %s P%d" % (_sel(ids), P))
            prep[P] = {"t": api.t}
            return
        waited = api.t - rec_p["t"]
        bonus = max(u.get("bonus", 0) for u in adj)
        if waited >= MAX_PREP_H or bonus >= GOOD_BONUS:
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

    try:
        _diplomacy(api, mem)
    except Exception:
        pass

    try:
        _depots(api, mem)
    except Exception:
        pass

    refit = set()
    try:
        refit = _refit_weak(api, mem, combat, ids)
    except Exception:
        refit = set(mem.get("refit", []))

    try:
        _refit_old(api, refit)
    except Exception:
        pass

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
        used = _civil(api, combat, refit)
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
```

REVIEW: standard