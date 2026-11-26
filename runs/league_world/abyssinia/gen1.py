def tick(api):
    mem = api.mem
    now = api.t
    mem["ticks"] = mem.get("ticks", 0) + 1
    units = api.units
    byid = {}
    for u in units:
        byid[u["id"]] = u
    owned = []
    for i, p in api.provs.items():
        if p.get("owner") == "me":
            owned.append(i)
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1

    # ---- research: keep two projects running when affordable ----
    try:
        if len(api.research) < 2:
            lines = ["farming", "mining", "conscription", "industry",
                     "inf.weapons", "art.weapons", "arm.weapons", "arm.protection",
                     "inf.protection", "mot.mobility", "discipline", "logistics",
                     "medicine", "drill", "fieldworks", "staffwork", "refining"]
            for line in lines:
                tv = api.tech.get(line)
                if not tv or tv.get("status") != "open":
                    continue
                cost = tv.get("cost") or {}
                ok = True
                for k in cost:
                    if api.stock.get(k, 0) < cost[k] + 60:
                        ok = False
                if ok and api.cmd("research " + line).startswith("ok"):
                    break
    except Exception:
        pass

    # ---- recruitment: spend the stockpile, mix by weights ----
    try:
        rc = api.capital
        for c in owned:
            if api.provs[c].get("city") and c in api.border:
                rc = c
                break
        cap_units = 150 + 10 * len(owned)
        weights = {"inf": 4, "mot": 2, "arm": 2, "art": 2, "atg": 1,
                   "eng": 1, "mtn": 1, "mec": 1, "hvt": 1}
        res = api.res
        mp = api.mp
        st = dict(api.stock)
        total = len(units)
        for _ in range(10):
            if total >= cap_units:
                break
            best = None
            bs = 1e9
            for ty, w in weights.items():
                uc = api.unit_costs.get(ty)
                if not uc:
                    continue
                if res - uc.get("res", 0) < 150 or mp - uc.get("mp", 0) < 20:
                    continue
                if (st.get("steel", 0) < uc.get("steel", 0) or
                        st.get("oil", 0) < uc.get("oil", 0) or
                        st.get("rare", 0) < uc.get("rare", 0)):
                    continue
                sc = (counts.get(ty, 0) + 1) / float(w)
                if sc < bs:
                    bs = sc
                    best = ty
            if best is None:
                break
            r = api.cmd("recruit %s 1 P%d" % (best, rc))
            if not r.startswith("ok"):
                break
            uc = api.unit_costs[best]
            res -= uc.get("res", 0)
            mp -= uc.get("mp", 0)
            st["steel"] = st.get("steel", 0) - uc.get("steel", 0)
            st["oil"] = st.get("oil", 0) - uc.get("oil", 0)
            st["rare"] = st.get("rare", 0) - uc.get("rare", 0)
            counts[best] = counts.get(best, 0) + 1
            total += 1
    except Exception:
        pass

    # ---- one staged assault at a time: prepare, wait, check odds, move ----
    try:
        op = mem.get("op")
        if op:
            tgt = op["tgt"]
            alive = [i for i in op["ids"] if i in byid]
            if api.provs.get(tgt, {}).get("owner") == "me" or not alive or now - op["t0"] > 240:
                op = None
                mem["op"] = None
            elif not op["go"]:
                ready_ids = [i for i in alive if not byid[i].get("path")]
                my = 0
                for i in ready_ids:
                    my += byid[i]["str"]
                e = api.enemy.get(tgt)
                en = e.get("str", 0) if e else 0
                if now - op["t0"] >= 12 and my >= 2.5 * en and len(ready_ids) >= 4:
                    api.cmd("move %s P%d" % (",".join(str(i) for i in ready_ids), tgt))
                    op["go"] = True
                    op["t0"] = now
                elif now - op["t0"] > 36:
                    op = None
                    mem["op"] = None
            elif now - op["t0"] >= 30:
                op = None
                mem["op"] = None

        if not mem.get("op"):
            best = None
            bsc = -1e18
            for s in list(api.border.keys()):
                sp = api.provs.get(s)
                if not sp or sp.get("owner") != "me":
                    continue
                staged = []
                for u in units:
                    if (u["prov"] == s and not u.get("path") and u.get("state") == "ready"
                            and u["str"] >= 60 and u["type"] != "rec"):
                        staged.append(u)
                if len(staged) < 4:
                    continue
                my = 0
                for u in staged:
                    my += u["str"]
                for nb in sp.get("nbrs", []):
                    npr = api.provs.get(nb)
                    if not npr or npr.get("owner") == "me":
                        continue
                    own = npr.get("owner")
                    if own not in ("neutral", "enemy"):
                        continue
                    e = api.enemy.get(nb)
                    if own == "enemy" and e is None:
                        continue
                    en = e.get("str", 0) if e else 0
                    if my < 2.5 * en or my < 150:
                        continue
                    sc = my - 2 * en
                    if sc > bsc:
                        bsc = sc
                        best = (nb, staged)
            if best:
                nb, staged = best
                ids = [str(u["id"]) for u in staged]
                r = api.cmd("prepare %s P%d" % (",".join(ids), nb))
                if r.startswith("ok"):
                    mem["op"] = {"tgt": nb, "ids": [u["id"] for u in staged],
                                 "t0": now, "go": False}
    except Exception:
        pass

    # ---- assign idle units (operation units are left alone) ----
    try:
        opset = set()
        if mem.get("op"):
            opset = set(mem["op"]["ids"])
        explore_ids = []
        expand_ids = []
        front_ids = []
        for u in units:
            if u["id"] in opset or u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
                continue
            if u.get("state") != "ready":
                continue
            if u["type"] == "rec":
                explore_ids.append(str(u["id"]))
            elif api.neutral_border and len(expand_ids) < 15:
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

    mem["last_units"] = len(units)
