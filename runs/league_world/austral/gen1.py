def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

def _p(api, att, dfn, terr, fort, city, bonus, rdy, heavy, dirs):
    m = api.model or {}
    if not m.get("w"):
        return _sig(1.2 * math.log((att + 1.0) / (dfn + 1.0)) - 0.5 * fort + 2 * bonus)
    x = [math.log((att + 1.0) / (dfn + 1.0)), terr, fort, city, bonus, rdy, heavy, dirs]
    z = m["b"]
    for i in range(len(x)):
        s = m["std"][i] or 1.0
        z += m["w"][i] * (x[i] - m["mean"][i]) / s
    return _sig(z)

TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}

def _afford(api, typ, n=1):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) < c.get("res", 0) * n + 15: return False
    if api.mp < c.get("mp", 0) * n + 5: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0) * n: return False
    return True

RESEARCH = ["farming", "staffwork", "conscription", "logistics", "inf.weapons", "medicine",
            "inf.protection", "drill", "art.weapons", "mining", "grn.weapons", "industry",
            "discipline", "fieldworks", "atg.weapons", "art.protection", "grn.protection",
            "drilling", "refining", "inf.mobility", "atg.protection", "art.mobility"]

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    for line in RESEARCH:
        if len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        cost = tl.get("cost") or {}
        ok = True
        for k, v in cost.items():
            if k == "res": v = v + 40
            if api.stock.get(k, 0) < v: ok = False; break
        if not ok: continue
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            busy.add(line)

def _recruit(api, counts, armor_seen):
    if len(api.units) > 0 and api.income < 1.5 and api.t > 48: return
    pend = api.mem.get("rq", 0)
    res = api.stock.get("res", 0)
    n = 3
    if res > 600: n = 5
    if res > 2000: n = 8
    for _ in range(n):
        nrec = counts.get("rec", 0)
        ncomb = sum(v for k, v in counts.items() if k != "rec")
        if nrec < 2 or (nrec < 6 and api.t > 300 and ncomb > 20 and nrec * 15 < ncomb):
            typ = "rec"
        else:
            k = pend % 10
            if armor_seen and k in (3, 8): typ = "atg"
            elif k in (2, 6, 9): typ = "art"
            elif k in (4, 7): typ = "grn"
            else: typ = "inf"
            if not _afford(api, typ): typ = "inf"
        if not _afford(api, typ): return
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): return
        counts[typ] = counts.get(typ, 0) + 1
        if typ != "rec": pend += 1
        api.mem["rq"] = pend

