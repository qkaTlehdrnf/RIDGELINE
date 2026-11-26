def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

def _p(api, att, dfn, terr, fort, city, bonus, rdy, heavy, dirs):
    m = api.model or {}
    if not m.get("w"):
        return _sig(1.2 * math.log((att + 1.0) / (dfn + 1.0)) - 0.5 * fort + bonus)
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

RESEARCH = ["farming", "industry", "conscription", "logistics", "inf.weapons", "medicine",
            "inf.protection", "art.weapons", "mining", "discipline", "drill", "staffwork",
            "grn.weapons", "fieldworks", "atg.weapons", "art.protection", "grn.protection",
            "drilling", "refining", "inf.mobility"]

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    for line in RESEARCH:
        if len(api.research) + len(busy) - len(api.research) >= 2 and len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        cost = tl.get("cost") or {}
        ok = True
        for k, v in cost.items():
            have = api.stock.get(k, 0)
            if k == "res": v = v + 40
            if have < v: ok = False; break
        if not ok: continue
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            busy.add(line)
            if len(busy) >= 2: return

def _recruit(api, counts, armor_seen):
    if len(api.units) > 0 and api.income < 1.5 and api.t > 48: return
    pend = api.mem.get("rq", 0)
    for _ in range(3):
        nrec = counts.get("rec", 0)
        ncomb = sum(v for k, v in counts.items() if k != "rec")
        if nrec < 2 or (nrec < 4 and api.t > 400 and ncomb > 20):
            typ = "rec"
        else:
            k = pend % 8
            if armor_seen and k in (3, 7): typ = "atg"
            elif k in (2, 6): typ = "art"
            elif k == 5: typ = "grn"
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

    # ---- manage operations
    inop = set()
    recs_needed = []
    for tk in list(ops.keys()):
        op = ops[tk]
        tgt = int(tk)
        ids = [i for i in op["u"] if i in byid]
        op["u"] = ids
        pr = provs.get(tgt, {})
        done = (pr.get("owner") == "me" and tgt not in api.enemy) or not ids \
            or api.t - op["t0"] > (op.get("lt", 10**9) - op["t0"]) + 72 or api.t - op["t0"] > 160
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
        bon = max([byid[i].get("bonus", 0) for i in ids] + [0]) / 100.0
        rdy = sum(byid[i]["rdy"] for i in ids) / (100.0 * len(ids))
        heavy = sum(1 for i in ids if byid[i]["type"] in ("art", "eng", "arm")) / float(len(ids))
        dirs = len(set(byid[i]["prov"] for i in ids))
        p = _p(api, att, dstr, TDF.get(pr.get("terrain"), 1.0), pr.get("fort", 0) or 0,
               1 if pr.get("city") else 0, bon, rdy, heavy, dirs)
        iscap = tgt in api.enemy_capitals.values()
        waited = api.t - op["t0"]
        if (p > 0.55 and waited >= 12) or (iscap and p > 0.45 and waited >= 24) or \
           (waited >= 48 and att > 2.0 * dstr + 50) or not e:
            api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgt))
            op["launched"] = True
            op["lt"] = api.t
        elif waited > 72:
            api.cmd("front " + ",".join(str(i) for i in ids))
            del ops[tk]
            for i in ids: inop.discard(i)

    # ---- plan new operations
    comb = [u for u in units if u["type"] != "rec"]
    maxops = min(4, max(1, len(comb) // 12))
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
            if tgt in caps: score -= 400
            cands.append((score, tgt, dstr))
        cands.sort()
        for score, tgt, dstr in cands[:3]:
            if len(ops) >= maxops: break
            nb = set(n for n in provs[tgt].get("nbrs", []) if provs.get(n, {}).get("owner") == "me")
            pool = {}
            for u in comb:
                if u["prov"] in nb and u["id"] not in inop and u["str"] >= 60 and u["rdy"] >= 40 \
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
            sel = ",".join(str(i) for i in ids)
            r = api.cmd("prepare %s P%d" % (sel, tgt))
            if r.startswith("ok"):
                ops[str(tgt)] = {"u": ids, "t0": api.t}
                for i in ids: inop.add(i)
                recs_needed.append(tgt)

    # ---- idle units
    enemy_contact = bool(api.enemy) or bool(api.enemy_capitals)
    nexp = sum(1 for u in comb if u.get("expand"))
    cap_exp = len(comb) if not enemy_contact else int(len(comb) * 0.55)
    recs_used = set(mem.get("recpost", {}).values())
    recpost = mem.setdefault("recpost", {})
    for u in units:
        if u["id"] in inop: continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["state"] in ("routing", "assault", "preparing"): continue
        if u["type"] == "rec":
            if api.unexplored and (counts.get("rec", 0) <= 2 or u["id"] % 2 == 0):
                api.cmd("explore %d" % u["id"])
                continue
            if recs_needed:
                tgt = recs_needed.pop(0)
                nb = [n for n in provs.get(tgt, {}).get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
                if nb:
                    api.cmd("move %d P%d" % (u["id"], nb[0]))
                    continue
            if api.unexplored:
                api.cmd("explore %d" % u["id"])
            continue
        if api.neutral_border and nexp < cap_exp:
            r = api.cmd("expand %d" % u["id"])
            if r.startswith("ok"):
                nexp += 1
                continue
        api.cmd("front %d" % u["id"])
    mem["calls"] = mem.get("calls", 0) + 1
