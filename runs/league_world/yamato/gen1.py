EXPAND_MIX = {"cav": 0.35, "inf": 0.25, "mil": 0.10, "mot": 0.15,
              "arm": 0.05, "rec": 0.05, "mtn": 0.05}
WAR_MIX = {"inf": 0.28, "mtn": 0.10, "mot": 0.10, "arm": 0.10, "art": 0.10,
           "atg": 0.10, "eng": 0.07, "grn": 0.07, "cav": 0.05, "rec": 0.03}

RESEARCH = ["farming", "drill", "mining", "medicine", "logistics",
            "inf.weapons", "inf.protection", "art.weapons", "atg.weapons",
            "arm.weapons", "arm.protection", "mot.mobility", "drilling",
            "refining", "discipline", "fieldworks", "industry", "staffwork",
            "conscription", "arm.mobility"]


def _terr_dfn(t):
    t = str(t)
    if "mount" in t:
        return 2.0
    if "hill" in t:
        return 1.5
    if "forest" in t:
        return 1.25
    return 1.0


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


def _recruit(api):
    costs = api.unit_costs
    if not costs:
        return
    mine = 0
    for p in api.provs.values():
        if p.get("owner") == "me":
            mine += 1
    if len(api.units) >= 40 + 10 * mine:
        return
    if api.income < 0 and api.stock.get("res", 0) < 300:
        return
    expanding = bool(api.neutral_border) and api.t < 1500
    mix = EXPAND_MIX if expanding else WAR_MIX
    count = {}
    for u in api.units:
        count[u["type"]] = count.get(u["type"], 0) + 1
    total = len(api.units) + 1
    res = api.stock.get("res", 0)
    steel = api.stock.get("steel", 0)
    oil = api.stock.get("oil", 0)
    rare = api.stock.get("rare", 0)
    mp = api.mp
    reserve = 80
    made = 0
    while made < 3:
        best = None
        for t, share in mix.items():
            c = costs.get(t)
            if not c:
                continue
            if res - c.get("res", 0) < reserve or mp < c.get("mp", 0):
                continue
            if steel < c.get("steel", 0) or oil < c.get("oil", 0) or rare < c.get("rare", 0):
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
        count[t] = count.get(t, 0) + 1
        total += 1
        made += 1


def _research(api):
    running = [r[0] for r in api.research]
    if len(running) >= 2:
        return
    stock = api.stock
    started = 0
    for line in RESEARCH:
        if len(running) + started >= 2:
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
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            started += 1


def _retreat(api):
    cap = api.capital
    n = 0
    for u in api.units:
        if n >= 10:
            break
        if u["str"] < 22 and not u.get("path") and u["prov"] != cap \
                and (u.get("fighting") or u.get("state") == "routing"):
            api.cmd("move %d P%d" % (u["id"], cap))
            n += 1


def _attack(api):
    prep = api.mem.setdefault("prep", {})

    # launch or abort prepared attacks
    by_t = {}
    for u in api.units:
        pl = u.get("plan", -1)
        if pl is not None and pl >= 0 and not u.get("path"):
            by_t.setdefault(pl, []).append(u)
    for tgt, us in by_t.items():
        ids = ",".join(str(u["id"]) for u in us)
        t0 = prep.get(str(tgt), api.t)
        b = max(u.get("bonus", 0) for u in us)
        if b > 1:
            b /= 100.0
        S = sum(u["str"] for u in us)
        E = api.enemy.get(tgt, {}).get("str", 0)
        if b >= 0.25 or api.t - t0 >= 20:
            if E and S < 2.2 * E:
                api.cmd("hold " + ids)
            else:
                api.cmd("move %s P%d" % (ids, tgt))
            prep.pop(str(tgt), None)

    # plan new attacks from standing stacks
    occupied = {}
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u["str"] < 45 or u.get("state") in ("routing", "shaken", "moving"):
            continue
        occupied.setdefault(u["prov"], []).append(u)

    for pid, us in occupied.items():
        pr = api.provs.get(pid)
        if not pr:
            continue
        if any(u.get("dry") for u in us):
            continue
        S = sum(u["str"] for u in us)
        if S < 100:
            continue
        avg_rdy = sum(u.get("rdy", 50) for u in us) / float(len(us))
        if avg_rdy < 55:
            continue
        best = None
        for nb in pr.get("nbrs", []):
            e = api.enemy.get(nb)
            if not e:
                continue
            E = max(e.get("str", 0), 1)
            nbp = api.provs.get(nb, {})
            fort = float(nbp.get("fort", 0) or 0)
            if S < (2.5 + fort) * E:
                continue
            p = _take_prob(api, S, E, nb, us)
            if p is None:
                p = 1.0 if S >= 3.0 * E else 0.0
            if p < 0.6:
                continue
            if best is None or p > best[0]:
                best = (p, nb)
        if best is None:
            continue
        nb = best[1]
        if str(nb) in prep:
            continue
        ids = ",".join(str(u["id"]) for u in us)
        api.cmd("prepare %s P%d" % (ids, nb))
        prep[str(nb)] = api.t


def _orders(api):
    border = api.border or {}
    neutral = api.neutral_border or []
    front_ids, explore_ids, rear = [], [], []
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u.get("front") or u.get("expand") or u.get("explore"):
            continue
        if u.get("state") in ("routing", "moving"):
            continue
        if u["type"] == "rec":
            explore_ids.append(u["id"])
        elif u["prov"] in border:
            front_ids.append(u["id"])
        elif u["type"] in ("cav", "inf", "mot", "mtn", "grn") and u["str"] >= 40:
            rear.append(u["id"])
        else:
            front_ids.append(u["id"])

    if explore_ids:
        api.cmd("explore " + ",".join(str(i) for i in explore_ids))
    if neutral and rear:
        api.cmd("expand " + ",".join(str(i) for i in rear))
    elif rear:
        front_ids += rear
    if front_ids:
        api.cmd("front " + ",".join(str(i) for i in front_ids))


def _groups(api):
    gn = api.mem.setdefault("gn", {})
    byp = {}
    for u in api.units:
        if u.get("front") and not u.get("path") and u.get("state") not in ("moving", "routing"):
            byp.setdefault(u["prov"], []).append(u)
    for pid, us in byp.items():
        if len(us) < 3:
            continue
        name = "fx%d" % pid
        members = gn.setdefault(name, set())
        new = [u["id"] for u in us if u["id"] not in members]
        if not new:
            continue
        ids = ",".join(str(i) for i in new)
        if members:
            r = api.cmd("group %s + %s" % (name, ids))
            if not r.startswith("ok"):
                api.cmd("group %s %s" % (name, ids))
        else:
            api.cmd("group %s %s" % (name, ids))
        members.update(new)


def tick(api):
    for f in (_recruit, _research, _retreat, _attack, _orders, _groups):
        try:
            f(api)
        except Exception:
            pass
