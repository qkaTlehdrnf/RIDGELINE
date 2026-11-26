def _tdf(pr):
    c = str(pr.get("terrain", "p"))[:1]
    return {"m": 2.0, "h": 1.5, "f": 1.25}.get(c, 1.0)

def _pwin(api, att, dfs, pr, bonus, rdy, heavy, dirs):
    m = api.model or {}
    w = m.get("w"); mu = m.get("mean"); sd = m.get("std")
    lr = math.log((att + 1.0) / (dfs + 1.0))
    x = [lr, _tdf(pr), pr.get("fort", 0) or 0, 1.0 if pr.get("city") else 0.0, bonus, rdy, heavy, dirs]
    if not w or not mu or not sd or len(w) != 8:
        return 1.0 / (1.0 + math.exp(-(lr * 1.5 - 0.8 - 0.3 * x[2] - (x[1] - 1))))
    z = m.get("b", 0.0)
    for i in range(8):
        s = sd[i] if sd[i] else 1.0
        z += w[i] * (x[i] - mu[i]) / s
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))

def _afford(api, cost, keep):
    if not cost: return False
    for k, v in cost.items():
        if k == "res":
            if api.res - v < keep: return False
        elif k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) < v: return False
    return True

RESEARCH = ["farming", "conscription", "industry", "logistics", "medicine",
            "inf.protection", "inf.weapons", "art.weapons", "discipline", "mining",
            "drill", "art.protection", "atg.protection", "grn.weapons", "fieldworks",
            "refining", "cav.weapons", "arm.weapons", "staffwork", "drilling",
            "mtn.weapons", "grn.protection", "inf.mobility"]

MIX_EARLY = [("cav", 0.35), ("inf", 0.45), ("mtn", 0.08), ("art", 0.07), ("atg", 0.05)]
MIX = [("inf", 0.38), ("art", 0.18), ("grn", 0.10), ("atg", 0.10), ("mtn", 0.06),
       ("eng", 0.04), ("cav", 0.06), ("arm", 0.08)]
MIX_LOWMP = [("art", 0.4), ("atg", 0.35), ("arm", 0.25)]

VAL = {"res": 1.0, "mp": 1.0, "steel": 1.2, "oil": 0.8, "rare": 4.0}

def _research(api):
    busy = set(r[0] for r in api.research)
    if len(busy) >= 2: return
    keep = 40 if api.t > 200 else 15
    for line in RESEARCH:
        if len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        if _afford(api, tl.get("cost"), keep):
            if str(api.cmd("research " + line)).startswith("ok"):
                busy.add(line)

def _recruit(api, units):
    net = api.income_by.get("res", api.income) if api.income_by else api.income
    counts = {}
    for u in units: counts[u["type"]] = counts.get(u["type"], 0) + 1
    nrec = counts.get("rec", 0)
    if nrec < (7 if api.t < 500 else 3) and api.res > 8:
        api.cmd("recruit rec")
        if api.t < 100: return
    if net is not None and net < 2 and api.t > 100: return
    reserve = 30 if api.t > 300 else 8
    mpfloor = 30 if api.t < 300 else 120
    if api.t < 500 and api.neutral_border:
        mix = MIX_EARLY
    elif api.mp < 250:
        mix = MIX_LOWMP
    else:
        mix = MIX
    total = max(1, len(units) - nrec)
    for _ in range(5):
        best = None; bd = -9
        for typ, share in mix:
            c = api.unit_costs.get(typ)
            if not c: continue
            if api.res - c.get("res", 0) < reserve or api.mp - c.get("mp", 0) < mpfloor: continue
            if any(api.stock.get(k, 0) < c.get(k, 0) for k in ("steel", "oil", "rare")): continue
            d = share - counts.get(typ, 0) / float(total)
            if d > bd: bd = d; best = typ
        if not best: return
        if not str(api.cmd("recruit " + best)).startswith("ok"): return
        counts[best] = counts.get(best, 0) + 1
        total += 1

def _diplo(api):
    mem = api.mem
    po = mem.setdefault("pact_off", {})
    for o in list(api.offers_in or []):
        try:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o["id"])
            elif o.get("kind") == "trade":
                get = sum(VAL.get(k, 1) * v for k, v in (o.get("they_give") or {}).items())
                give = sum(VAL.get(k, 1) * v for k, v in (o.get("you_give") or {}).items())
                ok = get >= give * 1.05
                for k, v in (o.get("you_give") or {}).items():
                    have = api.res if k == "res" else (api.mp if k == "mp" else api.stock.get(k, 0))
                    if have - v < (100 if k in ("res", "mp") else 50): ok = False
                api.cmd(("accept %s" if ok else "reject %s") % o["id"])
        except Exception:
            pass
    pacts = api.pacts or {}
    outs = set()
    for o in (api.offers_out or []):
        outs.add(o.get("to"))
    sent = 0
    for f in (api.met or []):
        if f == api.me or sent >= 4: continue
        p = pacts.get(f)
        if p and not p.get("broken_by"): continue
        if f in outs: continue
        if api.t - po.get(f, -999) < 120: continue
        api.cmd("offer %s pact" % f)
        if f not in mem.setdefault("said", {}):
            api.cmd("say %s Maghreb wants peace and trade with you. Pact accepted; we will never break it first." % f)
            mem["said"][f] = api.t
        po[f] = api.t
        sent += 1

