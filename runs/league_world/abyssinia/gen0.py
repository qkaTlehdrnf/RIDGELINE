def tick(api):
    mem = api.mem
    mem["ticks"] = mem.get("ticks", 0) + 1
    units = api.units
    cap = api.capital

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1

    # ---- research: start one open line per tick when affordable ----
    try:
        if len(api.research) < 2:
            lines = ["farming", "conscription", "inf.weapons", "inf.protection",
                     "mining", "art.weapons", "industry", "discipline"]
            for line in lines:
                t = api.tech.get(line)
                if not t or t.get("status") != "open":
                    continue
                cost = t.get("cost") or {}
                ok = True
                for k in cost:
                    if api.stock.get(k, 0) < cost[k]:
                        ok = False
                if ok:
                    r = api.cmd("research " + line)
                    if r.startswith("ok"):
                        break
    except Exception:
        pass

    # ---- recruitment: keep a mix, respect a unit cap that grows with land ----
    try:
        owned = 0
        for p in api.provs.values():
            if p.get("owner") == "me":
                owned += 1
        cap_units = 30 + 4 * owned
        res_left = api.res
        mp_left = api.mp
        weights = {"inf": 5, "atg": 1, "art": 1, "mot": 2, "cav": 1}
        total = len(units)
        for _ in range(3):
            if total >= cap_units:
                break
            best = None
            best_ratio = 10 ** 9
            for ty in weights:
                cost = api.costs.get(ty, (999, 999))
                if res_left < cost[0] + 40 or mp_left < cost[1] + 5:
                    continue
                ratio = (counts.get(ty, 0) + 1) / float(weights[ty])
                if ratio < best_ratio:
                    best_ratio = ratio
                    best = ty
            if best is None:
                break
            r = api.cmd("recruit %s 1 P%d" % (best, cap))
            if not r.startswith("ok"):
                break
            counts[best] = counts.get(best, 0) + 1
            total += 1
            res_left -= api.costs.get(best, (0, 0))[0]
            mp_left -= api.costs.get(best, (0, 0))[1]
    except Exception:
        pass

    # ---- assign idle units ----
    try:
        explore_ids = []
        expand_ids = []
        front_ids = []
        for u in units:
            if u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
                continue
            if u.get("state") != "ready":
                continue
            if u["type"] == "rec":
                explore_ids.append(str(u["id"]))
            elif api.neutral_border and len(expand_ids) < 12:
                expand_ids.append(str(u["id"]))
            else:
                front_ids.append(str(u["id"]))
        if explore_ids:
            api.cmd("explore " + ",".join(explore_ids))
        if expand_ids:
            api.cmd("expand " + ",".join(expand_ids))
        if front_ids:
            api.cmd("front " + ",".join(front_ids))
    except Exception:
        pass

    # ---- opportunistic attack: one move per tick, only with clear local superiority ----
    try:
        enemy = api.enemy
        attacked = False
        for p in list(api.border.keys()):
            if attacked:
                break
            pr = api.provs.get(p)
            if not pr:
                continue
            here = []
            for u in units:
                if (u["prov"] == p and not u.get("path") and u["str"] >= 75
                        and u.get("state") == "ready" and u["type"] != "rec"):
                    here.append(u)
            if len(here) < 4 or api.res < 80:
                continue
            my_str = 0
            for u in here:
                my_str += u["str"]
            for nb in pr.get("nbrs", []):
                npr = api.provs.get(nb)
                if not npr or npr.get("owner") == "me":
                    continue
                e = enemy.get(nb)
                en_str = e.get("str", 0) if e else 0
                if npr.get("owner") == "neutral" or (e and en_str * 1.3 < my_str):
                    ids = ",".join(str(u["id"]) for u in here)
                    api.cmd("move %s P%d" % (ids, nb))
                    attacked = True
                    break
    except Exception:
        pass

    mem["last_units"] = len(units)
