**Reasoning**

Last war ended 10th of 30 with 129 provinces. Assaults were the weak point: 8 of 369 succeeded, and the wins came at 1-30% plan bonus and high readiness. Meanwhile four factions repeatedly offered pacts that the policy never answered, so those fronts stayed open and drained units.

Changes:
- **Diplomacy:** accept incoming pacts, and offer pacts to met factions we have no active pact with, at most once every 72 h per faction.
- **Attack discipline:** require a 2.0 strength ratio (up from 1.6), a 0.6 model probability, and 3:1 against forts of level 2+. Plans wait 30 h to build the prepared bonus.
- **Targeting:** skip provinces owned by a pact partner, since the engine forbids those attacks anyway.
- **Kept:** the economy, recruitment mix, refit, grouping, and research logic, which worked. Research order is unchanged.

Each section runs in its own try block so one error cannot lose the whole tick. Per-tick cost is well under the time limit.

```python
RES_KEEP = 120
MAX_UNITS = 1800
ATTACK_STR = 50
ATTACK_RDY = 65
MAX_PLANS = 6
PREP_HOURS = 30
MIN_RATIO = 2.0
P_MIN = 0.6
REFIT_BELOW = 35
REFIT_DONE = 85
OFFER_EVERY = 72

TECH_ORDER = ["inf.weapons", "farming", "inf.protection", "conscription",
              "medicine", "arm.weapons", "art.weapons", "logistics", "mining",
              "drill", "discipline", "industry", "fieldworks", "staffwork",
              "inf.mobility", "arm.protection"]

WEIGHT = {"inf": 0.30, "arm": 0.22, "art": 0.15, "mot": 0.12,
          "mec": 0.08, "eng": 0.04, "atg": 0.04, "grn": 0.03, "rec": 0.02}

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


def _pact_on(api, f):
    p = api.pacts.get(f)
    if not p:
        return False
    ends = p.get("ends")
    return ends is None or ends > api.t


def _diplomacy(api, m):
    # accept every pact offered to us
    for o in api.offers_in:
        if o.get("kind") == "pact":
            api.cmd("accept %d" % o["id"])
    # offer pacts to met factions we are not bound to
    offered = m.setdefault("offered", {})
    for f in api.met:
        if _pact_on(api, f):
            continue
        if api.t - offered.get(f, -10000) < OFFER_EVERY:
            continue
        offered[f] = api.t
        api.cmd("offer %s pact" % f)


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
        if not u.get("supplied", True):
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
        owner = api.owner_name.get(T)
        if owner is not None and _pact_on(api, owner):
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
        fort = pr.get("fort", 0) or 0
        need = MIN_RATIO
        if fort >= 2:
            need = 3.0
        if att < need * est:
            continue
        lr = math.log((att + 1.0) / (est + 1.0))
        tdfn = DOWN.get(pr.get("elev", 0), 1.0)
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
    byid = dict((u["id"], u) for u in units)
    api.mem_byid = byid
    capital = api.capital

    for k in ("refit", "grouped", "plans"):
        if k not in m:
            m[k] = []

    # 0. diplomacy: accept pacts, offer pacts (every 6 hours)
    if t % 6 == 0:
        try:
            _diplomacy(api, m)
        except Exception:
            pass

    # 1. refit old-model units every 6 hours
    if t % 6 == 0:
        try:
            _refit(api, units, set(m["refit"]) | set(p_id for pl in m["plans"] for p_id in pl["ids"]))
        except Exception:
            pass

    # 2. recruitment every 2 hours
    if t % 2 == 0:
        try:
            _recruit(api, units)
        except Exception:
            pass

    # 3. scouting with rec
    try:
        recs = [u["id"] for u in units if u["type"] == "rec" and not u.get("path")
                and not u.get("explore") and not u.get("expand")]
        if recs:
            api.cmd("explore %s" % _sel(recs))
    except Exception:
        pass

    # 4. prepared attacks
    free = [u for u in units if not u.get("path")
            and u.get("state") not in ("preparing", "assault", "digging", "pinned", "routing")
            and u["id"] not in set(m["refit"])]
    try:
        _plan(api, m, t, free)
    except Exception:
        pass

    busy = set(i for p in m["plans"] for i in p["ids"])

    # 5. refit damaged units, return recovered ones
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

    # 6. expansion for idle units
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

    # 7. formations every 12 hours
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

    # 8. research
    try:
        _research(api)
    except Exception:
        pass

    m["calls"] = m.get("calls", 0) + 1
```

```letters
to kongo: Sahelia accepts your peace. Offer a pact and we keep fire off each other while it holds.
to maghreb: Sahelia accepts peace and fair trade. Send your pact; we will keep our units off yours.
to abyssinia: Sahelia agrees to hold our own land. Accept our pact offer and neither of us needs to fight.
```