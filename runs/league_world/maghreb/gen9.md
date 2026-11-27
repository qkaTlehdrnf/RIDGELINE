This war is different. It runs 9,216 hours instead of 600, covers years 0 to 2000, and starts with only inf, mil and rec. My last policy never researched discoveries, so it would stay ancient for the whole war. It also let upkeep grow without limit and left most units on old models.

Changes:
1. **Discoveries.** A tree walker uses one research slot for discoveries in a fixed priority order. Economy comes first (roads, crop rotation, banking, steam, railways), then the military line (iron working, horses, siege, pikes, gunpowder, rifling and on to tanks and rockets). It starts one only if res stays above a reserve after paying, including any strategic resources bought abroad.
2. **Upgrades.** Upgrade lines get the second slot only. Both slots go to upgrades only when no discovery is open.
3. **Upkeep limits.** Recruiting stops when upkeep exceeds 65% of income or net income turns negative. A treasury must last 9,000 hours.
4. **Refits.** Old-model units that are rested, supplied and out of combat on my own land are refitted in small affordable batches.
5. **Kept as before.** The pact-everyone diplomacy, expansion, oil-for-res trading and the opportunistic campaign logic stay. Mil is added as a cheap garrison filler when manpower is low.

```python
def _tdf(pr):
    c = str(pr.get("terrain", "p"))[:1]
    return {"m": 2.0, "h": 1.5, "f": 1.25}.get(c, 1.0)

def _have(api, k):
    if k == "res": return api.res
    if k == "mp": return api.mp
    return (api.stock or {}).get(k, 0)

def _afford(api, cost, keep):
    if not cost: return False
    for k, v in cost.items():
        if k == "res":
            if api.res - v < keep: return False
        elif k != "mp":
            if _have(api, k) < v: return False
    return True

DISC = ["roads", "iron_working", "crop_rotation", "horse_riding", "masonry", "siege_engines",
        "banking", "pikes_crossbows", "stirrup", "trebuchet", "castles", "gunpowder", "steam_power",
        "matchlock", "railways", "rifling", "dragoons", "steel_guns", "grenadiers", "field_engineering",
        "machine_guns", "combustion", "heavy_artillery", "anti_tank_guns", "tanks", "assault_rifles",
        "mechanisation", "heavy_armour", "rocket_artillery", "hillmen", "galleys", "flight",
        "jet_engines", "rocketry", "composite_armour", "satellites", "guided_weapons",
        "sailing", "navigation", "bombers", "ballistic_missiles", "ships_of_the_line", "ironclads",
        "dreadnoughts", "submarines", "carriers"]

RESEARCH = ["farming", "conscription", "logistics", "industry", "medicine", "mining", "drilling",
            "inf.weapons", "inf.protection", "art.weapons", "grn.weapons", "discipline", "drill", "staffwork",
            "refining", "cav.weapons", "art.protection", "atg.weapons", "fieldworks",
            "grn.protection", "cav.protection", "mtn.weapons", "arm.weapons", "atg.protection",
            "inf.mobility", "art.mobility", "eng.protection", "arm.protection"]

MIX_EARLY = [("cav", 0.55), ("inf", 0.40), ("art", 0.05)]
MIX = [("inf", 0.30), ("art", 0.20), ("grn", 0.16), ("atg", 0.08), ("mtn", 0.05),
       ("eng", 0.05), ("arm", 0.08), ("cav", 0.05), ("mil", 0.03)]
MIX_LOWMP = [("art", 0.35), ("atg", 0.25), ("arm", 0.25), ("mil", 0.15)]
VAL = {"res": 1.0, "mp": 1.0, "steel": 0.6, "oil": 0.4, "rare": 4.0, "coal": 1.5, "rubber": 0.8}
STRIKE_T = ("grn", "inf", "mtn", "art", "eng", "arm", "mot", "mec", "hvt", "rkt", "cav")
EXP_T = ("cav", "inf", "mot", "mtn", "mil", "grn", "mec")

def _is_disc(api, name):
    return name in (api.tree or {})

def _discover(api):
    tree = api.tree or {}
    if not tree: return
    busy = [r[0] for r in (api.research or [])]
    if len(busy) >= 2: return
    if any(_is_disc(api, b) for b in busy): return
    if api.t < 24: return
    keep = 60 if api.t < 400 else 150
    order = DISC + [d for d in tree if d not in DISC]
    for d in order:
        e = tree.get(d)
        if not e or e.get("status") != "open": continue
        need = e.get("res_now")
        if need is None:
            c = e.get("cost") or {}
            need = c.get("res", 0) if isinstance(c, dict) else 0
        try: need = float(need)
        except Exception: continue
        if api.res - need < keep:
            api.count("disc_wait")
            return
        r = str(api.cmd("research " + d))
        if r.startswith("ok"):
            api.count("disc_start")
        return

def _research(api):
    busy = [r[0] for r in (api.research or [])]
    if len(busy) >= 2: return
    if api.t < 150: return
    tree = api.tree or {}
    disc_open = any(e.get("status") == "open" for e in tree.values())
    nup = sum(1 for b in busy if not _is_disc(api, b))
    if disc_open and nup >= 1: return
    keep = 120 if api.t > 400 else 40
    for line in RESEARCH:
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        if _afford(api, tl.get("cost"), keep):
            if str(api.cmd("research " + line)).startswith("ok"):
                return

def _refit(api, units):
    mem = api.mem
    if api.t - mem.get("refit_t", -999) < 24: return
    mem["refit_t"] = api.t
    if not api.old_units or api.res < 400: return
    rc = api.refit_cost or {}
    budget = (api.res - 300) * 0.5
    ids = []
    for u in units:
        if not u.get("old") or u.get("fighting") or u.get("dom", 0) != 0: continue
        if u["rdy"] < 65 or not u.get("supplied", True): continue
        if api.provs.get(u["prov"], {}).get("owner") != "me": continue
        c = rc.get(u["type"]) or {}
        cr = c.get("res", 0) or 0
        if any((api.stock or {}).get(k, 0) < (c.get(k, 0) or 0) * (len(ids) + 1) for k in ("steel", "oil", "rare")):
            continue
        if cr > budget: break
        budget -= cr
        ids.append(u["id"])
        if len(ids) >= 25: break
    if ids:
        if str(api.cmd("refit " + ",".join(map(str, ids)))).startswith("ok"):
            api.count("refit", len(ids))

def _economy(api):
    mem = api.mem; t = api.t
    if t < 200 or t - mem.get("eco_t", -99) < 12: return
    mem["eco_t"] = t
    eco = api.economy or {}
    works = eco.get("works") or []
    if len(works) >= 3: return
    net = api.income
    if api.res < 220 or (net is not None and net < 3): return
    busy = set()
    for w in works:
        try: busy.add(w[1])
        except Exception: pass
    plist = list(eco.get("provs") or [])
    def sc(p):
        return (p.get("yield_now", 0) or 0) * (p.get("agg", 1) or 1) + (3 if p.get("city") else 0)
    plist.sort(key=lambda p: -sc(p))
    n = len(works)
    for p in plist[:25]:
        if n >= 3: return
        pid = p.get("prov")
        if pid is None or pid in busy: continue
        if not api.provs.get(pid, {}).get("supplied", True): continue
        dev = p.get("dev", 0) or 0
        room = p.get("room", 0) or 0
        c = p.get("dev_cost")
        if isinstance(c, dict) and dev + 1 <= room and dev < 5 and p.get("can_dev"):
            if _afford(api, c, 180):
                if str(api.cmd("develop P%d" % pid)).startswith("ok"):
                    api.count("develop"); n += 1; busy.add(pid); continue
        infra = p.get("infra", 0) or 0
        c = p.get("infra_cost")
        if isinstance(c, dict) and infra < 3 and dev >= 1 and dev + 1 > room and p.get("can_infra"):
            if _afford(api, c, 180):
                if str(api.cmd("build P%d" % pid)).startswith("ok"):
                    api.count("build"); n += 1; busy.add(pid)

def _recruit(api, units):
    net = api.income_by.get("res", api.income) if api.income_by else api.income
    counts = {}
    for u in units: counts[u["type"]] = counts.get(u["type"], 0) + 1
    nrec = counts.get("rec", 0)
    want = 8 if api.t < 600 else 4
    if nrec < want and api.res > 8:
        api.cmd("recruit rec")
        if api.t < 48: return
    b = api.budget or {}
    us = b.get("upkeep_share")
    if api.t > 150 and us is not None and us > 0.65:
        api.count("upkeep_cap"); return
    if net is not None and api.t > 100 and net < 10 and api.res < 300: return
    reserve = 60 if api.t > 300 else 8
    if api.t > 400: reserve = 200
    mpfloor = 30 if api.t < 300 else 120
    if api.t < 500 and api.neutral_border: mix = MIX_EARLY
    elif api.mp < 250: mix = MIX_LOWMP
    else: mix = MIX
    can = set(api.can_raise or api.unit_costs.keys())
    mix = [(ty, s) for ty, s in mix if ty in can]
    if not mix: mix = [("inf", 0.8), ("mil", 0.2)]
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

def _trade(api):
    mem = api.mem
    if api.t - mem.get("trade_t", -999) < 24: return
    if any(o.get("kind") == "trade" for o in (api.offers_out or [])): return
    partners = [f for f, p in (api.pacts or {}).items() if not p.get("broken_by")]
    if not partners: return
    oil = api.stock.get("oil", 0); st = api.stock.get("steel", 0)
    what = None
    j = mem.get("trade_k", 0); mem["trade_k"] = j + 1
    if oil > 400:
        opts = [("oil", 150, 60, "res"), ("oil", 150, 25, "coal"), ("oil", 120, 30, "rubber")]
        what = opts[j % 3]
    elif st > 400: what = ("steel", 150, 65, "res")
    if not what: return
    i = mem.get("trade_i", 0) % len(partners)
    mem["trade_i"] = i + 1
    mem["trade_t"] = api.t
    api.cmd("offer %s trade %d %s for %d %s" % (partners[i], what[1], what[0], what[2], what[3]))

def _victim_locked(api, f):
    m = api.mem
    return f and f == m.get("victim") and api.t - m.get("victim_t", -9999) < 700

def _diplo(api):
    mem = api.mem
    po = mem.setdefault("pact_off", {})
    for o in list(api.offers_in or []):
        try:
            if o.get("kind") in ("pact", "alliance"):
                if _victim_locked(api, o.get("frm")):
                    api.cmd("reject %s" % o["id"])
                else:
                    api.cmd("accept %s" % o["id"])
            elif o.get("kind") == "trade":
                if any(str(k).startswith("P") for k in (o.get("you_give") or {})):
                    api.cmd("reject %s" % o["id"]); continue
                get = sum(VAL.get(k, 1) * v for k, v in (o.get("they_give") or {}).items())
                give = sum(VAL.get(k, 1) * v for k, v in (o.get("you_give") or {}).items())
                ok = get >= give * 1.0
                for k, v in (o.get("you_give") or {}).items():
                    have = _have(api, k)
                    if have - v < (150 if k in ("res", "mp") else 150): ok = False
                api.cmd(("accept %s" if ok else "reject %s") % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
        except Exception:
            pass
    pacts = api.pacts or {}
    outs = set(o.get("to") for o in (api.offers_out or []))
    sent = 0
    for f in (api.met or []):
        if f == api.me or sent >= 5: continue
        if _victim_locked(api, f) or f == mem.get("victim"): continue
        p = pacts.get(f)
        if p and not p.get("broken_by") and p.get("kind") != "truce" and (p.get("ends") is None or p.get("ends") - api.t > 48): continue
        if f in outs or api.t - po.get(f, -999) < 96: continue
        api.cmd("offer %s pact" % f)
        if f not in mem.setdefault("said", {}):
            api.cmd("say %s Maghreb offers lasting peace and trades spare oil for res, coal or steel." % f)
            mem["said"][f] = api.t
        po[f] = api.t
        sent += 1

def _dist(a, b):
    return math.hypot((a.get("x", 0) or 0) - (b.get("x", 0) or 0), (a.get("y0", 0) or 0) - (b.get("y0", 0) or 0))

def _hostile(api, f):
    if not f: return False
    p = (api.pacts or {}).get(f)
    return not (p and not p.get("broken_by"))

def _pwin(api, att, dstr, q, bonus, rdy, heavy):
    m = api.model or {}
    w = m.get("w"); mu = m.get("mean"); sd = m.get("std")
    if not w or not mu or not sd: return 0.5 if att > 3 * dstr else 0.2
    x = [math.log((att + 1.0) / (dstr + 1.0)), _tdf(q), q.get("fort", 0) or 0,
         1.0 if q.get("city") else 0.0, bonus, rdy, heavy, 1.0]
    z = m.get("b", 0)
    for i in range(min(len(w), len(x))):
        z += w[i] * (x[i] - mu[i]) / (sd[i] or 1)
    return 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))

def _border_factions(api, pacted):
    provs = api.provs; on = api.owner_name or {}
    cnt = {}; st = {}; fort = {}
    for pid in api.border:
        pr = provs.get(pid)
        if not pr or not pr.get("supplied", True): continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if not q or q.get("owner") != "enemy": continue
            f = on.get(n)
            if not f: continue
            h = _hostile(api, f)
            if pacted and h: continue
            if not pacted and not h: continue
            cnt[f] = cnt.get(f, 0) + 1
            e = api.enemy.get(n)
            st[f] = st.get(f, 0) + (e["str"] if e else 150)
            fort[f] = fort.get(f, 0) + (q.get("fort", 0) or 0)
    return cnt, st, fort

def _pick_foe(api):
    cnt, st, fort = _border_factions(api, False)
    best = None; bs = -1
    for f, c in cnt.items():
        sc = c / (1.0 + st[f] * (1 + 0.5 * fort[f] / c) / (100.0 * c))
        if sc > bs: bs = sc; best = f
    return best

def _choose_victim(api, units):
    cnt, st, fort = _border_factions(api, True)
    mystr = sum(u["str"] for u in units if u["type"] in STRIKE_T)
    best = None; bs = 1e18
    for f, c in cnt.items():
        if c < 2: continue
        per = st[f] / float(c) * (1 + 0.4 * fort[f] / float(c))
        if per < bs: bs = per; best = f
    if best and mystr > 2.0 * st[best]:
        return best
    return None

def _new_target(api, foe, near, bad):
    provs = api.provs; on = api.owner_name or {}
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
            if n in (pr.get("river") or []): cost *= 1.5
            cost -= 15 * (q.get("y", 0) or 0)
            if near: cost += 2.0 * _dist(q, near)
            if pr.get("harsh"): cost += 100
            if cost < bs: bs = cost; best = (n, pid)
    return best

def _end_camp(api, ids):
    if ids: api.cmd("front " + ",".join(map(str, ids)))
    api.mem["camp"] = None; api.mem["camp_end"] = api.t

def _campaign(api, units, byid, inop):
    mem = api.mem; provs = api.provs; t = api.t
    c = mem.get("camp")
    if c:
        ids = [i for i in c["ids"] if i in byid]
        c["ids"] = ids
        tgt = c["tgt"]; stage = c["stage"]
        pr = provs.get(tgt, {})
        f = (api.owner_name or {}).get(tgt)
        if pr.get("owner") == "me":
            api.count("camp_win")
            keep = [i for i in ids if byid[i]["str"] >= 50 and byid[i]["mor"] >= 30]
            weak = [i for i in ids if i not in keep]
            if weak: api.cmd("front " + ",".join(map(str, weak)))
            mem["last_win"] = t
            nt = _new_target(api, mem.get("foe"), pr, set(mem.get("bad", [])))
            if nt and len(keep) >= 8:
                c.update({"tgt": nt[0], "stage": nt[1], "ids": keep, "phase": "gather", "t0": t, "fails": 0})
                api.cmd("move %s P%d" % (",".join(map(str, keep)), nt[1]))
            else:
                _end_camp(api, keep)
            for i in ids: inop.add(i)
            return
        if len(ids) < 4 or pr.get("owner") == "neutral" or (f and not _hostile(api, f)):
            _end_camp(api, ids); return
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
                        _end_camp(api, ids)
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
            movers = [u for u in pl if u["type"] not in ("art", "rkt", "atg")]
            if not movers: return
            att = sum(u["str"] for u in pl)
            rdy = sum(u["rdy"] for u in movers) / (100.0 * len(movers))
            bon = max([u.get("bonus", 0) or 0 for u in movers] + [0])
            if bon > 1.0: bon /= 100.0
            heavy = sum(1 for u in pl if u["type"] in ("art", "eng", "arm")) / float(len(pl))
            p = _pwin(api, att, dstr, pr, bon, rdy, heavy)
            age = t - c["tp"]
            go = (dstr == 0 and pr.get("visible")) or (bon >= 0.4 and p >= 0.5) or \
                 (age > 60 and p >= 0.55) or (age > 48 and att > 4 * dstr)
            if go:
                api.count("camp_launch")
                api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in movers), tgt))
                arts = [u["id"] for u in pl if u["type"] in ("art", "rkt", "atg")]
                if arts: api.cmd("hold " + ",".join(map(str, arts)))
                c["phase"] = "go"; c["tl"] = t
                return
            if age > 150:
                mem.setdefault("bad", []).append(tgt)
                _end_camp(api, ids)
            return
        if ph == "go":
            live = [i for i in ids if byid[i]["str"] >= 35 and byid[i]["prov"] != stage]
            if t - c["tl"] > 60 or (t - c["tl"] > 12 and not live):
                api.count("camp_fail")
                api.cmd("move %s P%d" % (",".join(map(str, ids)), stage))
                c["fails"] = c.get("fails", 0) + 1
                if c["fails"] >= 3:
                    mem.setdefault("bad", []).append(tgt)
                    _end_camp(api, ids)
                else:
                    c["phase"] = "rest"; c["tr"] = t
        return
    foe = mem.get("foe")
    if not foe or not _hostile(api, foe): return
    if t - mem.get("camp_end", -999) < 18: return
    nt = _new_target(api, foe, None, set(mem.get("bad", [])))
    if not nt:
        mem["foe_fail"] = mem.get("foe_fail", 0) + 1
        return
    tgt, stage = nt
    sp = api.provs.get(stage, {})
    fighters = [u for u in units if u["id"] not in inop and u["type"] in STRIKE_T
                and u.get("dom", 0) == 0
                and u["str"] >= 75 and u["rdy"] >= 60 and u.get("mor", 70) >= 45
                and u["state"] not in ("routing", "shaken", "assault", "pinned", "refitting")
                and not u["expand"] and not u["explore"]]
    k = int(min(130, max(16, 0.38 * len(units))))
    def dd(u):
        return _dist(api.provs.get(u["prov"], {}), sp)
    fighters.sort(key=dd)
    pick = fighters[:k]
    if len(pick) < 12: return
    ids = [u["id"] for u in pick]
    api.cmd("move %s P%d" % (",".join(map(str, ids)), stage))
    api.cmd("group strike %s" % ",".join(map(str, ids)))
    recs = [u for u in units if u["type"] == "rec" and u["id"] not in inop]
    rec = None
    if recs:
        recs.sort(key=dd); rec = recs[0]["id"]
        api.cmd("move %d P%d" % (rec, stage))
    mem["camp"] = {"tgt": tgt, "stage": stage, "ids": ids, "phase": "gather", "t0": t, "rec": rec, "fails": 0}
    api.count("camp_start")
    for i in ids: inop.add(i)
    if rec: inop.add(rec)

def _neutral_targets(api, k):
    provs = api.provs; sc = {}
    for pid in api.neutral_border:
        pr = provs.get(pid)
        if not pr: continue
        for n in pr.get("nbrs", []):
            if n in sc: continue
            q = provs.get(n)
            if not q or q.get("owner") != "neutral" or n in api.enemy: continue
            s = 3 * (q.get("y", 0) or 0) + (q.get("mp", 0) or 0) + 2 * ((q.get("steel", 0) or 0) + (q.get("oil", 0) or 0)) + 5 * (q.get("rare", 0) or 0)
            s += 3 * ((q.get("coal", 0) or 0) + (q.get("rubber", 0) or 0))
            if q.get("city"): s += 5
            if q.get("harsh"): s -= 6
            sc[n] = s
    return [n for n, s in sorted(sc.items(), key=lambda x: -x[1])[:k]]

def _hostile_zone(api):
    provs = api.provs; on = api.owner_name or {}
    z = set()
    for pid in api.border:
        pr = provs.get(pid)
        if not pr: continue
        for n in pr.get("nbrs", []):
            q = provs.get(n)
            if q and q.get("owner") == "enemy" and _hostile(api, on.get(n)):
                z.add(pid); break
    for p in api.enemy:
        z.add(p)
        for n in provs.get(p, {}).get("nbrs", []): z.add(n)
    return z

def _expand_cmd(api, ids):
    if not ids: return
    tg = _neutral_targets(api, 8)
    if tg and len(ids) >= 3:
        chunks = len(tg) + 1
        sz = max(1, len(ids) // chunks)
        i = 0
        for n in tg:
            part = ids[i:i + sz]
            if not part: break
            api.cmd("expand %s P%d" % (",".join(map(str, part)), n))
            i += sz
        if ids[i:]: api.cmd("expand " + ",".join(map(str, ids[i:])))
    else:
        api.cmd("expand " + ",".join(map(str, ids)))

def _war_policy(api, units):
    mem = api.mem; t = api.t
    own = 0
    for pr in api.provs.values():
        if pr.get("owner") == "me": own += 1
    if own > mem.get("own_max", 0):
        mem["own_max"] = own; mem["own_t"] = t
    if t < 300 or t - mem.get("war_chk", -999) < 24: return
    mem["war_chk"] = t
    stalled = t - mem.get("own_t", 0) > 150
    v = mem.get("victim")
    if v and _hostile(api, v):
        cnt, st, fort = _border_factions(api, False)
        if cnt.get(v, 0) > 0 and t - mem.get("last_win", mem.get("victim_t", t)) < 400:
            mem["foe"] = v
            return
        if t - mem.get("victim_t", t) > 200:
            api.cmd("offer %s pact" % v)
            api.count("peace_offer")
            mem["victim"] = None
    if not stalled: return
    cnt, st, fort = _border_factions(api, False)
    if cnt: return
    nv = _choose_victim(api, units)
    if nv:
        api.cmd("break %s" % nv)
        api.count("break")
        mem["victim"] = nv; mem["victim_t"] = t; mem["foe"] = nv
        mem["foe_t"] = t; mem["last_win"] = t; mem["bad"] = []; mem["foe_fail"] = 0
    else:
        api.count("no_victim")

def tick(api):
    mem = api.mem
    units = [u for u in api.units if u.get("dom", 0) == 0 and not u.get("at_sea")]
    byid = dict((u["id"], u) for u in units)
    provs = api.provs
    t = api.t
    try: _diplo(api)
    except Exception: pass
    try: _trade(api)
    except Exception: pass
    try: _discover(api)
    except Exception: api.count("disc_err")
    try: _research(api)
    except Exception: api.count("res_err")
    try: _economy(api)
    except Exception: api.count("eco_err")
    try: _refit(api, units)
    except Exception: api.count("refit_err")
    try: _recruit(api, units)
    except Exception: api.count("rec_err")
    try: _war_policy(api, units)
    except Exception: pass

    if t >= 150:
        foe = mem.get("foe")
        if not foe or not _hostile(api, foe) or mem.get("foe_fail", 0) > 8 or \
                t - max(mem.get("last_win", 0), mem.get("foe_t", 0)) > 360:
            nf = _pick_foe(api)
            if nf != foe:
                mem["foe"] = nf; mem["foe_t"] = t; mem["bad"] = []; mem["last_win"] = t
            else:
                mem["foe_t"] = t
            mem["foe_fail"] = 0

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

    if t >= 150:
        try: _campaign(api, units, byid, inop)
        except Exception: mem["camp"] = None

    exp_ids = []; front_ids = []; scout_ids = []
    neutral = bool(api.neutral_border)
    ncav_explore = sum(1 for u in units if u["explore"] and u["type"] != "rec")
    for u in units:
        if u["id"] in inop: continue
        if u["front"] or u["expand"] or u["explore"] or u["path"]: continue
        if u["state"] in ("moving", "assault", "preparing", "routing", "refitting"): continue
        if u["type"] == "rec": scout_ids.append(u["id"])
        elif neutral and u["type"] in EXP_T:
            if u["type"] == "cav" and t < 1200 and ncav_explore < 8 and api.unexplored:
                api.cmd("explore %d" % u["id"]); ncav_explore += 1
            else:
                exp_ids.append(u["id"])
        else: front_ids.append(u["id"])
    if scout_ids:
        api.cmd(("explore " if api.unexplored else "front ") + ",".join(map(str, scout_ids)))
    if exp_ids: _expand_cmd(api, exp_ids)
    if front_ids: api.cmd("front " + ",".join(map(str, front_ids)))

    if neutral and t - mem.get("reexp_t", -999) >= 24:
        mem["reexp_t"] = t
        hz = _hostile_zone(api)
        cand = [u["id"] for u in units if u["front"] and not u["expand"] and u["id"] not in inop
                and u["type"] in EXP_T and u["str"] >= 60 and u["prov"] not in hz
                and u["state"] not in ("moving", "assault", "routing", "pinned")]
        frac = 0.9 if t < 800 else 0.4
        cand = cand[:int(len(cand) * frac) + 1] if cand else []
        if cand: _expand_cmd(api, cand)

    if t < 72: return
    on = api.owner_name or {}
    cnt = {}; avail = {}
    for u in units:
        cnt[u["prov"]] = cnt.get(u["prov"], 0) + 1
        if u["id"] in inop or u["type"] in ("rec", "mil", "art", "atg"): continue
        if u["str"] < 80 or u["rdy"] < 60 or u["state"] in ("routing", "shaken", "moving", "assault", "pinned"): continue
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
            if not _hostile(api, on.get(n)): continue
            e = api.enemy.get(n)
            if e and e.get("n", 0) > 0: continue
            if not avail[pid]: break
            u = avail[pid].pop()
            api.cmd("move %d P%d" % (u["id"], n))
            ops[n] = {"ids": [u["id"]], "start": t}
            api.count("free_grab")
            cnt[pid] -= 1; sent += 1
            break
```

```letters
to iberia: Maghreb keeps the strait peace. Rubber for oil or coal is welcome; offer and we will accept fair terms.
to austral: Maghreb keeps the peace and will keep offering oil and steel for res. Thank you for fair dealing.
to kongo: Maghreb wants lasting peace with Kongo; neither of us gains from a Saharan war. Trade oil for res any time.
to sahelia: Maghreb offers lasting peace and oil for res, coal or rubber.
```

```feedback
It would help to have a clear way to tell discoveries from upgrade lines in api.research: a 'kind' field ('discovery' or 'upgrade') on each entry. Please also give api.tree a ready flag, "affordable now with keep X", or a sorted list of open discoveries by days_of_net_income. A batch refit cost preview, "refit <sel> ?", that returns the total price without spending would be useful. For long wars, the review should show the age reached over time and the upkeep share over time.
```

REVIEW: standard