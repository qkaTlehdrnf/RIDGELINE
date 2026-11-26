RESEARCH = ["farming", "conscription", "mining", "inf.weapons", "inf.protection",
            "medicine", "industry", "logistics", "atg.weapons", "arm.protection",
            "arm.weapons", "discipline", "drill", "staffwork", "fieldworks"]
ARMOUR = ("arm", "hvt", "mec")
EXPANDERS = ("cav", "mot", "inf", "mtn", "mil")
NO_FRONT = ("rec",)


def _ids(us):
    return ",".join(str(u["id"]) for u in us)


def _enemy_armour(api):
    n = 0
    for p, e in api.enemy.items():
        ty = e.get("types")
        if isinstance(ty, dict):
            for k, v in ty.items():
                if k in ARMOUR:
                    n += v
        elif isinstance(ty, (list, tuple)):
            n += sum(1 for k in ty if k in ARMOUR)
        elif isinstance(ty, str):
            n += sum(1 for k in ARMOUR if k in ty)
    return n


def _affordable(api, cost, extra_res):
    if not cost:
        return False
    for k in ("res", "steel", "oil", "rare"):
        need = cost.get(k, 0) or 0
        if k == "res":
            need += extra_res
        if need and api.stock.get(k, 0) < need:
            return False
    return True


def _research(api, m):
    if api.income <= 0 or len(api.research) >= 2:
        return
    active = set(r[0] for r in api.research)
    for line in RESEARCH:
        if line in active:
            continue
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        if not _affordable(api, t.get("cost"), 150):
            continue
        r = api.cmd("research %s" % line)
        if r.startswith("ok"):
            return


def _recruit(api, m):
    if api.t - m.get("last_rec", -99) < 2:
        return
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    inf_n = counts.get("inf", 0) + counts.get("mtn", 0) + counts.get("mil", 0)
    if api.income < 0 and inf_n > 10:
        return
    if counts.get("rec", 0) < 2 and api.unexplored:
        choice = "rec"
    elif _enemy_armour(api) > 0 and counts.get("atg", 0) < max(1, inf_n // 4):
        choice = "atg"
    elif counts.get("art", 0) < max(1, inf_n // 6) and api.stock.get("res", 0) > 400:
        choice = "art"
    else:
        choice = "inf"
    cost = api.costs.get(choice)
    if not cost:
        return
    if api.res < cost[0] + 60 or api.mp < cost[1]:
        return
    r = api.cmd("recruit %s P%d" % (choice, api.capital))
    if r.startswith("ok"):
        m["last_rec"] = api.t


def _deploy(api, m):
    units = api.units
    # scouts explore
    scouts = [u for u in units if u["type"] == "rec" and not u.get("explore")
              and not u.get("path")]
    if scouts and api.unexplored:
        api.cmd("explore %s" % _ids(scouts[:2]))
    # expansion
    nb = list(api.neutral_border)
    if nb:
        exp_now = [u for u in units if u.get("expand")]
        want = min(4, len(nb))
        if len(exp_now) < want:
            cand = [u for u in units if u["type"] in EXPANDERS
                    and not u.get("front") and not u.get("expand")
                    and not u.get("path") and u.get("state") == "ready"
                    and (u.get("str", 0) or 0) >= 60
                    and u.get("plan", -1) in (-1, None)]
            cand.sort(key=lambda u: 0 if u["type"] == "cav" else 1)
            for u in cand[: want - len(exp_now)]:
                api.cmd("expand %d" % u["id"])
    # idle units join the front
    idle = [u for u in units if not u.get("path") and not u.get("front")
            and not u.get("expand") and not u.get("explore")
            and u["type"] not in NO_FRONT and u.get("state") in ("ready", "refitting")
            and u.get("plan", -1) in (-1, None)]
    if idle:
        api.cmd("front " + _ids(idle))


def _attack(api, m):
    t = api.t
    prep = m.setdefault("prep", {})
    units = api.units
    # launch or cancel existing preparations
    for key in list(prep.keys()):
        tgt = int(key)
        start = prep[key]
        waited = t - start
        planners = [u for u in units if u.get("plan") == tgt]
        if not planners:
            if waited > 2:
                del prep[key]
            continue
        bonus = max((u.get("bonus", 0) or 0) for u in planners)
        if waited >= 6 and (bonus >= 15 or waited >= 18):
            api.cmd("move %s P%d" % (_ids(planners), tgt))
            del prep[key]
    if len(prep) >= 2:
        return
    # ready units grouped by province
    mine = {}
    for u in units:
        if u["type"] == "rec" or u.get("expand") or u.get("explore") or u.get("path"):
            continue
        if u.get("plan", -1) not in (-1, None):
            continue
        if (u.get("str", 0) or 0) < 50:
            continue
        if u.get("state") in ("routing", "broke", "pinned", "digging", "refitting"):
            continue
        mine.setdefault(u["prov"], []).append(u)
    best = None
    for pid in list(api.border.keys()):
        p = api.provs.get(pid)
        if not p:
            continue
        for q in p.get("nbrs", []):
            if str(q) in prep:
                continue
            tq = api.provs.get(q)
            if not tq or tq.get("owner") != "enemy":
                continue
            e = api.enemy.get(q)
            if not e:
                continue
            es = float(e.get("str", 0) or 0)
            seen = set()
            uniq = []
            for r in tq.get("nbrs", []):
                for u in mine.get(r, []):
                    if u["id"] not in seen:
                        seen.add(u["id"])
                        uniq.append(u)
            if len(uniq) < 3:
                continue
            os_ = sum((u.get("str", 0) or 0) * (u.get("rdy", 0) or 0) / 100.0 for u in uniq)
            need = 2.0 + 0.8 * (tq.get("fort", 0) or 0)
            if os_ < need * es + 30:
                continue
            ratio = os_ / (es + 1.0)
            if best is None or ratio > best[0]:
                best = (ratio, q, uniq)
    if best:
        _, q, uniq = best
        r = api.cmd("prepare %s P%d" % (_ids(uniq), q))
        if r.startswith("ok"):
            prep[str(q)] = t


def tick(api):
    m = api.mem
    m["n"] = m.get("n", 0) + 1
    try:
        _research(api, m)
    except Exception:
        pass
    try:
        _recruit(api, m)
    except Exception:
        pass
    try:
        _deploy(api, m)
    except Exception:
        pass
    try:
        _attack(api, m)
    except Exception:
        pass
