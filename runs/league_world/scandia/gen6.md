**Reasoning**

Every war ends at 28-29 of 30 with 30 provinces. We never gained land after the first days, while 1,854 neutral provinces were free on day 5. Economically we are bankrupt: 49 res, -3/day, with 1,689 steel and 1,618 oil idle. Most units sit at readiness 33 in a static front, and only one depot feeds the whole army.

The rewrite targets these failures:
- **Land grab first.** Interior units move into explored neutral provinces next to our land, with claims tracked so units don't double up. Harsh land goes last. Rec scouts explore all unknown edges.
- **Economy.** Recruit only when income is non-negative or res is large. Lean on cheap militia early, and use steel/oil-cost types since those stockpiles are idle.
- **Readiness.** Border units stay on the front order. Interior idle units hold and rest, which recovers readiness.
- **Supply.** Open forward depots on the far border once res allows. Depot placement is the agent's choice.
- **Attacks.** Keep the existing odds-gated strike logic, since it has been stable.

I could not test this against the engine, so the expansion path is the main risk. I log grabs with `api.count` so the next review shows whether it works.

```python
MIX = {"mil": 0.22, "inf": 0.22, "mot": 0.08, "arm": 0.08, "art": 0.09,
       "atg": 0.06, "eng": 0.06, "mtn": 0.04, "cav": 0.04, "mec": 0.05,
       "hvt": 0.03, "grn": 0.03}
PREF_RES = ["farming", "conscription", "inf.weapons", "arm.weapons",
            "atg.weapons", "art.weapons", "mot.mobility", "medicine",
            "arm.protection", "inf.protection", "discipline", "drill",
            "staffwork", "logistics", "fieldworks", "mec.weapons",
            "industry", "mining", "drilling"]
EXPAND_TYPES = ("inf", "mil", "mtn", "mot", "cav", "eng", "mec", "arm", "grn")
MIN_RATIO = 4.0
FORT_EXTRA = 3.0
MIN_ATTACKERS = 8
PREP_HOURS = 24
MAX_STRIKE = 14
GRAB_PER_TICK = 6
MAX_REFIT = 12
MAX_REC = 3
RES_RESERVE = 200
DEPOT_GAP = 240
MAX_DEPOTS = 3


def _can(api, t, bud):
    uc = api.unit_costs.get(t)
    if not uc:
        return False
    if bud["res"] < uc.get("res", 0) + RES_RESERVE:
        return False
    if bud["mp"] < uc.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if bud[k] < uc.get(k, 0):
            return False
    return True


def _spend(api, t, bud):
    uc = api.unit_costs.get(t, {})
    bud["res"] -= uc.get("res", 0)
    bud["mp"] -= uc.get("mp", 0)
    for k in ("steel", "oil", "rare"):
        bud[k] -= uc.get(k, 0)


def _ids(items):
    out = []
    for x in items:
        out.append(str(x["id"]) if isinstance(x, dict) else str(x))
    return ",".join(out)


def _recruit(api, units):
    # upkeep is paid from income: do not grow the army on a loss
    if api.income < 2 and api.res < 400:
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    bud = {"res": api.res, "mp": api.mp,
           "steel": api.stock.get("steel", 0),
           "oil": api.stock.get("oil", 0),
           "rare": api.stock.get("rare", 0)}
    if counts.get("rec", 0) < MAX_REC and _can(api, "rec", bud):
        if api.cmd("recruit rec P%d" % api.capital).startswith("ok"):
            counts["rec"] = counts.get("rec", 0) + 1
            _spend(api, "rec", bud)
    for _ in range(3):
        total = sum(counts.values()) + 1
        pick = None
        best = -1e9
        for t, w in MIX.items():
            if not _can(api, t, bud):
                continue
            d = w * total - counts.get(t, 0)
            if d > best:
                best = d
                pick = t
        if pick is None:
            break
        if not api.cmd("recruit %s P%d" % (pick, api.capital)).startswith("ok"):
            break
        counts[pick] = counts.get(pick, 0) + 1
        _spend(api, pick, bud)


def _research(api):
    if len(api.research) >= 2:
        return
    busy = set(r[0] for r in api.research)
    for line in PREF_RES:
        if line in busy:
            continue
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        cost = t.get("cost") or {}
        if api.res < cost.get("res", 0) + 60:
            continue
        ok = True
        for k, v in cost.items():
            if k != "res" and api.stock.get(k, 0) < v:
                ok = False
        if ok:
            api.cmd("research %s" % line)
            return


def _refit(api, units):
    if api.old_units <= 0 or api.income < 0:
        return
    if api.mem.get("refit_t", -99) > api.t - 4:
        return
    api.mem["refit_t"] = api.t
    cands = [u for u in units if u.get("old") and u.get("state") == "ready"
             and not u.get("path") and u.get("supplied")
             and u.get("prov") not in api.border]
    if not cands:
        return
    picked = []
    res_need = 0
    steel_need = 0
    oil_need = 0
    rare_need = 0
    for u in cands:
        if len(picked) >= MAX_REFIT:
            break
        rc = api.refit_cost.get(u["type"], {})
        if api.res - res_need - rc.get("res", 0) < 80:
            break
        if api.stock.get("steel", 0) - steel_need < rc.get("steel", 0):
            continue
        if api.stock.get("oil", 0) - oil_need < rc.get("oil", 0):
            continue
        if api.stock.get("rare", 0) - rare_need < rc.get("rare", 0):
            continue
        res_need += rc.get("res", 0)
        steel_need += rc.get("steel", 0)
        oil_need += rc.get("oil", 0)
        rare_need += rc.get("rare", 0)
        picked.append(u)
    if picked:
        api.cmd("refit " + _ids(picked))


def _attackers(api, tgt, units):
    nb = api.provs.get(tgt, {}).get("nbrs", [])
    out = []
    for u in units:
        if u.get("prov") not in nb:
            continue
        if api.provs.get(u.get("prov"), {}).get("owner") != "me":
            continue
        if u.get("path") or u.get("type") == "rec":
            continue
        if u.get("state") not in ("ready", "preparing"):
            continue
        if u.get("str", 0) < 70 or u.get("rdy", 0) < 80:
            continue
        out.append(u)
    return out


def _odds(att, es):
    if es is None:
        return 0.0
    s = sum(u.get("str", 0) for u in att)
    return s / max(float(es), 1.0)


def _need(api, tgt):
    fort = api.provs.get(tgt, {}).get("fort") or 0
    return MIN_RATIO + (FORT_EXTRA if fort >= 2 else 0.0)


def _free_rec(units):
    for u in units:
        if u["type"] == "rec" and u["state"] == "ready" and not u["path"] \
                and not u["explore"]:
            return u
    return None


def _stage_rec(api, units, att):
    r = _free_rec(units)
    if r is None or not att:
        return
    dest = att[0].get("prov")
    if dest is not None and r.get("prov") != dest:
        api.cmd("move %d P%d" % (r["id"], dest))


def _strike(api, units):
    m = api.mem
    prep = m.get("prep")
    if prep:
        tgt, t0, ids = prep
        if api.provs.get(tgt, {}).get("owner") == "me":
            m["prep"] = None
            return
        if api.t - t0 < PREP_HOURS:
            return
        m["prep"] = None
        byid = dict((u["id"], u) for u in units)
        alive = [byid[i] for i in ids if i in byid]
        if not alive:
            return
        att = _attackers(api, tgt, alive)
        es = api.enemy.get(tgt, {}).get("str")
        if len(att) >= MIN_ATTACKERS and _odds(att, es) >= _need(api, tgt) * 0.9:
            api.cmd("move %s P%d" % (_ids(att), tgt))
        else:
            api.cmd("hold %s" % _ids(alive))
        return

    own = [p for p, pr in api.provs.items() if pr.get("owner") == "me"]
    cands = set()
    for p in own:
        for nb in api.provs[p].get("nbrs", []):
            pr = api.provs.get(nb)
            if pr and pr.get("owner") == "enemy":
                cands.add(nb)
    best = None
    for tgt in cands:
        es = api.enemy.get(tgt, {}).get("str")
        if es is None:
            continue
        att = _attackers(api, tgt, units)
        if len(att) < MIN_ATTACKERS:
            continue
        r = _odds(att, es)
        if r >= _need(api, tgt) and (best is None or r > best[0]):
            best = (r, tgt, att)
    if best:
        r, tgt, att = best
        att = att[:MAX_STRIKE]
        ids = [u["id"] for u in att]
        _stage_rec(api, units, att)
        api.cmd("prepare %s P%d" % (_ids(ids), tgt))
        m["prep"] = (tgt, api.t, ids)


def _targets(api):
    # explored neutral provinces next to our land, nearest to the capital first;
    # harsh land (almost no yield) goes last
    own = [p for p, pr in api.provs.items() if pr.get("owner") == "me"]
    seen = set()
    out = []
    cap = api.provs.get(api.capital, {})
    cx, cy = cap.get("x", 0), cap.get("y0", 0)
    for p in own:
        for nb in api.provs[p].get("nbrs", []):
            if nb in seen:
                continue
            seen.add(nb)
            pr = api.provs.get(nb)
            if not pr or pr.get("owner") != "neutral":
                continue
            d = (pr.get("x", 0) - cx) ** 2 + (pr.get("y0", 0) - cy) ** 2
            if pr.get("harsh"):
                d += 1000000
            out.append((d, nb))
    out.sort()
    return [nb for d, nb in out]


def _grab(api, units, used):
    # interior units walk into free neutral land; claims are tracked so
    # two units never go for the same province
    m = api.mem
    claims = m.get("claims", {})
    byid = dict((u["id"], u) for u in units)
    live = {}
    for k, (tgt, t0) in claims.items():
        u = byid.get(int(k))
        if not u or api.provs.get(tgt, {}).get("owner") == "me":
            continue
        if api.t - t0 > 96:
            continue
        if not u.get("path") and u.get("prov") != tgt:
            continue
        live[k] = (tgt, t0)
    claimed = set(v[0] for v in live.values())
    targets = [t for t in _targets(api) if t not in claimed]
    if targets:
        cands = [u for u in units if u.get("state") == "ready" and not u.get("path")
                 and u["type"] in EXPAND_TYPES and not u.get("explore")
                 and u["id"] not in used and u.get("prov") not in api.border]
        cands.sort(key=lambda u: -u.get("str", 0))
        k = 0
        made = 0
        for tgt in targets:
            if made >= GRAB_PER_TICK or k >= len(cands):
                break
            u = cands[k]
            k += 1
            if api.cmd("move %d P%d" % (u["id"], tgt)).startswith("ok"):
                live[str(u["id"])] = (tgt, api.t)
                used.add(u["id"])
                made += 1
                api.count("grab_order")
    m["claims"] = live


def _depot(api):
    # forward depot on the far border once the treasury can pay for it
    if api.res < 600 or api.income < 0:
        return
    if api.t - api.mem.get("depot_t", -999) < DEPOT_GAP:
        return
    if len(api.depots) >= MAX_DEPOTS:
        return
    cap = api.provs.get(api.capital, {})
    cx, cy = cap.get("x", 0), cap.get("y0", 0)
    pool = [p for p in api.border if api.provs.get(p, {}).get("owner") == "me"]
    if not pool:
        pool = [p for p, pr in api.provs.items() if pr.get("owner") == "me"]
    best = None
    for p in pool:
        if p in api.depots or p == api.capital:
            continue
        pr = api.provs.get(p, {})
        if not pr.get("supplied"):
            continue
        d = abs(pr.get("x", 0) - cx) + abs(pr.get("y0", 0) - cy)
        if best is None or d > best[0]:
            best = (d, p)
    if best:
        api.cmd("depot P%d 1" % best[1])
        api.mem["depot_t"] = api.t


def _diplomacy(api, n):
    for o in list(api.offers_in):
        oid = o.get("id")
        if o.get("kind") == "pact":
            api.cmd("accept %s" % oid)
            continue
        if o.get("kind") == "trade":
            give = o.get("you_give", {})
            ok = True
            for k, v in give.items():
                if k in ("steel", "oil"):
                    if api.stock.get(k, 0) < v + 100:
                        ok = False
                elif k == "res":
                    if v > 150:
                        ok = False
                else:
                    ok = False
            if ok:
                api.cmd("accept %s" % oid)
    if n % 36 == 0:
        pending = set(o.get("to") for o in api.offers_out)
        for f in api.met:
            if f in api.pacts or f in pending:
                continue
            api.cmd("offer %s pact 240" % f)
    if n % 96 == 0:
        for f in api.met:
            api.cmd("say %s Scandia keeps its pacts and takes only free land." % f)


def tick(api):
    m = api.mem
    n = m.get("n", 0) + 1
    m["n"] = n
    units = api.units

    try:
        _recruit(api, units)
    except Exception:
        pass

    try:
        _research(api)
    except Exception:
        pass

    try:
        _diplomacy(api, n)
    except Exception:
        pass

    try:
        _depot(api)
    except Exception:
        pass

    used = set()
    try:
        if api.unexplored:
            explorers = [u for u in units if u["type"] == "rec" and u["state"] == "ready"
                         and not u["path"] and not u["explore"]]
            if explorers:
                api.cmd("explore " + _ids(explorers[:MAX_REC]))
                used.update(u["id"] for u in explorers[:MAX_REC])
    except Exception:
        pass

    try:
        _strike(api, units)
        for u in units:
            if u["state"] == "preparing":
                used.add(u["id"])
    except Exception:
        pass

    try:
        _refit(api, units)
    except Exception:
        pass

    try:
        _grab(api, units, used)
    except Exception:
        pass

    idle = [u for u in units if u.get("state") == "ready" and not u.get("path")
            and not u.get("front") and not u.get("expand") and not u.get("explore")
            and u["type"] != "rec" and u["id"] not in used]
    bord = api.border
    try:
        fr = [str(u["id"]) for u in idle if u.get("prov") in bord]
        if fr:
            api.cmd("front " + ",".join(fr))
    except Exception:
        pass
    try:
        rest = [str(u["id"]) for u in idle if u.get("prov") not in bord]
        if rest and n % 2 == 0:
            api.cmd("hold " + ",".join(rest))
    except Exception:
        pass

    try:
        if n % 12 == 0:
            core = ("inf", "mtn", "mil", "atg", "mec", "arm", "hvt", "art", "grn")
            new = [str(u["id"]) for u in units if u.get("front") and not u.get("group")
                   and u["type"] in core]
            if new:
                if not m.get("grp"):
                    api.cmd("group line " + ",".join(new))
                    m["grp"] = True
                else:
                    api.cmd("group line + " + ",".join(new))
    except Exception:
        pass

    m["calls"] = n
```

REVIEW: full