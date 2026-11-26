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

RESEARCH = ["farming", "staffwork", "conscription", "logistics", "inf.protection", "inf.weapons",
            "medicine", "drill", "mining", "art.weapons", "grn.weapons", "industry",
            "discipline", "fieldworks", "atg.weapons", "art.protection", "grn.protection",
            "drilling", "refining", "inf.mobility", "atg.protection", "art.mobility",
            "rec.mobility", "grn.mobility"]

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    for line in RESEARCH:
        if len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        cost = tl.get("cost") or {}
        ok = True
        for k in cost:
            v = cost[k]
            if k == "res": v = v + 40
            if api.stock.get(k, 0) < v:
                ok = False
                break
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
    if res > 1500: n = 8
    if res > 3000: n = 12
    for _ in range(n):
        nrec = counts.get("rec", 0)
        ncomb = 0
        for k in counts:
            if k != "rec": ncomb += counts[k]
        if nrec < 2 or (nrec < 8 and api.t > 300 and ncomb > 20 and nrec * 15 < ncomb):
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

def _refit(api, inop):
    if not api.old_units: return
    if api.stock.get("res", 0) < 500: return
    done = 0
    for u in api.units:
        if done >= 8: break
        if not u.get("old") or u["id"] in inop: continue
        if u.get("fighting") or not u.get("supplied") or u["path"]: continue
        if u["state"] in ("routing", "assault", "preparing", "refitting", "shaken"): continue
        if api.provs.get(u["prov"], {}).get("owner") != "me": continue
        if u["prov"] in api.border: continue
        c = api.refit_cost.get(u["type"]) or {}
        ok = api.stock.get("res", 0) >= c.get("res", 0) + 400
        for k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) < c.get(k, 0) + 20: ok = False
        if not ok: break
        r = api.cmd("refit %d" % u["id"])
        if r.startswith("ok"): done += 1

def _diplo(api):
    mem = api.mem
    met = list(api.met or [])
    pacts = api.pacts or {}
    unpacted = [f for f in met if f not in pacts]
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            if len(unpacted) >= 2 and o.get("frm") in unpacted:
                r = api.cmd("accept %s" % o["id"])
                if r.startswith("ok"):
                    unpacted.remove(o["frm"])
                    continue
            api.cmd("reject %s" % o["id"])
        else:
            api.cmd("reject %s" % o["id"])
    last = mem.get("dip_t", -1000)
    if api.t - last < 240 or len(met) < 2: return
    mem["dip_t"] = api.t
    npact = len(met) - len(unpacted)
    pending = set(o.get("to") for o in (api.offers_out or []))
    for f in unpacted:
        if npact >= len(met) // 2: break
        if len(unpacted) - 1 < 1: break
        if f in pending: continue
        api.cmd("offer %s pact" % f)
        api.cmd("say %s Austral proposes peace. We will not attack you while a pact holds." % f)
        npact += 1

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
        try:
            if ty.get("arm") or ty.get("hvt") or ty.get("mec"): armor_seen = True
        except Exception:
            pass
    mem["armor"] = armor_seen

    _research(api)
    _recruit(api, counts, armor_seen)
    if api.t % 24 < 6:
        try:
            _diplo(api)
        except Exception:
            pass

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
            go = rdy >= 40 or waited >= 24
        elif rdy >= 55 and (bon >= 35 or (bon >= 25 and waited >= 36)):
            if p > 0.5 or att > 2.5 * dstr + 40:
                go = True
        elif waited >= 72 and bon >= 20 and att > 3.0 * dstr + 60 and rdy >= 50:
            go = True
        if go:
            api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgt))
            op["launched"] = True
            op["lt"] = api.t
        elif waited > 130:
            api.cmd("front " + ",".join(str(i) for i in ids))
            del ops[tk]
            for i in ids: inop.discard(i)

    comb = [u for u in units if u["type"] != "rec"]
    maxops = min(10, max(1, len(comb) // 12))
    if len(ops) < maxops and api.enemy:
        cands = []
        caps = set(api.enemy_capitals.values())
        for tgt in api.enemy:
            e = api.enemy[tgt]
            pr = provs.get(tgt)
            if not pr or str(tgt) in ops: continue
            if pr.get("owner") == "neutral": continue
            if not any(provs.get(n, {}).get("owner") == "me" for n in pr.get("nbrs", [])): continue
            dstr = e["str"] * (1.0 if e.get("exact") else 1.3)
            score = dstr * TDF.get(pr.get("terrain"), 1.0) * (1 + 0.3 * (pr.get("fort", 0) or 0))
            score -= (pr.get("y", 0) or 0) * 5
            if pr.get("city"): score -= 30
            if tgt in caps: score -= 400
            cands.append((score, tgt, dstr))
        cands.sort()
        for score, tgt, dstr in cands[:6]:
            if len(ops) >= maxops: break
            nb = set(n for n in provs[tgt].get("nbrs", []) if provs.get(n, {}).get("owner") == "me")
            pool = {}
            for u in comb:
                if u["prov"] in nb and u["id"] not in inop and u["str"] >= 65 and u["rdy"] >= 45 \
                   and u["state"] not in ("routing", "shaken", "refitting") and u["mor"] >= 40:
                    pool.setdefault(u["prov"], []).append(u)
            pick = []
            for pv in pool:
                lst = pool[pv]
                lst.sort(key=lambda u: -u["str"])
                keep = 1 if len(lst) > 1 else 0
                if pv == api.capital: keep = max(keep, 2)
                pick += lst[:len(lst) - keep] if keep else lst
            att = sum(u["str"] for u in pick)
            if len(pick) < 2 or att < 1.6 * dstr + 40: continue
            ids = [u["id"] for u in pick]
            r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in ids), tgt))
            if r.startswith("ok"):
                ops[str(tgt)] = {"u": ids, "t0": api.t}
                for i in ids: inop.add(i)
                recs_needed.append(tgt)

    if api.t % 12 < 6:
        try:
            _refit(api, inop)
        except Exception:
            pass

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
            if u["state"] == "routing": continue
            if needs and not (u.get("explore") and nexplore <= 1 and api.unexplored):
                tgt = needs.pop(0)
                nb = [n for n in provs.get(tgt, {}).get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
                if nb:
                    if u.get("explore"): nexplore -= 1
                    api.cmd("move %d P%d" % (u["id"], nb[0]))
                    recpost[str(u["id"])] = tgt
                    continue
            if u["path"] or u.get("explore") or u.get("front"): continue
            if api.unexplored:
                api.cmd("explore %d" % u["id"])
                nexplore += 1
            continue
        if u["id"] in inop: continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["state"] in ("routing", "assault", "preparing", "refitting"): continue
        if api.neutral_border and nexp < cap_exp:
            r = api.cmd("expand %d" % u["id"])
            if r.startswith("ok"):
                nexp += 1
                continue
        api.cmd("front %d" % u["id"])
    mem["calls"] = mem.get("calls", 0) + 1
