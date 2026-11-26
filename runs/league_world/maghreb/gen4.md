Last war I placed 21st of 30 with 70 provinces, while the leaders held 300 to 450. Three problems stand out:

1. **Expansion stalled by day 15.** The nearby neutral land was Sahara, and too few fast units went out to grab land. The early mix now leans hard on cavalry (cheap, fast, no oil), and each expander is pointed at the best-yield free province (yield counts for score, empty desert does not).
2. **Assaults failed (2 of 29 taken).** Most went in at low readiness, below 1:1 strength, or into level-3 forts. Now targets with forts cost much more, and attacks launch only at readiness ≥ 0.7, strength ≥ 3:1 and a solid prepare bonus. Strike groups are larger (up to 60 units), with artillery firing from the staging province.
3. **Wasted stock.** I ended with about 2000 steel and 3000 oil but only 27 res. The policy now offers surplus oil and steel to pact partners for res (Abyssinia and Sahelia asked for exactly this). It also researches lines that spend steel, such as fieldworks and unit weapons.

Diplomacy stays peaceful with everyone except one chosen weak neighbour.

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
            "inf.weapons", "art.weapons", "staffwork", "grn.weapons", "fieldworks",
            "discipline", "inf.protection", "art.protection", "drill", "grn.protection",
            "cav.weapons", "mtn.weapons", "mining", "refining", "drilling"]

MIX_EARLY = [("cav", 0.55), ("inf", 0.33), ("art", 0.06), ("atg", 0.06)]
MIX = [("inf", 0.28), ("art", 0.22), ("grn", 0.20), ("atg", 0.08), ("mtn", 0.06),
       ("eng", 0.06), ("arm", 0.05), ("cav", 0.05)]
MIX_LOWMP = [("art", 0.45), ("atg", 0.25), ("arm", 0.30)]
VAL = {"res": 1.0, "mp": 1.0, "steel": 0.6, "oil": 0.4, "rare": 4.0}
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
        if api.t < 60: return
    if net is not None and api.t > 100 and net < 6 and api.res < 300: return
    reserve = 40 if api.t > 300 else 6
    mpfloor = 30 if api.t < 300 else 120
    if api.t < 400 and api.neutral_border: mix = MIX_EARLY
    elif api.mp < 250: mix = MIX_LOWMP
    else: mix = MIX
    total = max(1, len(units) - nrec)
    for _ in range(6):
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