def tick(api):
    mem = api.mem
    ops = mem.setdefault("ops", {})
    provs = api.provs
    units = api.units
    byid = {}
    counts = {}
    for u in units:
        byid[u["id"]] = u
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    armor_seen = mem.get("armor", False)
    for e in api.enemy.values():
        ty = e.get("types") or {}
        if isinstance(ty, dict):
            if ty.get("arm") or ty.get("hvt") or ty.get("mec"): armor_seen = True
    mem["armor"] = armor_seen

    _research(api)
    _recruit(api, counts, armor_seen)

    inop = set()
    recs_needed = []
    for tk in list(ops.keys()):
        op = ops[tk]
        tgt = int(tk)
        ids = [i for i in op["u"] if i in byid]
        op["u"] = ids
        pr = provs.get(tgt, {})
        lt = op.get("lt")
        done = (pr.get("owner") == "me" and tgt not in api.enemy) or not ids \
            or (lt is not None and api.t - lt > 72)
        if done:
            if ids:
                api.cmd("front " + ",".join(str(i) for i in ids))
            del ops[tk]
            continue
        for i in ids: inop.add(i)
        if op.get("launched"): continue
        recs_needed.append(tgt)
        e = api.enemy.get(tgt)
        dstr = e["str"] * (1.0 if e.get("exact") else 1.3) if e else 0.0
        att = sum(byid[i]["str"] for i in ids)
        bon = max([byid[i].get("bonus", 0) for i in ids] + [0])
        rdy = sum(byid[i]["rdy"] for i in ids) / float(len(ids))
        heavy = sum(1 for i in ids if byid[i]["type"] in ("art", "eng", "arm")) / float(len(ids))
        dirs = len(set(byid[i]["prov"] for i in ids))
        p = _p(api, att, dstr, TDF.get(pr.get("terrain"), 1.0), pr.get("fort", 0) or 0,
               1 if pr.get("city") else 0, bon / 100.0, rdy / 100.0, heavy, dirs)
        waited = api.t - op["t0"]
        go = False
        if not e:
            go = True
        elif rdy >= 45 and (bon >= 22 or (bon >= 15 and waited >= 36)):
            if p > 0.45 or att > 2.0 * dstr + 40:
                go = True
        elif waited >= 60 and bon >= 10 and att > 3.0 * dstr + 60 and rdy >= 35:
            go = True
        if go:
            api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgt))
            op["launched"] = True
            op["lt"] = api.t
        elif waited > 110:
            api.cmd("front " + ",".join(str(i) for i in ids))
            del ops[tk]
            for i in ids: inop.discard(i)

    comb = [u for u in units if u["type"] != "rec"]
    maxops = min(8, max(1, len(comb) // 10))
    if len(ops) < maxops and api.enemy:
        cands = []
        caps = set(api.enemy_capitals.values())
        for tgt, e in api.enemy.items():
            pr = provs.get(tgt)
            if not pr or str(tgt) in ops: continue
            if not any(provs.get(n, {}).get("owner") == "me" for n in pr.get("nbrs", [])): continue
            dstr = e["str"] * (1.0 if e.get("exact") else 1.3)
            score = dstr * TDF.get(pr.get("terrain"), 1.0) * (1 + 0.3 * (pr.get("fort", 0) or 0))
            score -= (pr.get("y", 0) or 0) * 5
            if pr.get("city"): score -= 30
            if tgt in caps: score -= 400
            cands.append((score, tgt, dstr))
        cands.sort()
        for score, tgt, dstr in cands[:5]:
            if len(ops) >= maxops: break
            nb = set(n for n in provs[tgt].get("nbrs", []) if provs.get(n, {}).get("owner") == "me")
            pool = {}
            for u in comb:
                if u["prov"] in nb and u["id"] not in inop and u["str"] >= 60 and u["rdy"] >= 35 \
                   and u["state"] not in ("routing", "shaken", "refitting") and u["mor"] >= 35:
                    pool.setdefault(u["prov"], []).append(u)
            pick = []
            for pv, lst in pool.items():
                lst.sort(key=lambda u: -u["str"])
                keep = 1 if len(lst) > 1 else 0
                if pv == api.capital: keep = max(keep, 2)
                pick += lst[:len(lst) - keep] if keep else lst
            att = sum(u["str"] for u in pick)
            if len(pick) < 2 or att < 1.3 * dstr + 30: continue
            ids = [u["id"] for u in pick]
            r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in ids), tgt))
            if r.startswith("ok"):
                ops[str(tgt)] = {"u": ids, "t0": api.t}
                for i in ids: inop.add(i)
                recs_needed.append(tgt)

    # scouts: support operations first
    recpost = mem.setdefault("recpost", {})
    for k in list(recpost.keys()):
        if int(k) not in byid or str(recpost[k]) not in ops:
            del recpost[k]
    covered = set(recpost.values())
    needs = [t for t in recs_needed if str(t) in ops and t not in covered]
    enemy_contact = bool(api.enemy) or bool(api.enemy_capitals)
    nexp = sum(1 for u in comb if u.get("expand"))
    cap_exp = len(comb) if not enemy_contact else int(len(comb) * 0.55)
    nexplore = sum(1 for u in units if u["type"] == "rec" and u.get("explore"))
    for u in units:
        if u["type"] == "rec":
            if str(u["id"]) in recpost: continue
            if needs and (nexplore > 1 or not api.unexplored or u["path"] == [] or not u.get("explore")):
                if u.get("explore") and nexplore <= 1 and api.unexplored: pass
                else:
                    tgt = needs.pop(0)
                    nb = [n for n in provs.get(tgt, {}).get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
                    if nb:
                        if u.get("explore"): nexplore -= 1
                        api.cmd("move %d P%d" % (u["id"], nb[0]))
                        recpost[str(u["id"])] = tgt
                        continue
            if u["path"] or u.get("explore") or u.get("front"): continue
            if u["state"] in ("routing",): continue
            if api.unexplored:
                api.cmd("explore %d" % u["id"])
                nexplore += 1
            continue
        if u["id"] in inop: continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["state"] in ("routing", "assault", "preparing"): continue
        if api.neutral_border and nexp < cap_exp:
            r = api.cmd("expand %d" % u["id"])
            if r.startswith("ok"):
                nexp += 1
                continue
        api.cmd("front %d" % u["id"])
    mem["calls"] = mem.get("calls", 0) + 1
