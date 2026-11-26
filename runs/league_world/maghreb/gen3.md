Third war in a row at 65 provinces (23rd place). Three problems show in the record:

1. **Growth stops early.** I reach about 65 provinces by day 15, then nothing. I signed pacts with every neighbour, so I was boxed in with nobody left to take land from.
2. **The army eats the economy.** Income falls from 58 to 32 a day while the army grows to 1,050 units.
3. **Every assault failed (0 of 107).** Almost all had readiness under 34 and no prepared-attack bonus. These were mostly single units drifting into enemy land, not real attacks.

New orders:
- **Expand first** until neutral land runs out (or hour 420).
- **Then pick one foe.** That is the neighbour with the most border contact and the weakest visible troops. I keep peace with everyone else, refuse the foe's pact offers, and break an existing pact with it once.
- **Strike force.** A named group (about 20% of the army, up to 32 units) gathers at a staging province and rests. It then prepares the attack with a scout beside the target. It launches only with bonus ≥40, readiness ≥0.6 and a strength edge of about 2.5x. Artillery fires from the staging province.
- **After a capture,** the force chains on to the next province toward the foe's capital, since taking a capital hands over all its land. After a failed or stalled attack it pulls back, refits, or switches target.
- **Single-unit grabs** of empty enemy provinces are kept, but only with rested units.
- **Recruiting** stops when net income is low, so research and income come first.