def tick(api):
    mem = api.mem
    ops = mem.setdefault("ops", {})
    units = api.units
    byid = dict((u["id"], u) for u in units)
    provs = api.provs
    inop = set()
    for o in ops.values():
        for i in o["ids"]: inop.add(i)

    try:
        _diplo(api)
    except Exception:
        pass
    _research(api)
    _recruit(api, units)

    for tgt in list(ops.keys()):
        o = ops[tgt]
        ids = [i for i in o["ids"] if i in byid]
        o["ids"] = ids
        pr = provs.get(tgt, {})
        done = (not ids) or pr.get("owner") == "me"
        age = api.t - o["start"]
        if not done:
            if o["launched"]:
                live = [i for i in ids if byid[i]["str"] >= 35]
                if api.t - o.get("lt", o["start"]) > 48 or not live:
                    done = True
            elif age >= 24:
                e = api.enemy.get(tgt)
                dstr = e["str"] if e else 0
                att = sum(byid[i]["str"] for i in ids)
                rdy = sum(byid[i]["rdy"] for i in ids) / (100.0 * len(ids))
                bon = max([byid[i].get("bonus", 0) or 0 for i in ids] + [0])
                heavy = len([i for i in ids if byid[i]["type"] in ("art", "eng", "arm")]) / float(len(ids))
                dirs = len(set(byid[i]["prov"] for i in ids))
                p = _pwin(api, att, dstr, pr, bon / 100.0, rdy, heavy, dirs)
                iscap = tgt in api.enemy_capitals.values()
                if bon >= 40 and rdy >= 0.6 and (p >= 0.65 or (iscap and p >= 0.5) or dstr == 0):
                    movers = [i for i in ids if byid[i]["type"] != "art"] or ids
                    api.cmd("move %s P%d" % (",".join(map(str, movers)), tgt))
                    arts = [i for i in ids if i not in movers]
                    if arts: api.cmd("hold " + ",".join(map(str, arts)))
                    o["launched"] = True; o["lt"] = api.t
                elif age > 80 or rdy < 0.4:
                    done = True
        if done:
            if ids: api.cmd("front " + ",".join(map(str, ids)))
            del ops[tgt]
            for i in ids: inop.discard(i)

    exp_ids = []; front_ids = []; scout_ids = []
    neutral = bool(api.neutral_border)
    for u in units:
        if u["id"] in inop: continue
        if u["front"] or u["expand"] or u["explore"] or u["path"]: continue
        if u["state"] in ("moving", "assault", "preparing", "routing"): continue
        if u["type"] == "rec": scout_ids.append(u["id"])
        elif neutral and u["type"] not in ("art", "atg", "mil", "eng", "arm"): exp_ids.append(u["id"])
        else: front_ids.append(u["id"])
    if scout_ids:
        api.cmd(("explore " if api.unexplored else "front ") + ",".join(map(str, scout_ids)))
    if exp_ids: api.cmd("expand " + ",".join(map(str, exp_ids)))
    if front_ids: api.cmd("front " + ",".join(map(str, front_ids)))

    if api.t < 72: return

    avail = {}; cnt = {}
    for u in units:
        cnt[u["prov"]] = cnt.get(u["prov"], 0) + 1
        if u["id"] in inop or u["type"] in ("rec", "mil"): continue
        if u["str"] < 80 or u["rdy"] < 70 or u.get("mor", 70) < 50: continue
        if u["state"] in ("routing", "shaken", "moving", "assault", "pinned"): continue
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
    best = []
    for tgt in cands:
        if tgt in ops: continue
        pr = provs[tgt]
        e = api.enemy.get(tgt)
        srcs = [n for n in pr.get("nbrs", []) if n in avail and avail[n]]
        if not srcs: continue
        if not e or e.get("n", 0) == 0:
            if pr.get("visible") and empty_sent < 6:
                for src in srcs:
                    if cnt.get(src, 0) > 1 and avail[src]:
                        us = [x for x in avail[src] if x["type"] != "art"]
                        if not us: continue
                        u = us[0]; avail[src].remove(u)
                        api.cmd("move %d P%d" % (u["id"], tgt))
                        ops[tgt] = {"ids": [u["id"]], "start": api.t, "launched": True, "lt": api.t}
                        inop.add(u["id"]); cnt[src] -= 1; empty_sent += 1
                        break
            continue
        if not e.get("exact"): continue
        fort = pr.get("fort", 0) or 0
        if fort > 1: continue
        pick = []
        for s in srcs:
            us = sorted(avail[s], key=lambda x: -x["str"])
            pick.extend(us[:max(0, min(len(us), cnt.get(s, 0) - 1))])
        if len(pick) < 4: continue
        pick = pick[:18]
        att = sum(u["str"] for u in pick)
        dstr = e.get("str", 100)
        if att < 3.0 * dstr: continue
        heavy = len([u for u in pick if u["type"] in ("art", "eng", "arm")]) / float(len(pick))
        rdy = sum(u["rdy"] for u in pick) / (100.0 * len(pick))
        dirs = len(set(u["prov"] for u in pick))
        p = _pwin(api, att, dstr, pr, 0.45, rdy, heavy, dirs)
        iscap = tgt in api.enemy_capitals.values()
        score = p + (0.3 if iscap else 0) + 0.02 * (pr.get("y", 0) or 0)
        if p >= 0.65:
            best.append((score, tgt, pick))
    best.sort(key=lambda b: -b[0])
    used = set()
    for score, tgt, pick in best:
        if len(ops) >= 4: break
        pick = [u for u in pick if u["id"] not in used]
        if len(pick) < 4: continue
        ids = [u["id"] for u in pick]
        r = api.cmd("prepare %s P%d" % (",".join(map(str, ids)), tgt))
        if str(r).startswith("ok"):
            ops[tgt] = {"ids": ids, "start": api.t, "launched": False}
            for i in ids: used.add(i)