def _trade(api):
    mem = api.mem
    if api.t - mem.get("trade_t", -999) < 36: return
    if any(o.get("kind") == "trade" for o in (api.offers_out or [])): return
    partners = [f for f, p in (api.pacts or {}).items() if not p.get("broken_by") and f != mem.get("foe")]
    if not partners: return
    oil = api.stock.get("oil", 0); st = api.stock.get("steel", 0)
    what = None
    if oil > 500: what = ("oil", 150, 70)
    elif st > 500: what = ("steel", 150, 90)
    if not what: return
    i = mem.get("trade_i", 0) % len(partners)
    mem["trade_i"] = i + 1
    mem["trade_t"] = api.t
    api.cmd("offer %s trade %d %s for %d res" % (partners[i], what[1], what[0], what[2]))

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
                    if have - v < (100 if k in ("res", "mp") else 200): ok = False
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
            api.cmd("say %s Maghreb offers lasting peace and trades spare oil and steel for res. Accept the pact and we both grow elsewhere." % f)
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
            st[f] = st.get(f, 0) + (e["str"] if e else 150) * (1 + 0.5 * (q.get("fort", 0) or 0))
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
            fort = q.get("fort", 0) or 0
            cost = (est + 50) * _tdf(q) * (1 + 1.0 * fort) * (1.6 if q.get("harsh") else 1.0)
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
            if nt and len(keep) >= 8:
                c.update({"tgt": nt[0], "stage": nt[1], "ids": keep, "phase": "gather", "t0": t, "fails": 0})
                api.cmd("move %s P%d" % (",".join(map(str, keep)), nt[1]))
            else:
                if keep: api.cmd("front " + ",".join(map(str, keep)))
                mem["camp"] = None; mem["camp_end"] = t
            for i in ids: inop.add(i)
            return
        if len(ids) < 4 or pr.get("owner") == "neutral":
            if ids: api.cmd("front " + ",".join(map(str, ids)))
            mem["camp"] = None; mem["camp_end"] = t
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
                        mem["camp"] = None; mem["camp_end"] = t
            return
        if ph == "rest":
            if t - c["tr"] > 60:
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
            fort = pr.get("fort", 0) or 0
            dstr_eff = dstr * (1 + 0.3 * fort)
            att = sum(u["str"] for u in pl)
            rdy = sum(u["rdy"] for u in pl) / (100.0 * len(pl))
            bon = max([u.get("bonus", 0) or 0 for u in pl] + [0])
            if bon <= 1.0: bon *= 100
            age = t - c["tp"]
            go = False
            if dstr == 0 and pr.get("visible"): go = True
            elif bon >= 35 and rdy >= 0.7 and att >= 3.0 * dstr_eff: go = True
            elif age > 96 and rdy >= 0.7 and att >= 4.0 * dstr_eff: go = True
            if go:
                movers = [u["id"] for u in pl if u["type"] not in ("art", "rkt", "atg")]
                arts = [u["id"] for u in pl if u["type"] in ("art", "rkt", "atg")]
                if movers:
                    api.cmd("move %s P%d" % (",".join(map(str, movers)), tgt))
                    if arts: api.cmd("hold " + ",".join(map(str, arts)))
                    c["phase"] = "go"; c["tl"] = t
                return
            if age > 160:
                mem.setdefault("bad", []).append(tgt)
                api.cmd("front " + ",".join(map(str, ids)))
                mem["camp"] = None; mem["camp_end"] = t
            return
        if ph == "go":
            live = [i for i in ids if byid[i]["str"] >= 35 and byid[i]["prov"] != stage]
            if t - c["tl"] > 54 or (t - c["tl"] > 12 and not live):
                api.cmd("move %s P%d" % (",".join(map(str, ids)), stage))
                c["fails"] = c.get("fails", 0) + 1
                if c["fails"] >= 2:
                    mem.setdefault("bad", []).append(tgt)
                    api.cmd("front " + ",".join(map(str, ids)))
                    mem["camp"] = None; mem["camp_end"] = t
                else:
                    c["phase"] = "rest"; c["tr"] = t
            return
        return
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
    k = int(min(60, max(12, 0.25 * len(units))))
    def dd(u):
        return _dist(api.provs.get(u["prov"], {}), sp)
    fighters.sort(key=dd)
    pick = fighters[:k]
    if len(pick) < 10: return
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

def _best_neutral(api):
    best = None; bs = -1e9
    provs = api.provs
    for pid in api.neutral_border:
        pr = provs.get(pid)
        if not pr: continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if not q or q.get("owner") != "neutral": continue
            if n in api.enemy: continue
            s = 3 * (q.get("y", 0) or 0) + (q.get("mp", 0) or 0) + 2 * ((q.get("steel", 0) or 0) + (q.get("oil", 0) or 0)) + 5 * (q.get("rare", 0) or 0)
            if q.get("city"): s += 5
            if q.get("harsh"): s -= 10
            if s > bs: bs = s; best = n
    return best

def tick(api):
    mem = api.mem
    units = api.units
    byid = dict((u["id"], u) for u in units)
    provs = api.provs
    t = api.t
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
    try:
        _trade(api)
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
        elif neutral and u["type"] not in ("art", "atg", "eng", "arm"): exp_ids.append(u["id"])
        else: front_ids.append(u["id"])
    if scout_ids:
        api.cmd(("explore " if api.unexplored else "front ") + ",".join(map(str, scout_ids)))
    if exp_ids:
        tgt = None
        try:
            tgt = _best_neutral(api)
        except Exception:
            tgt = None
        if tgt is not None and len(exp_ids) > 1:
            h = len(exp_ids) // 2
            api.cmd("expand %s P%d" % (",".join(map(str, exp_ids[:h])), tgt))
            api.cmd("expand " + ",".join(map(str, exp_ids[h:])))
        else:
            api.cmd("expand " + ",".join(map(str, exp_ids)))
    if front_ids: api.cmd("front " + ",".join(map(str, front_ids)))

    if t < 72: return
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
        if sent >= 6: break
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
to sahelia: Maghreb keeps the peace with Sahelia. We will offer pacts at once and trade spare oil and steel for res; accept and we both grow.
to abyssinia: Maghreb honours our pact and will not break first. Expect offers of oil and steel for res early on; accept them if they suit you.
to arabia: Maghreb seeks lasting peace with Arabia. Pact offer comes at the start; we will keep our units off your land.
to kongo: Maghreb seeks lasting peace with Kongo. Our pact offer stands from hour 0.
to anatolia: Maghreb seeks lasting peace with Anatolia; pact offered at once, and spare oil/steel for trade.
```