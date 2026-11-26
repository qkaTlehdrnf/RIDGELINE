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

def _dstr(api, pid):
    e = api.enemy.get(pid)
    if not e: return 0.0
    s = e.get("str", 0) or 0
    if not e.get("exact"): s *= 1.3
    return s

def tick(api):
    mem = api.mem
    t = api.t
    ops = mem.setdefault("ops", {})
    units = api.units
    byid = {u["id"]: u for u in units}
    provs = api.provs
    nb = api.neutral_border
    n = len(units)

    # ---------- recruitment ----------
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    made = 0
    cap = 3
    if api.res > 600: cap = 6
    if api.res > 2000: cap = 10
    while made < cap:
        if cnt.get("rec", 0) < (2 if n < 40 else (3 if n < 200 else 5)):
            ty = "rec"
        elif cnt.get("eng", 0) < 1 + n // 20 and n >= 8:
            ty = "eng"
        elif cnt.get("art", 0) * 4 < n and n >= 6 and not (nb and t < 400):
            ty = "art"
        elif nb and t < 600 and cnt.get("mot", 0) * 5 < n:
            ty = "mot"
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
        done = (not alive) or pr.get("owner") == "me" or (t - op["s"] > 130)
        if op.get("go") and t - op["go"] > 72: done = True
        if done:
            if alive: api.cmd("front " + _ids(alive))
            del ops[tg]
            continue
        if not op.get("go"):
            # add arrived reinforcements adjacent to target
            us = [byid[i] for i in alive]
            nbrs = set(pr.get("nbrs", []))
            ready = [u for u in us if u["prov"] in nbrs and not u["path"]]
            pend = [i for i in alive if byid[i]["plan"] != tg and byid[i]["prov"] in nbrs and not byid[i]["path"]]
            if pend:
                api.cmd("prepare %s P%d" % (_ids(pend), tg))
            if not ready: continue
            bon = sum(u.get("bonus", 0) or 0 for u in ready) / len(ready)
            dstr = _dstr(api, tg)
            att = sum(u["str"] for u in ready)
            rdy = sum(u["rdy"] for u in ready) / len(ready) / 100.0
            heavy = sum(1 for u in ready if u["type"] in ("art", "eng", "arm")) / len(ready)
            dirs = len(set(u["prov"] for u in ready))
            p = _p(api, att, dstr, pr, bon / 100.0, rdy, heavy, dirs)
            if dstr <= 0 and pr.get("visible"):
                p = 1.0
            if (bon >= 25 and rdy >= 0.55 and p >= 0.55) or (t - op["s"] >= 60 and p >= 0.7) or p >= 0.97:
                api.cmd("move %s P%d" % (_ids([u["id"] for u in ready]), tg))
                op["go"] = t
            elif t - op["s"] >= 72 and p < 0.4:
                api.cmd("front " + _ids(alive))
                del ops[tg]

    inop = set()
    for k in ops:
        for i in ops[k]["u"]:
            inop.add(i)

    maxops = 2 + n // 50
    if maxops > 12: maxops = 12

    # ---------- plan new operations ----------
    if len(ops) < maxops and t % 12 < 6:
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
            dstr = _dstr(api, pid)
            avail = []
            for q in mynb:
                here = byprov.get(q, [])
                ul = [u for u in here if u["id"] not in inop and u["type"] not in ("rec", "mil")
                      and u["str"] >= 70 and u["rdy"] >= 50 and not u.get("expand") and not u["path"]]
                ul.sort(key=lambda u: -u["str"])
                if len(here) <= len(ul) and ul: ul = ul[:-1]
                avail += ul
            if not avail: continue
            if dstr <= 0:
                cands.append((2.0, pid, avail[:2]))
                continue
            att = sum(u["str"] for u in avail)
            rdy = sum(u["rdy"] for u in avail) / len(avail) / 100.0
            heavy = sum(1 for u in avail if u["type"] in ("art", "eng", "arm")) / len(avail)
            dirs = len(set(u["prov"] for u in avail))
            p = _p(api, att, dstr, pr, 0.40, rdy, heavy, dirs)
            sc = p + 0.05 * (pr.get("y", 0) or 0)
            if pid in api.enemy_capitals.values(): sc += 0.4
            if p >= 0.5:
                cands.append((sc, pid, avail))
        cands.sort(key=lambda c: -c[0])
        for sc, pid, av in cands:
            if len(ops) >= maxops: break
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

    # ---------- reinforce prepared ops from the rear ----------
    if t % 24 < 6:
        pending = [tg for tg in ops if not ops[tg].get("go")]
        if pending:
            border = api.border
            spare = [u for u in units if u["id"] not in inop and not u["path"] and u["type"] in ("inf", "art", "mtn", "mot", "arm", "eng")
                     and u["str"] >= 85 and u["rdy"] >= 70 and not u.get("expand") and u["prov"] not in border]
            k = 0
            for u in spare[:24]:
                tg = pending[k % len(pending)]
                k += 1
                stage = [q for q in provs.get(tg, {}).get("nbrs", []) if provs.get(q, {}).get("owner") == "me"]
                if not stage: continue
                st = stage[u["id"] % len(stage)]
                r = api.cmd("move %d P%d" % (u["id"], st))
                if r.startswith("ok"):
                    ops[tg]["u"].append(u["id"])
                    inop.add(u["id"])

    # ---------- idle units ----------
    expanders = sum(1 for u in units if u.get("expand"))
    lim = max(4, int(n * (0.85 if t < 500 else 0.6)))
    rx = mem.setdefault("rx", {})
    for u in units:
        if u["id"] in inop or u["path"] or u.get("front") or u.get("expand"): continue
        if u["type"] == "rec":
            last = rx.get(str(u["id"]), -999)
            if api.unexplored and t - last >= 24:
                api.cmd("explore %d" % u["id"])
                rx[str(u["id"])] = t
            continue
        if nb and expanders < lim and u["type"] in ("inf", "mtn", "mot", "mil"):
            api.cmd("expand %d" % u["id"])
            expanders += 1
        else:
            api.cmd("front %d" % u["id"])
