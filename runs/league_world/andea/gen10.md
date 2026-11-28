**Review of war 10 (gen9 policy, 39 provinces, 17th place):** Almost all income went to upkeep (about 397k of 461k earned), so the purse never built up. Research was starved: only 3 research commands were issued and the bank sat near 60. The army grew to 4,358 units, of which 2,952 were on outdated models. Refit was refused 2,720 times because the units were not on supplied land. Rare, rubber and oil piled up unused. None of the 757 assaults on defended provinces succeeded.

**Changes:**
- Recruiting stops when upkeep exceeds 60% of income, which keeps the economy solvent.
- Research now saves up for the next wanted discovery when it is reachable within about 40 days of income, and recruiting and refits leave that money alone.
- Refits only target units that are on supplied land.
- Attack logic is unchanged, since its failures were not clearly a logic bug.

I'm keeping the rest of the policy as it was.

```python
RESERVE = 60
MIN_DAYS_LEFT = 25
MAX_UPKEEP_SHARE = 0.6
SAVE_MAX_DAYS = 40
RECRUIT_PER_TICK = 8
REC_WANT = 6
REFIT_PER_TICK = 10
REFIT_WEAK = 40
EXPAND_WANT = 40
EXPAND_MIN_STR = 35
EXPAND_PICK = 14
RESEARCH_MIN_RES = 150
DEV_GAP_H = 12
BUILD_GAP_H = 24
DEPOT_GAP_H = 48
DEPOT_LOAD_FRAC = 0.7
PACT_RETRY = 48
SELL_GAP_H = 24
MIN_ADJ = 4
MIN_RDY = 70
MAX_FORT = 2
UNKNOWN_FORT = 1
MIN_RATIO = 2.0
MIN_RATIO_FORT = 2.5
MIN_P = 0.6
MAX_PREP_H = 4
GOOD_BONUS = 25
RES_KEYS = ("steel", "oil", "rare")

# recruit weights; only kinds in api.can_raise are used
WANT = {"inf": 3.0, "mil": 1.0, "rec": 0.5, "cav": 1.5, "grn": 1.5,
        "mtn": 1.0, "mot": 1.0, "arm": 1.5, "mec": 1.5, "hvt": 1.0,
        "art": 1.2, "eng": 0.5, "atg": 0.8, "rkt": 0.6}

# discoveries in the order I want them (cheap, broadly useful first)
DISC_ORDER = ["iron_working", "horse_riding", "siege_engines", "masonry", "roads",
              "hillmen", "galleys", "pikes_crossbows", "stirrup", "trebuchet",
              "castles", "sailing", "crop_rotation", "gunpowder", "matchlock",
              "banking", "navigation", "grenadiers", "dragoons", "steam_power",
              "rifling", "steel_guns", "field_engineering", "railways",
              "ships_of_the_line", "ironclads", "combustion", "machine_guns",
              "tanks", "heavy_artillery", "anti_tank_guns", "flight", "bombers",
              "dreadnoughts", "submarines", "mechanisation", "heavy_armour",
              "rocket_artillery", "assault_rifles", "jet_engines", "carriers",
              "rocketry", "satellites", "ballistic_missiles", "composite_armour",
              "guided_weapons"]

RESEARCH = ["farming", "conscription", "industry", "inf.weapons", "inf.protection",
            "mec.protection", "drill", "atg.weapons", "discipline", "logistics",
            "arm.protection", "art.weapons", "mot.mobility", "medicine", "staffwork",
            "mining", "drilling", "fieldworks"]


def _ok(api, line):
    try:
        return api.cmd(line)
    except Exception:
        return ""


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _snap(api):
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
        elif s < REFIT_WEAK and u.get("prov") != api.capital and not u.get("path"):
            refit.add(i)
            moves.append(i)
    if moves:
        _ok(api, "move %s P%d" % (_sel(moves), api.capital))
    mem["refit"] = list(refit)
    return refit


def _refit_old(api, refit_set, save):
    if not api.old_units:
        return
    rc = api.refit_cost or {}
    b = _snap(api)
    b["res"] -= save
    cands = [u for u in api.units if u.get("old") and u.get("type") != "rec"
             and not u.get("path") and u["id"] not in refit_set
             and u.get("supplied", True) and not u.get("dry")
             and u.get("state") in ("ready", "defending")]
    cands.sort(key=lambda u: (bool(u.get("front")), -u.get("str", 0)))
    picked = []
    for u in cands:
        if len(picked) >= REFIT_PER_TICK:
            break
        c = rc.get(u.get("type"))
        if not c:
            continue
        if b["res"] - c.get("res", 0) < RESERVE:
            continue
        if any(b[k] < c.get(k, 0) for k in RES_KEYS):
            continue
        b["res"] -= c.get("res", 0)
        for k in RES_KEYS:
            b[k] -= c.get(k, 0)
        picked.append(u["id"])
    if picked:
        _ok(api, "refit " + _sel(picked))


def _recruit(api, counts, save):
    bud = api.budget or {}
    dl = bud.get("days_left")
    if dl is not None and dl < MIN_DAYS_LEFT:
        return
    if (bud.get("upkeep_share") or 0) > MAX_UPKEEP_SHARE:
        return
    b = _snap(api)
    b["res"] -= save
    can = set(api.can_raise or [])
    wts = {k: w for k, w in WANT.items() if k in can and w > 0}
    if not wts:
        return
    if "rec" in wts and counts.get("rec", 0) < REC_WANT and _can(api, b, "rec", RESERVE):
        if _ok(api, "recruit rec 1 P%d" % api.capital).startswith("ok"):
            _spend(api, b, "rec")
            counts["rec"] = counts.get("rec", 0) + 1
    total_w = sum(wts.values())
    for _ in range(RECRUIT_PER_TICK):
        total = sum(counts.get(t, 0) for t in wts)
        best = None
        bd = -1e9
        for typ, w in wts.items():
            if not _can(api, b, typ, RESERVE):
                continue
            d = (w / total_w) * (total + 1) - counts.get(typ, 0)
            if d > bd:
                bd = d
                best = typ
        if best is None:
            break
        if not _ok(api, "recruit %s 1 P%d" % (best, api.capital)).startswith("ok"):
            break
        _spend(api, b, best)
        counts[best] = counts.get(best, 0) + 1


def _research(api, mem):
    mem["save"] = 0
    tree = api.tree or {}
    busy = [r[0] for r in (api.research or [])]
    if len(busy) >= 2:
        return
    res = api.stock.get("res", 0)
    inc = api.income if (api.income or 0) > 0 else 0
    if not any(b in tree for b in busy):
        for d in DISC_ORDER:
            info = tree.get(d)
            if not info or info.get("status") != "open":
                continue
            need = info.get("res_now") or (info.get("cost") or {}).get("res", 0)
            if res - need >= RESERVE:
                if _ok(api, "research " + d).startswith("ok"):
                    return
                continue
            gap = need + RESERVE - res
            if inc > 0 and gap / inc <= SAVE_MAX_DAYS:
                mem["save"] = need + RESERVE
                return
    if res < RESEARCH_MIN_RES:
        return
    for line in RESEARCH:
        if line in busy:
            continue
        info = (api.tech or {}).get(line) or {}
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
        if ok and _ok(api, "research " + line).startswith("ok"):
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
            if "res" in take and api.stock.get("res", 0) - take["res"] < 150:
                can = False
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


def _sell(api, mem):
    if api.t - mem.get("sell_t", -10 ** 9) < SELL_GAP_H:
        return
    if api.stock.get("res", 0) > 800:
        return
    if any(o.get("kind") == "trade" for o in (api.offers_out or [])):
        return
    if api.stock.get("rubber", 0) >= 600:
        what = "rubber"
    elif api.stock.get("rare", 0) >= 300:
        what = "rare"
    else:
        return
    n = min(200, int(api.stock.get(what, 0) * 0.3))
    if n < 50:
        return
    for f in api.met or []:
        if not _pact_active(api, f):
            continue
        if _ok(api, "offer %s trade %d %s for %d res" % (f, n, what, n // 2)).startswith("ok"):
            mem["sell_t"] = api.t
            api.count("sell_offer")
            return


def _develop(api, mem):
    if api.t - mem.get("dev_t", -10 ** 9) < DEV_GAP_H:
        return
    econ = api.economy or {}
    works = econ.get("works", []) or []
    if len(works) >= 2:
        return
    busy = set(w[1] for w in works if w[0] == "dev")
    best = None
    bv = 0.0
    for pr in econ.get("provs", []) or []:
        p = pr.get("prov")
        if p is None or p in busy:
            continue
        dev = pr.get("dev", 0)
        if dev >= 6 or dev + 1 > pr.get("room", 0):
            continue
        if not pr.get("can_dev"):
            continue
        dc = pr.get("dev_cost") or {}
        c_res = dc.get("res", 1)
        if api.stock.get("res", 0) - c_res < RESERVE + 60:
            continue
        gain = (pr.get("base", 1) * 0.3 + 0.8) * pr.get("agg", 1)
        v = gain / max(1, c_res)
        if v > bv:
            bv = v
            best = p
    if best is None:
        return
    if _ok(api, "develop P%d" % int(best)).startswith("ok"):
        mem["dev_t"] = api.t
        api.count("develop")


def _build(api, mem):
    if api.t - mem.get("build_t", -10 ** 9) < BUILD_GAP_H:
        return
    econ = api.economy or {}
    works = econ.get("works", []) or []
    if len(works) >= 3:
        return
    busy = set(w[1] for w in works if w[0] == "infra")
    best = None
    bv = 0.0
    for pr in econ.get("provs", []) or []:
        p = pr.get("prov")
        if p is None or p in busy or not pr.get("can_infra"):
            continue
        if pr.get("infra", 0) >= 3 or pr.get("dev", 0) < 2:
            continue
        ic = pr.get("infra_cost") or {}
        if api.stock.get("res", 0) - ic.get("res", 0) < RESERVE + 100:
            continue
        v = pr.get("agg", 1) * pr.get("dev", 0) / max(1, ic.get("res", 1))
        if v > bv:
            bv = v
            best = p
    if best is None:
        return
    if _ok(api, "build P%d" % int(best)).startswith("ok"):
        mem["build_t"] = api.t
        api.count("build")


def _depots(api, mem):
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
    if _ok(api, "depot P%d" % best).startswith("ok"):
        mem["dep_t"] = api.t


def _civil(api, combat, refit):
    used = set()
    recs = [u for u in api.units if u.get("type") == "rec" and not u.get("path")]
    if api.unexplored:
        pick = [u["id"] for u in recs if not u.get("explore")]
        if pick:
            _ok(api, "explore " + _sel(pick))
    else:
        pick = [u["id"] for u in recs if not u.get("front")]
        if pick:
            _ok(api, "front " + _sel(pick))
    neutral = set(api.neutral_border)
    expanders = [u for u in combat if u.get("expand")]
    want = min(EXPAND_WANT, max(len(neutral), 1) * 2)
    need = want - len(expanders)
    if need > 0:
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
        ratio = MIN_RATIO_FORT if fort >= 1 else MIN_RATIO
        if sA < ratio * sE:
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
            api.count("assault")
        return


def tick(api):
    mem = api.mem
    combat = [u for u in api.units if u.get("type") != "rec"]
    ids = set(u["id"] for u in api.units)
    counts = {}
    for u in api.units:
        counts[u.get("type")] = counts.get(u.get("type"), 0) + 1

    for fn in (lambda: _diplomacy(api, mem),
               lambda: _sell(api, mem),
               lambda: _develop(api, mem),
               lambda: _build(api, mem),
               lambda: _depots(api, mem)):
        try:
            fn()
        except Exception:
            pass

    refit = set()
    try:
        refit = _refit_weak(api, mem, combat, ids)
    except Exception:
        refit = set(mem.get("refit", []))

    # research first: it sets how much res to save for the next discovery
    try:
        _research(api, mem)
    except Exception:
        mem["save"] = 0
    save = mem.get("save", 0)

    for fn in (lambda: _refit_old(api, refit, save),
               lambda: _recruit(api, counts, save)):
        try:
            fn()
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

```feedback
Upkeep took about 86% of income in my last war, and there is no way to see or reduce it except by not recruiting. A disband command would help. Refit was refused 2,720 times for units off supplied land; a unit flag or a filter in q army for "refittable now" would save wasted calls. api.budget is useful, but a per-kind upkeep-to-benefit figure would help choose the army size. Strategic stock (rare, rubber) piled up with no good sale: a public market or a price query would make surplus worth something. Research could also use a clearer "cost of waiting" signal, such as days until a discovery is affordable at current net income.
```

REVIEW: standard