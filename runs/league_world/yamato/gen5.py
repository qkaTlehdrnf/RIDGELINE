EXPAND_MIX = {"inf": 0.30, "mil": 0.25, "cav": 0.15, "mot": 0.10, "eng": 0.08, "rec": 0.02}
WAR_MIX = {"inf": 0.22, "mtn": 0.06, "mot": 0.08, "arm": 0.06, "art": 0.12,
           "atg": 0.08, "eng": 0.08, "grn": 0.06, "cav": 0.04, "rec": 0.02,
           "mec": 0.04, "mil": 0.04}

# per-day upkeep of each unit type (from the rules briefing)
UPKEEP = {"inf": 0.09, "mil": 0.03, "mtn": 0.105, "mot": 0.135, "arm": 0.18,
          "art": 0.135, "eng": 0.09, "rec": 0.045, "cav": 0.084, "grn": 0.114,
          "atg": 0.075, "mec": 0.15, "hvt": 0.27, "rkt": 0.165}

RESEARCH = ["farming", "medicine", "mining", "logistics", "drill",
            "inf.protection", "art.weapons", "inf.weapons", "atg.weapons",
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
                if give <= get:
                    api.cmd("accept %s" % o["id"])
                else:
                    api.cmd("reject %s" % o["id"])
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
        api.cmd("offer %s pact" % f)


def _recruit(api):
    costs = api.unit_costs
    if not costs:
        return
    mine = sum(1 for p in api.provs.values() if p.get("owner") == "me")
    cap = 30 + 10 * mine
    if len(api.units) >= cap:
        return
    inc = api.income
    if inc < 4:
        return
    expanding = bool(api.neutral_border) and api.t < 2000
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
    reserve = 150
    made = 0
    while made < 2:
        best = None
        for t, share in mix.items():
            c = costs.get(t)
            if not c:
                continue
            if res - c.get("res", 0) < reserve or mp < c.get("mp", 0):
                continue
            if steel < c.get("steel", 0) or oil < c.get("oil", 0) or rare < c.get("rare", 0):
                continue
            # income after this unit's upkeep must stay positive
            if inc - UPKEEP.get(t, 0.1) < 3:
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
    running = [r[0] for r in api.research]
    if len(running) >= 2:
        return
    if api.income < 5:
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
        if stock.get("res", 0) - c.get("res", 0) < 250:
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
        if n >= 12:
            break
        if u["str"] < 30 and not u.get("path") and u["prov"] != cap \
                and (u.get("fighting") or u.get("state") in ("routing", "shaken")):
            api.cmd("move %d P%d" % (u["id"], cap))
            n += 1


def _grab(api):
    # send idle units straight into explored neutral provinces next to ours
    mem = api.mem.setdefault("grab", {})
    by_prov = {}
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u["type"] == "rec" or u.get("state") in ("routing", "moving", "shaken"):
            continue
        if u.get("str", 0) < 30:
            continue
        by_prov.setdefault(u["prov"], []).append(u)
    used = set()
    for pid, pr in api.provs.items():
        if pr.get("owner") != "me":
            continue
        for nb in pr.get("nbrs", []):
            q = api.provs.get(nb)
            if not q or q.get("owner") != "neutral":
                continue
            if nb in api.enemy:
                continue
            if api.t - mem.get(str(nb), -99) < 10:
                continue
            pool = [u for u in by_prov.get(pid, []) if u["id"] not in used]
            if not pool:
                continue
            # prefer units not holding the front
            pool.sort(key=lambda u: (1 if u.get("front") else 0, -u["str"]))
            u = pool[0]
            if u.get("front") and len(by_prov.get(pid, [])) < 4:
                continue
            r = api.cmd("move %d P%d" % (u["id"], nb))
            if r.startswith("ok"):
                used.add(u["id"])
                mem[str(nb)] = api.t


def _attack(api):
    prep = api.mem.setdefault("prep", {})

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
        if b >= 0.3 or api.t - t0 >= 12:
            if E and S < 2.5 * E:
                api.cmd("hold " + ids)
            else:
                api.cmd("move %s P%d" % (ids, tgt))
            prep.pop(str(tgt), None)

    occupied = {}
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u["str"] < 50 or u.get("state") in ("routing", "shaken", "moving"):
            continue
        occupied.setdefault(u["prov"], []).append(u)

    for pid, us in occupied.items():
        pr = api.provs.get(pid)
        if not pr:
            continue
        if any(u.get("dry") for u in us):
            continue
        S = sum(u["str"] for u in us)
        if S < 120:
            continue
        avg_rdy = sum(u.get("rdy", 50) for u in us) / float(len(us))
        if avg_rdy < 60:
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
                p = 1.0 if S >= 3.5 * E else 0.0
            if p < 0.65:
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
    front_ids, expand_ids, explore_ids = [], [], []
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u.get("front") or u.get("expand") or u.get("explore"):
            continue
        if u.get("state") in ("routing", "moving"):
            continue
        if u["type"] == "rec":
            explore_ids.append(u["id"])
        elif _contact(api, u["prov"]) or u["str"] < 40:
            front_ids.append(u["id"])
        else:
            expand_ids.append(u["id"])

    if explore_ids:
        api.cmd("explore " + ",".join(str(i) for i in explore_ids))
    if expand_ids:
        api.cmd("expand " + ",".join(str(i) for i in expand_ids))
    if front_ids:
        api.cmd("front " + ",".join(str(i) for i in front_ids))


def _fortify(api):
    ids = []
    for u in api.units:
        if u.get("path") or u.get("plan", -1) >= 0:
            continue
        if u.get("state") in ("digging", "routing", "moving"):
            continue
        if _contact(api, u["prov"]) and not u.get("f_set") and not u.get("fort_lv"):
            if u.get("state") == "ready" and not u.get("fighting"):
                ids.append(u["id"])
        if len(ids) >= 20:
            break
    if ids:
        api.cmd("fortify " + ",".join(str(i) for i in ids))


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
    for f in (_diplomacy, _recruit, _research, _retreat, _grab, _attack,
              _orders, _fortify, _groups):
        try:
            f(api)
        except Exception:
            pass
