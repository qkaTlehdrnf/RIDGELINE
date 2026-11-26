UPKEEP = {"inf": 0.09, "mil": 0.03, "mtn": 0.105, "mot": 0.135, "arm": 0.18,
          "art": 0.135, "eng": 0.09, "rec": 0.045, "cav": 0.084, "grn": 0.114,
          "atg": 0.075, "mec": 0.15, "hvt": 0.27, "rkt": 0.165}

# Land-taking mix (early, while neutral land is free) and war mix
MIX_EXP = {"mil": 0.40, "inf": 0.25, "cav": 0.10, "eng": 0.08, "art": 0.07, "atg": 0.10}
MIX_WAR = {"inf": 0.30, "mil": 0.08, "mtn": 0.08, "art": 0.10, "atg": 0.08,
           "eng": 0.05, "grn": 0.07, "arm": 0.05, "cav": 0.05, "mot": 0.07, "mec": 0.03}
LAND = ("mil", "inf", "cav", "mot", "eng")
PER_PROV = 30          # soft cap of units per border province (no more 499-unit stacks)
STOCK_OK = 60          # a border province must hold this much supply to take reinforcements
RESERVE = 250          # res kept back when recruiting
RESEARCH = ["farming", "conscription", "mining", "drilling", "medicine",
            "drill", "inf.protection", "logistics", "inf.weapons",
            "discipline", "fieldworks", "atg.weapons", "staffwork",
            "industry", "art.weapons", "mot.mobility", "arm.protection",
            "arm.weapons", "refining"]


def _terr_dfn(t):
    t = str(t)
    if "mount" in t:
        return 2.0
    if "hill" in t:
        return 1.5
    if "forest" in t:
        return 1.25
    return 1.0


def _contact(api, pid):
    pr = api.provs.get(pid)
    if not pr:
        return False
    for nb in pr.get("nbrs", []):
        q = api.provs.get(nb)
        if q and q.get("owner") == "enemy":
            return True
        if nb in api.enemy:
            return True
    return False


def _border(api):
    return set(pid for pid, pr in api.provs.items()
               if pr.get("owner") == "me" and _contact(api, pid))


def _owned(api):
    return sum(1 for p in api.provs.values() if p.get("owner") == "me")


def _cap(api):
    return min(220, 12 + 6 * _owned(api))


def _ids(lst):
    return ",".join(str(i) for i in lst)


def _take_prob(api, S, E, nb, us):
    m = api.model
    if not m or "w" not in m:
        return None
    n = float(len(us) or 1)
    heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / n
    rdy = sum(u.get("rdy", 50) for u in us) / n / 100.0
    bonus = max([u.get("bonus", 0) for u in us] + [0])
    if bonus > 1:
        bonus /= 100.0
    nbp = api.provs.get(nb, {})
    feats = [
        math.log((S + 1.0) / (E + 1.0)),
        _terr_dfn(nbp.get("terrain", "")),
        float(nbp.get("fort", 0) or 0),
        1.0 if nbp.get("city") else 0.0,
        bonus,
        rdy,
        heavy,
        1.0,
    ]
    z = m["b"]
    for i, x in enumerate(feats):
        z += m["w"][i] * (x - m["mean"][i]) / m["std"][i]
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _diplomacy(api):
    for o in list(api.offers_in or []):
        try:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o["id"])
            elif o.get("kind") == "trade":
                give = sum((o.get("you_give") or {}).values())
                get = sum((o.get("they_give") or {}).values())
                api.cmd(("accept %s" if give <= get else "reject %s") % o["id"])
        except Exception:
            pass
    pacts = api.pacts or {}
    last = api.mem.setdefault("pact_offer", {})
    for f in (api.met or []):
        if f in pacts:
            continue
        if api.t - last.get(f, -999) < 96:
            continue
        last[f] = api.t
        api.cmd("offer %s pact 240" % f)
    if api.stock.get("steel", 0) > 200 and api.stock.get("res", 0) < 150 and api.met:
        if api.t - api.mem.get("trade_t", -999) >= 96:
            cands = [f for f in api.met if f in pacts] or list(api.met)
            api.cmd("offer %s trade 100 steel for 100 res" % cands[0])
            api.mem["trade_t"] = api.t


