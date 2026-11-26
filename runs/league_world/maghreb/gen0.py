def _tdf(pr):
    t = str(pr.get("terrain", "p"))
    c = t[:1]
    if c == "m": return 2.0
    if c == "h": return 1.5
    if c == "f": return 1.25
    return 1.0

def _pwin(api, att, dfs, pr, bonus, rdy, heavy, dirs):
    m = api.model or {}
    w = m.get("w"); mu = m.get("mean"); sd = m.get("std")
    lr = math.log((att + 1.0) / (dfs + 1.0))
    x = [lr, _tdf(pr), pr.get("fort", 0) or 0, 1.0 if pr.get("city") else 0.0,
         bonus, rdy, heavy, dirs]
    if not w or not mu or not sd or len(w) != 8:
        return 1.0 / (1.0 + math.exp(-(lr * 1.5 - 0.8 - 0.3 * (x[2]) - (x[1] - 1))))
    z = m.get("b", 0.0)
    for i in range(8):
        s = sd[i] if sd[i] else 1.0
        z += w[i] * (x[i] - mu[i]) / s
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))

def _afford(api, cost, keep):
    if not cost: return False
    st = api.stock
    for k, v in cost.items():
        have = st.get(k, 0) if k != "res" else api.res
        if k == "res":
            if have - v < keep: return False
        elif k in ("steel", "oil", "rare"):
            if have < v: return False
    return True

RESEARCH = ["farming", "conscription", "industry", "logistics", "inf.weapons",
            "art.weapons", "medicine", "inf.protection", "mining", "discipline",
            "drill", "grn.weapons", "staffwork", "fieldworks", "atg.weapons",
            "art.protection", "drilling", "refining", "grn.protection", "inf.mobility"]

MIX = [("inf", 0.42), ("art", 0.16), ("grn", 0.14), ("atg", 0.08), ("cav", 0.10), ("mtn", 0.05), ("eng", 0.05)]

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    keep = 40 if api.t > 200 else 20
    for line in RESEARCH:
        if len(api.research) + len(busy) - len(api.research) >= 2 and len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        if _afford(api, tl.get("cost"), keep):
            r = api.cmd("research " + line)
            if str(r).startswith("ok"):
                busy.add(line)
                if len(busy) >= 2: return

def _recruit(api, units):
    net = api.income_by.get("res", api.income) if api.income_by else api.income
    counts = {}
    for u in units: counts[u["type"]] = counts.get(u["type"], 0) + 1
    nrec = counts.get("rec", 0)
    reserve = 30 if api.t > 300 else 10
    if nrec < 3 and api.res > 10:
        api.cmd("recruit rec")
        return
    if net is not None and net < 0 and api.t > 100: return
    total = max(1, len(units) - nrec)
    tries = 0
    while api.res > reserve and tries < 4:
        tries += 1
        best = None; bd = -9
        for typ, share in MIX:
            if typ == "cav" and api.t > 1500: continue
            c = api.unit_costs.get(typ)
            if not c: continue
            ok = api.res - c.get("res", 0) >= reserve and api.mp >= c.get("mp", 0)
            for k in ("steel", "oil", "rare"):
                if api.stock.get(k, 0) < c.get(k, 0): ok = False
            if not ok: continue
            d = share - counts.get(typ, 0) / float(total)
            if d > bd: bd = d; best = typ
        if not best:
            c = api.unit_costs.get("inf", {})
            if api.res - c.get("res", 8) >= reserve and api.mp >= c.get("mp", 9):
                best = "inf"
            else:
                return
        r = api.cmd("recruit " + best)
        if not str(r).startswith("ok"): return
        counts[best] = counts.get(best, 0) + 1
        total += 1