```python
def _tdf(pr):
    c = str(pr.get("terrain", "p"))[:1]
    return {"m": 2.0, "h": 1.5, "f": 1.25}.get(c, 1.0)

def _afford(api, cost, keep):
    if not cost: return False
    for k, v in cost.items():
        if k == "res":
            if api.res - v < keep: return False
        elif k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) < v: return False
    return True

RESEARCH = ["farming", "conscription", "industry", "logistics", "medicine",
            "staffwork", "inf.weapons", "art.weapons", "grn.weapons", "discipline",
            "mining", "drill", "inf.protection", "art.protection", "fieldworks",
            "refining", "drilling", "mtn.weapons", "grn.protection", "cav.weapons"]

MIX_EARLY = [("cav", 0.35), ("inf", 0.45), ("mtn", 0.08), ("art", 0.07), ("atg", 0.05)]
MIX = [("inf", 0.30), ("art", 0.20), ("grn", 0.18), ("atg", 0.08), ("mtn", 0.06),
       ("eng", 0.06), ("arm", 0.06), ("cav", 0.06)]
MIX_LOWMP = [("art", 0.45), ("atg", 0.25), ("arm", 0.30)]
VAL = {"res": 1.0, "mp": 1.0, "steel": 1.2, "oil": 0.8, "rare": 4.0}
STRIKE_T = ("grn", "inf", "mtn", "art", "eng", "arm", "mot", "mec", "hvt", "rkt", "cav")

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
    if nrec < (7 if api.t < 500 else 4) and api.res > 8:
        api.cmd("recruit rec")
        if api.t < 100: return
    if net is not None and api.t > 100 and net < 6 and api.res < 300: return
    reserve = 40 if api.t > 300 else 8
    mpfloor = 30 if api.t < 300 else 120
    if api.t < 400 and api.neutral_border: mix = MIX_EARLY
    elif api.mp < 250: mix = MIX_LOWMP
    else: mix = MIX
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
    foe = mem.get("foe")
    po = mem.setdefault("pact_off", {})
    for o in list(api.offers_in or []):
        try:
            if o.get("kind") == "pact":
                api.cmd(("reject %s" if o.get("frm") == foe else "accept %s") % o["id"])
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
    outs = set(o.get("to") for o in (api.offers_out or []))
    sent = 0
    for f in (api.met or []):
        if f == api.me or f == foe or sent >= 4: continue
        p = pacts.get(f)
        if p and not p.get("broken_by"): continue
        if f in outs or api.t - po.get(f, -999) < 120: continue
        api.cmd("offer %s pact" % f)
        if f not in mem.setdefault("said", {}):
            api.cmd("say %s Maghreb offers peace along our border. Accept the pact and we both grow elsewhere." % f)
            mem["said"][f] = api.t
        po[f] = api.t
        sent += 1

def _dist(a, b):
    return math.hypot((a.get("x", 0) or 0) - (b.get("x", 0) or 0), (a.get("y0", 0) or 0) - (b.get("y0", 0) or 0))

def _pick_foe(api):
    provs = api.provs; on = api.owner_name or {}
    cnt = {}; st = {}
    for pid in api.border:
        pr = provs.get(pid)
        if not pr: continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if not q or q.get("owner") != "enemy": continue
            f = on.get(n)
            if not f: continue
            cnt[f] = cnt.get(f, 0) + 1
            e = api.enemy.get(n)
            st[f] = st.get(f, 0) + (e["str"] if e else 150)
    best = None; bs = -1
    pacts = api.pacts or {}
    for f, c in cnt.items():
        sc = c / (1.0 + st[f] / (100.0 * c))
        if f not in pacts: sc *= 1.5
        if sc > bs: bs = sc; best = f
    return best

def _new_target(api, foe, near, bad):
    provs = api.provs; on = api.owner_name or {}
    caps = api.enemy_capitals or {}
    capp = None
    for pid, cp in caps.items():
        if cp in provs and on.get(cp) == foe: capp = provs[cp]
    best = None; bs = 1e18
    for pid in api.border:
        pr = provs.get(pid)
        if not pr or not pr.get("supplied", True): continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if not q or q.get("owner") != "enemy" or on.get(n) != foe or n in bad: continue
            e = api.enemy.get(n)
            est = e["str"] if e else 200
            cost = (est + 50) * _tdf(q) * (1 + 0.5 * (q.get("fort", 0) or 0)) * (1.6 if q.get("harsh") else 1.0)
            cost -= 15 * (q.get("y", 0) or 0)
            if capp: cost += 0.5 * _dist(q, capp)
            if near: cost += 2.0 * _dist(q, near)
            if pr.get("harsh"): cost += 100
            if cost < bs: bs = cost; best = (n, pid)
    return best

def _campaign(api, units, byid, inop):
    mem = api.mem; provs = api.provs; t = api.t
    c = mem.get("camp")
    if c:
        ids = [i for i in c["ids"] if i in byid]
        c["ids"] = ids
        tgt = c["tgt"]; stage = c["stage"]
        pr = provs.get(tgt, {})
        if pr.get("owner") == "me":
            keep = [i for i in ids if byid[i]["str"] >= 50 and byid[i]["mor"] >= 30]
            weak = [i for i in ids if i not in keep]
            if weak: api.cmd("front " + ",".join(map(str, weak)))
            mem["wins"] = mem.get("wins", 0) + 1; mem["last_win"] = t
            nt = _new_target(api, mem.get("foe"), pr, set(mem.get("bad", [])))
            if nt and len(keep) >= 6:
                c.update({"tgt": nt[0], "stage": nt[1], "ids": keep, "phase": "gather", "t0": t, "fails": 0})
                api.cmd("move %s P%d" % (",".join(map(str, keep)), nt[1]))
            else:
                if keep: api.cmd("front " + ",".join(map(str, keep)))
                mem["camp"] = None
            for i in ids: inop.add(i)
            return
        if len(ids) < 4 or pr.get("owner") == "neutral":
            if ids: api.cmd("front " + ",".join(map(str, ids)))
            mem["camp"] = None
            return
        for i in ids: inop.add(i)
        rec = c.get("rec")
        if rec in byid:
            inop.add(rec)
            if byid[rec]["prov"] != stage and not byid[rec]["path"]:
                api.cmd("move %d P%d" % (rec, stage))
        ph = c["phase"]
        here = [i for i in ids if byid[i]["prov"] == stage and not byid[i]["path"]]
        if ph == "gather":
            for i in ids:
                u = byid[i]
                if u["prov"] != stage and not u["path"] and u["state"] not in ("moving", "routing"):
                    api.cmd("move %d P%d" % (i, stage))
            if len(here) >= 0.75 * len(ids) or t - c["t0"] > 120:
                if here:
                    r = api.cmd("prepare %s P%d" % (",".join(map(str, here)), tgt))
                    if str(r).startswith("ok"):
                        c["phase"] = "prep"; c["tp"] = t
                    elif t - c["t0"] > 160:
                        mem.setdefault("bad", []).append(tgt)
                        api.cmd("front " + ",".join(map(str, ids)))
                        mem["camp"] = None
            return
        if ph == "rest":
            if t - c["tr"] > 48:
                c["phase"] = "gather"; c["t0"] = t
            return
        if ph == "prep":
            late = [i for i in here if byid[i].get("plan", -1) != tgt]
            if late: api.cmd("prepare %s P%d" % (",".join(map(str, late)), tgt))
            for i in ids:
                u = byid[i]
                if u["prov"] != stage and not u["path"] and u["state"] not in ("moving", "routing"):
                    api.cmd("move %d P%d" % (i, stage))
            pl = [byid[i] for i in here]
            if not pl: return
            e = api.enemy.get(tgt)
            dstr = e["str"] if e else (0 if pr.get("visible") else 150)
            att = sum(u["str"] for u in pl)
            rdy = sum(u["rdy"] for u in pl) / (100.0 * len(pl))
            bon = max([u.get("bonus", 0) or 0 for u in pl] + [0])
            age = t - c["tp"]
            go = False
            if dstr == 0 and pr.get("visible"): go = True
            elif bon >= 40 and rdy >= 0.6 and att >= 2.5 * dstr: go = True
            elif age > 72 and rdy >= 0.55 and att >= 3.5 * dstr: go = True
            if go:
                movers = [u["id"] for u in pl if u["type"] not in ("art", "rkt")]
                arts = [u["id"] for u in pl if u["type"] in ("art", "rkt")]
                if movers:
                    api.cmd("move %s P%d" % (",".join(map(str, movers)), tgt))
                    if arts: api.cmd("hold " + ",".join(map(str, arts)))
                    c["phase"] = "go"; c["tl"] = t
                return
            if age > 140:
                mem.setdefault("bad", []).append(tgt)
                api.cmd("front " + ",".join(map(str, ids)))
                mem["camp"] = None
            return
        if ph == "go":
            live = [i for i in ids if byid[i]["str"] >= 35 and byid[i]["prov"] != stage]
            if t - c["tl"] > 54 or (t - c["tl"] > 12 and not live):
                api.cmd("move %s P%d" % (",".join(map(str, ids)), stage))
                c["fails"] = c.get("fails", 0) + 1
                if c["fails"] >= 2:
                    mem.setdefault("bad", []).append(tgt)
                    api.cmd("front " + ",".join(map(str, ids)))
                    mem["camp"] = None
                else:
                    c["phase"] = "rest"; c["tr"] = t
            return
        return
    # new campaign
    foe = mem.get("foe")
    if not foe: return
    if t - mem.get("camp_end", -999) < 12: return
    nt = _new_target(api, foe, None, set(mem.get("bad", [])))
    if not nt:
        mem["foe_fail"] = mem.get("foe_fail", 0) + 1
        return
    tgt, stage = nt
    sp = api.provs.get(stage, {})
    fighters = [u for u in units if u["id"] not in inop and u["type"] in STRIKE_T
                and u["str"] >= 75 and u["rdy"] >= 50 and u.get("mor", 70) >= 45
                and u["state"] not in ("routing", "shaken", "assault", "pinned")
                and not u["expand"] and not u["explore"]]
    k = int(min(32, max(10, 0.2 * len(units))))
    def dd(u):
        return _dist(api.provs.get(u["prov"], {}), sp)
    fighters.sort(key=dd)
    pick = fighters[:k]
    if len(pick) < 8: return
    ids = [u["id"] for u in pick]
    api.cmd("move %s P%d" % (",".join(map(str, ids)), stage))
    api.cmd("group strike %s" % ",".join(map(str, ids)))
    recs = [u for u in units if u["type"] == "rec" and u["id"] not in inop]
    rec = None
    if recs:
        recs.sort(key=dd); rec = recs[0]["id"]
        api.cmd("move %d P%d" % (rec, stage))
    mem["camp"] = {"tgt": tgt, "stage": stage, "ids": ids, "phase": "gather", "t0": t, "rec": rec, "fails": 0}
    for i in ids: inop.add(i)
    if rec: inop.add(rec)

def tick(api):
    mem = api.mem
    units = api.units
    byid = dict((u["id"], u) for u in units)
    provs = api.provs
    t = api.t
    # foe choice
    if t >= 200 and (not api.neutral_border or t >= 420):
        foe = mem.get("foe")
        stale = foe and t - max(mem.get("last_win", 0), mem.get("foe_t", 0)) > 360
        if not foe or stale or mem.get("foe_fail", 0) > 8:
            nf = _pick_foe(api)
            if nf:
                if nf != foe:
                    mem["foe"] = nf; mem["foe_t"] = t; mem["bad"] = []
                    mem["last_win"] = t
                else:
                    mem["foe_t"] = t
                mem["foe_fail"] = 0
        foe = mem.get("foe")
        if foe:
            p = (api.pacts or {}).get(foe)
            if p and not p.get("broken_by") and mem.get("broke") != foe:
                if p.get("ends") is None or p.get("ends") - t > 200:
                    api.cmd("break %s" % foe)
                mem["broke"] = foe
    try:
        _diplo(api)
    except Exception:
        pass
    _research(api)
    _recruit(api, units)

    inop = set()
    ops = mem.setdefault("ops", {})
    for tgt in list(ops.keys()):
        o = ops[tgt]
        ids = [i for i in o["ids"] if i in byid]
        if not ids or provs.get(tgt, {}).get("owner") == "me" or t - o["start"] > 36:
            if ids: api.cmd("front " + ",".join(map(str, ids)))
            del ops[tgt]
        else:
            o["ids"] = ids
            for i in ids: inop.add(i)

    if t >= 200:
        try:
            _campaign(api, units, byid, inop)
        except Exception:
            mem["camp"] = None

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

    if t < 72: return
    # grab visibly empty enemy provinces with rested single units
    pacts = api.pacts or {}
    on = api.owner_name or {}
    cnt = {}; avail = {}
    for u in units:
        cnt[u["prov"]] = cnt.get(u["prov"], 0) + 1
        if u["id"] in inop or u["type"] in ("rec", "mil", "art", "atg"): continue
        if u["str"] < 80 or u["rdy"] < 70 or u["state"] in ("routing", "shaken", "moving", "assault", "pinned"): continue
        if provs.get(u["prov"], {}).get("owner") != "me": continue
        avail.setdefault(u["prov"], []).append(u)
    sent = 0
    for pid in api.border:
        if sent >= 4: break
        pr = provs.get(pid)
        if not pr or pid not in avail or cnt.get(pid, 0) < 2: continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if not q or q.get("owner") != "enemy" or not q.get("visible") or n in ops: continue
            f = on.get(n)
            pp = pacts.get(f)
            if pp and not pp.get("broken_by"): continue
            e = api.enemy.get(n)
            if e and e.get("n", 0) > 0: continue
            if not avail[pid]: break
            u = avail[pid].pop()
            api.cmd("move %d P%d" % (u["id"], n))
            ops[n] = {"ids": [u["id"]], "start": t}
            cnt[pid] -= 1; sent += 1
            break
```

```letters
to iberia: Maghreb accepts peace across the strait. Send the pact offer at the start and we will accept it.
to sahelia: Maghreb agrees: peace along the desert border. Offer the pact and we will accept it.
to nilotica: Maghreb seeks a lasting pact with Nilotica, not a short one. Offer it unbounded and we accept.
```