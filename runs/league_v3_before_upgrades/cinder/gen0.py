def _sig(x):
    if x < -30: return 0.0
    if x > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-x))

TD = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}

def _p(api, att, dfs, pr, bonus, rdy, heavy, dirs):
    m = api.model or {}
    w = m.get("w"); mean = m.get("mean"); sd = m.get("std")
    lr = math.log((att + 1.0) / (dfs + 1.0))
    if not w:
        return _sig(1.5 * lr - 0.5 + bonus)
    x = [lr, TD.get(pr.get("terrain"), 1.0) + (0.25 if pr.get("city") else 0),
         pr.get("fort", 0) or 0, 1.0 if pr.get("city") else 0.0, bonus, rdy, heavy, dirs]
    s = m.get("b", 0.0)
    for i in range(len(w)):
        s += w[i] * (x[i] - mean[i]) / (sd[i] or 1.0)
    return _sig(s)

def _ids(l):
    return ",".join(str(i) for i in l)

def tick(api):
    mem = api.mem
    t = api.t
    ops = mem.setdefault("ops", {})
    units = api.units
    byid = {u["id"]: u for u in units}
    provs = api.provs
    inop = set()
    for k in ops:
        for i in ops[k]["u"]:
            inop.add(i)

    # ---------- recruitment ----------
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    n = len(units)
    made = 0
    while made < 3:
        if cnt.get("rec", 0) < (2 if n < 40 else 3):
            ty = "rec"
        elif cnt.get("eng", 0) < 1 + n // 18 and n >= 8:
            ty = "eng"
        elif cnt.get("art", 0) * 4 < n and n >= 6:
            ty = "art"
        else:
            ty = "inf"
        c = api.costs.get(ty)
        if not c: break
        if api.res < c[0] or api.mp < c[1] + 10: break
        if n > 6 and api.income < 4: break
        r = api.cmd("recruit %s 1" % ty)
        if not r.startswith("ok"): break
        cnt[ty] = cnt.get(ty, 0) + 1
        n += 1
        made += 1

    # ---------- manage operations ----------
    for tg in list(ops.keys()):
        op = ops[tg]
        alive = [i for i in op["u"] if i in byid]
        op["u"] = alive
        pr = provs.get(tg, {})
        done = (not alive) or pr.get("owner") == "me" or (t - op["s"] > 110)
        if op.get("go") and t - op["go"] > 72: done = True
        if done:
            if alive: api.cmd("front " + _ids(alive))
            del ops[tg]
            continue
        if not op.get("go"):
            us = [byid[i] for i in alive]
            bon = sum(u.get("bonus", 0) or 0 for u in us) / max(1, len(us))
            e = api.enemy.get(tg)
            dstr = e["str"] if e else 0
            att = sum(u["str"] for u in us)
            rdy = sum(u["rdy"] for u in us) / max(1, len(us)) / 100.0
            heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / max(1, len(us))
            dirs = len(set(u["prov"] for u in us))
            p = _p(api, att, dstr, pr, bon / 100.0, rdy, heavy, dirs)
            if (bon >= 30 or t - op["s"] >= 36) and p >= 0.5:
                api.cmd("move %s P%d" % (_ids(alive), tg))
                op["go"] = t
            elif t - op["s"] >= 48 and p < 0.35:
                api.cmd("front " + _ids(alive))
                del ops[tg]

    inop = set()
    for k in ops:
        for i in ops[k]["u"]:
            inop.add(i)

    # ---------- plan new operations ----------
    if len(ops) < 3 and t % 12 < 6:
        # units per own province
        byprov = {}
        for u in units:
            byprov.setdefault(u["prov"], []).append(u)
        cands = []
        for pid, pr in provs.items():
            if pr.get("owner") != "enemy" or pid in ops: continue
            mynb = [q for q in pr.get("nbrs", []) if provs.get(q, {}).get("owner") == "me"]
            if not mynb: continue
            e = api.enemy.get(pid)
            if e is None and not pr.get("visible"): continue
            dstr = e["str"] if e else 0
            avail = []
            for q in mynb:
                ul = [u for u in byprov.get(q, []) if u["id"] not in inop and u["type"] not in ("rec", "mil")
                      and u["str"] >= 65 and u["rdy"] >= 45 and not u.get("expand")]
                total_here = len(byprov.get(q, []))
                keep = 1 if total_here <= len(ul) else 0
                ul.sort(key=lambda u: -u["str"])
                if keep and ul: ul = ul[:-1]
                avail += ul
            if not avail: continue
            if dstr <= 0:
                cands.append((2.0, pid, avail[:2]))
                continue
            att = sum(u["str"] for u in avail)
            rdy = sum(u["rdy"] for u in avail) / len(avail) / 100.0
            heavy = sum(1 for u in avail if u["type"] in ("art", "eng", "arm")) / len(avail)
            dirs = len(set(u["prov"] for u in avail))
            p = _p(api, att, dstr, pr, 0.35, rdy, heavy, dirs)
            sc = p + 0.05 * (pr.get("y", 0) or 0)
            if pid in api.enemy_capitals.values(): sc += 0.3
            if p >= 0.55:
                cands.append((sc, pid, avail))
        cands.sort(key=lambda c: -c[0])
        for sc, pid, av in cands:
            if len(ops) >= 3: break
            av = [u for u in av if u["id"] not in inop]
            if not av: continue
            ids = [u["id"] for u in av]
            if sc >= 2.0:
                api.cmd("move %s P%d" % (_ids(ids), pid))
                ops[pid] = {"u": ids, "s": t, "go": t}
            else:
                api.cmd("prepare %s P%d" % (_ids(ids), pid))
                ops[pid] = {"u": ids, "s": t}
            for i in ids: inop.add(i)

    # ---------- idle units ----------
    nb = api.neutral_border
    expanders = sum(1 for u in units if u.get("expand"))
    lim = max(3, int(n * 0.6))
    for u in units:
        if u["id"] in inop or u["path"] or u.get("front") or u.get("expand"): continue
        if u["type"] == "rec":
            last = mem.setdefault("rx", {}).get(str(u["id"]), -999)
            if api.unexplored and t - last >= 24:
                api.cmd("explore %d" % u["id"])
                mem["rx"][str(u["id"])] = t
            continue
        if nb and expanders < lim and u["type"] in ("inf", "mtn", "mot", "mil"):
            api.cmd("expand %d" % u["id"])
            expanders += 1
        else:
            api.cmd("front %d" % u["id"])