def tick(api):
    mem = api.mem
    ops = mem.setdefault("ops", {})
    units = api.units
    byid = {}
    for u in units: byid[u["id"]] = u
    provs = api.provs
    inop = set()
    for k, o in ops.items():
        for i in o["ids"]: inop.add(i)

    _research(api)
    _recruit(api, units)

    # ---- manage running ops
    for tgt in list(ops.keys()):
        o = ops[tgt]
        ids = [i for i in o["ids"] if i in byid]
        o["ids"] = ids
        pr = provs.get(tgt, {})
        done = (not ids) or pr.get("owner") == "me"
        age = api.t - o["start"]
        if not done:
            if o["launched"]:
                live = [i for i in ids if byid[i]["str"] >= 25]
                if age > o.get("lt", o["start"]) - o["start"] + 72 or not live:
                    done = True
            else:
                if age >= 36:
                    e = api.enemy.get(tgt)
                    dstr = e["str"] if e else 0
                    att = sum(byid[i]["str"] for i in ids)
                    rdy = sum(byid[i]["rdy"] for i in ids) / (100.0 * len(ids))
                    bon = max([byid[i].get("bonus", 0) or 0 for i in ids] + [0]) / 100.0
                    heavy = len([i for i in ids if byid[i]["type"] in ("art", "eng", "arm")]) / float(len(ids))
                    dirs = len(set(byid[i]["prov"] for i in ids))
                    p = _pwin(api, att, dstr, pr, bon, rdy, heavy, dirs)
                    if p >= 0.4 or (tgt == api.enemy_capital and p >= 0.3):
                        api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgt))
                        o["launched"] = True; o["lt"] = api.t
                    elif age > 72:
                        done = True
        if done:
            if ids: api.cmd("front " + ",".join(str(i) for i in ids))
            del ops[tgt]
            for i in ids: inop.discard(i)
    # ops store with int keys may become str in json; normalise not needed for dict in memory

    # ---- assign idle units
    exp_ids = []; front_ids = []; scout_ids = []
    neutral = bool(api.neutral_border)
    for u in units:
        if u["id"] in inop: continue
        if u["front"] or u["expand"] or u["explore"] or u["path"]: continue
        if u["state"] in ("moving", "assault", "preparing", "routing"): continue
        if u["type"] == "rec":
            scout_ids.append(u["id"])
        elif neutral and u["type"] not in ("art", "atg", "mil"):
            exp_ids.append(u["id"])
        else:
            front_ids.append(u["id"])
    if scout_ids:
        if api.unexplored: api.cmd("explore " + ",".join(map(str, scout_ids)))
        else: api.cmd("front " + ",".join(map(str, scout_ids)))
    if exp_ids: api.cmd("expand " + ",".join(map(str, exp_ids)))
    if front_ids: api.cmd("front " + ",".join(map(str, front_ids)))

    # ---- choose new offensives
    if api.t % 12 >= 6 and api.t > 48: return
    # units available per my province
    avail = {}
    cnt = {}
    for u in units:
        cnt[u["prov"]] = cnt.get(u["prov"], 0) + 1
        if u["id"] in inop or u["type"] in ("rec", "mil"): continue
        if u["str"] < 65 or u["rdy"] < 45 or u.get("mor", 70) < 40: continue
        if u["state"] in ("routing", "shaken", "moving", "assault"): continue
        if provs.get(u["prov"], {}).get("owner") != "me": continue
        avail.setdefault(u["prov"], []).append(u)
    cands = set()
    for pid in api.border:
        pr = provs.get(pid)
        if not pr: continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if q and q.get("owner") == "enemy": cands.add(n)
    empty_sent = 0
    best = None
    for tgt in cands:
        if tgt in ops: continue
        pr = provs[tgt]
        e = api.enemy.get(tgt)
        srcs = [n for n in pr.get("nbrs", []) if n in avail]
        if not srcs: continue
        if not e or e.get("n", 0) == 0:
            if pr.get("visible") and empty_sent < 3:
                src = srcs[0]
                us = avail[src]
                if cnt.get(src, 0) > 1:
                    u = us.pop(0)
                    api.cmd("move %d P%d" % (u["id"], tgt))
                    ops[tgt] = {"ids": [u["id"]], "start": api.t, "launched": True, "lt": api.t}
                    inop.add(u["id"]); cnt[src] -= 1; empty_sent += 1
            continue
        pick = []
        for s in srcs:
            us = sorted(avail[s], key=lambda x: -x["str"])
            leave = 1
            pick.extend(us[:max(0, min(len(us), cnt.get(s, 0) - leave))])
        if len(pick) < 2: continue
        pick = pick[:14]
        att = sum(u["str"] for u in pick)
        rdy = sum(u["rdy"] for u in pick) / (100.0 * len(pick))
        heavy = len([u for u in pick if u["type"] in ("art", "eng", "arm")]) / float(len(pick))
        dirs = len(set(u["prov"] for u in pick))
        p = _pwin(api, att, e.get("str", 100), pr, 0.4, rdy, heavy, dirs)
        score = p + (0.3 if tgt == api.enemy_capital or tgt in api.enemy_capitals.values() else 0) + 0.02 * (pr.get("y", 0) or 0)
        if p >= 0.35 and (best is None or score > best[0]):
            best = (score, tgt, pick)
    if best and len(ops) < 3:
        _, tgt, pick = best
        ids = [u["id"] for u in pick]
        r = api.cmd("prepare %s P%d" % (",".join(map(str, ids)), tgt))
        if str(r).startswith("ok"):
            ops[tgt] = {"ids": ids, "start": api.t, "launched": False}