def _recruit(api, B):
    costs = api.unit_costs
    if not costs or api.income < 10:          # never add upkeep while thin
        return
    limit = _cap(api)
    if B:
        known = [api.provs[p].get("stock", 0) for p in B if p in api.provs]
        if known and sum(known) / float(len(known)) < 80:
            return                             # border is starving: do not add mouths
        limit = min(limit, PER_PROV * len(B) + 40)
    if len(api.units) >= limit:
        return
    mix = MIX_EXP if (api.neutral_border and api.t < 1500) else MIX_WAR
    count = {}
    for u in api.units:
        count[u["type"]] = count.get(u["type"], 0) + 1
    total = len(api.units) + 1
    res = api.stock.get("res", 0)
    steel = api.stock.get("steel", 0)
    oil = api.stock.get("oil", 0)
    rare = api.stock.get("rare", 0)
    mp = api.mp
    inc = api.income
    made = 0
    while made < 2:
        best = None
        for t, share in mix.items():
            c = costs.get(t)
            if not c:
                continue
            if res - c.get("res", 0) < RESERVE or mp < c.get("mp", 0):
                continue
            if steel < c.get("steel", 0) or oil < c.get("oil", 0) or rare < c.get("rare", 0):
                continue
            if inc - UPKEEP.get(t, 0.1) < 8:
                continue
            deficit = share * total - count.get(t, 0)
            if best is None or deficit > best[0]:
                best = (deficit, t, c)
        if best is None or best[0] <= 0:
            break
        _, t, c = best
        r = api.cmd("recruit %s P%d" % (t, api.capital))
        if not r.startswith("ok"):
            break
        res -= c.get("res", 0)
        mp -= c.get("mp", 0)
        steel -= c.get("steel", 0)
        oil -= c.get("oil", 0)
        rare -= c.get("rare", 0)
        inc -= UPKEEP.get(t, 0.1)
        count[t] = count.get(t, 0) + 1
        total += 1
        made += 1


def _research(api):
    running = [r[0] for r in (api.research or [])]
    if len(running) >= 2 or api.income < 6:
        return
    stock = api.stock
    for line in RESEARCH:
        if len(running) >= 2:
            break
        if line in running:
            continue
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        c = t.get("cost")
        if not c:
            continue
        if stock.get("res", 0) - c.get("res", 0) < 150:
            continue
        if not all(stock.get(k, 0) >= v for k, v in c.items() if k != "res"):
            continue
        if api.cmd("research " + line).startswith("ok"):
            running.append(line)


def _economy(api):
    # one development level at a time, only when income can carry it
    if api.t < 24 or api.income < 8 or api.stock.get("res", 0) < 350:
        return
    econ = api.economy or {}
    works = econ.get("works") or []
    if len(works) >= 2:
        return
    best = None
    for pr in econ.get("provs") or []:
        pid = pr.get("prov")
        c = pr.get("dev_cost")
        if pid is None or not c or pr.get("dev", 6) >= 4:
            continue
        if api.stock.get("res", 0) - c < 200:
            continue
        if api.provs.get(pid, {}).get("owner") != "me":
            continue
        y = pr.get("yield_now", 0) or 0
        if best is None or y > best[0]:
            best = (y, pid)
    if best and api.cmd("develop P%d" % best[1]).startswith("ok"):
        pass


def _depots(api, B):
    # one forward depot at a time, far from the capital, every 48 h
    if api.t < 48 or api.t - api.mem.get("dep_t", -999) < 48:
        return
    dep = api.depots or {}
    if len(dep) >= 4 or api.stock.get("res", 0) < 450:
        return
    cap = api.capital
    best = None
    for pid in B:
        if pid in dep:
            continue
        pr = api.provs.get(pid, {})
        if not pr.get("supplied", True):
            continue
        path = api.path(cap, pid) or []
        d = len(path)
        if d < 3:
            continue
        if best is None or d > best[0]:
            best = (d, pid)
    if best:
        if api.cmd("depot P%d 1" % best[1]).startswith("ok"):
            api.cmd("depot P%d 3" % cap)      # treasury stays mostly at home
            api.mem["dep_t"] = api.t


def _manage(api, B):
    cap = api.capital
    fill = {p: 0 for p in B}
    for u in api.units:
        if u["prov"] in B:
            fill[u["prov"]] = fill.get(u["prov"], 0) + 1

    def stock(q):
        return (api.provs.get(q) or {}).get("stock", 0)

    rec, rest, hold, expand = [], [], [], []
    garrison = {}
    land_free = bool(api.neutral_border)
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u.get("state") in ("routing", "moving", "refitting", "assault"):
            continue
        if u["type"] == "rec":
            if not u.get("explore"):
                rec.append(u["id"])
            continue
        p = u["prov"]
        s = u.get("str", 0)
        inB = p in B
        if s < 40 and (inB or u.get("front") or u.get("fighting")):
            if p != cap:
                rest.append(u["id"])
            continue
        if u.get("expand"):
            continue
        if not inB and land_free and u["type"] in LAND and s >= 30:
            expand.append(u["id"])
            continue
        if u.get("front"):
            hold.append(u["id"])          # drop the front order: we place units ourselves
        if inB and fill.get(p, 0) <= PER_PROV:
            continue
        if s < 45 or not B:
            continue
        # prefer provinces that are fed and not yet full
        open_ = [q for q in B if fill.get(q, 0) < PER_PROV]
        if not open_:
            continue
        dest = max(open_, key=lambda q: ((stock(q) >= STOCK_OK) * 100) - fill.get(q, 0))
        if inB and dest == p:
            continue
        fill[dest] = fill.get(dest, 0) + 1
        garrison.setdefault(dest, []).append(u["id"])
    if rec:
        api.cmd("explore " + _ids(rec))
    if rest:
        api.cmd("move %s P%d" % (_ids(rest), cap))
    if hold:
        api.cmd("hold " + _ids(hold))
    if expand:
        api.cmd("expand " + _ids(expand))
    for dest, lst in garrison.items():
        api.cmd("move %s P%d" % (_ids(lst), dest))


def _attack(api, B):
    prep = api.mem.setdefault("prep", {})
    by_t = {}
    for u in api.units:
        pl = u.get("plan", -1)
        if pl is not None and pl >= 0 and not u.get("path"):
            by_t.setdefault(pl, []).append(u)
    for tgt, us in by_t.items():
        ids = _ids([u["id"] for u in us])
        t0 = prep.get(str(tgt), api.t)
        b = max(u.get("bonus", 0) for u in us)
        if b > 1:
            b /= 100.0
        S = sum(u["str"] for u in us)
        E = (api.enemy.get(tgt) or {}).get("str", 0)
        if b >= 0.3 or api.t - t0 >= 12:
            if E and S < 2.5 * E:
                api.cmd("hold " + ids)
            else:
                api.cmd("move %s P%d" % (ids, tgt))
            prep.pop(str(tgt), None)

    occ = {}
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u["prov"] not in B:
            continue
        if u["str"] < 50 or u.get("state") in ("routing", "shaken", "moving", "digging"):
            continue
        occ.setdefault(u["prov"], []).append(u)

    for pid, us in occ.items():
        if len(us) < 4 or any(u.get("dry") for u in us):
            continue
        S = sum(u["str"] for u in us)
        if S < 300:
            continue
        if sum(u.get("rdy", 50) for u in us) / float(len(us)) < 55:
            continue
        pr = api.provs.get(pid, {})
        if pr.get("stock", 0) < STOCK_OK:
            continue
        best = None
        for nb in pr.get("nbrs", []):
            e = api.enemy.get(nb)
            if not e:
                continue
            E = max(e.get("str", 0), 1)
            nbp = api.provs.get(nb, {})
            fort = float(nbp.get("fort", 0) or 0)
            if fort >= 2:
                continue
            if S < (2.5 + fort) * E:
                continue
            p = _take_prob(api, S, E, nb, us)
            if p is None:
                p = 1.0
            if p < 0.6:
                continue
            if best is None or p > best[0]:
                best = (p, nb)
        if best is None or str(best[1]) in prep:
            continue
        nb = best[1]
        api.cmd("prepare %s P%d" % (_ids([u["id"] for u in us]), nb))
        prep[str(nb)] = api.t


def _fortify(api, B):
    ids = []
    for u in api.units:
        if u["prov"] not in B or u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u.get("state") != "ready" or u.get("fighting"):
            continue
        if u.get("str", 0) < 60 or u.get("fort_lv") or u.get("f_set"):
            continue
        ids.append(u["id"])
        if len(ids) >= 20:
            break
    if ids:
        api.cmd("fortify " + _ids(ids))


def _groups(api, B):
    gn = api.mem.setdefault("gn", {})
    byp = {}
    for u in api.units:
        if u["prov"] in B and not u.get("path") and u.get("state") not in ("moving", "routing"):
            byp.setdefault(u["prov"], []).append(u)
    for pid, us in byp.items():
        if len(us) < 3:
            continue
        name = "g%d" % pid
        members = gn.setdefault(name, set())
        new = [u["id"] for u in us if u["id"] not in members]
        if not new:
            continue
        ids = _ids(new)
        if members:
            r = api.cmd("group %s + %s" % (name, ids))
            if not r.startswith("ok"):
                api.cmd("group %s %s" % (name, ids))
        else:
            api.cmd("group %s %s" % (name, ids))
        members.update(new)


def tick(api):
    for f in (_diplomacy, _research):
        try:
            f(api)
        except Exception:
            pass
    try:
        B = _border(api)
    except Exception:
        B = set()
    for f in (_recruit, _economy, _depots):
        try:
            f(api, B) if f is not _economy else f(api)
        except Exception:
            pass
    try:
        _manage(api, B)
    except Exception:
        pass
    for f in (_attack, _fortify, _groups):
        try:
            f(api, B)
        except Exception:
            pass
