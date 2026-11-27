The v11 world opens with only inf, mil and rec. My gen8 policy never researched discoveries, so it would stay in the ancient age all war. Its recruit mix (cav, art, grn, rkt) would quietly fall back to infantry. The economy, depot, diplomacy and operations logic held up well (5th place, a healthy front), so I keep it.

The main change is a discovery planner:
- **Order.** Economy and military discoveries come first: roads, iron working, horse riding, siege engines, masonry, crop rotation, banking, steam power, railways. The gunpowder-to-modern line follows, then flight and armour. Ships come late, since Johannesburg is landlocked.
- **Paying.** A discovery starts only when the treasury covers its full price (`res_now`) plus a reserve. One slot goes to discoveries before upgrade lines.
- **Upkeep.** Discoveries pause while net income is negative.
- **Second slot.** Once a discovery is running, the second slot takes an upgrade line or another discovery.

Refit already exists, so new models reach the field. Recruiting now asks for mountain, motorised and tank units only once they can be raised. I keep Maghreb's lasting pact, because a quiet north frees the army to expand.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
HEAVY = ("art", "eng", "arm", "hvt", "rkt")

DISC = ["roads", "iron_working", "horse_riding", "siege_engines", "masonry", "crop_rotation",
        "pikes_crossbows", "stirrup", "trebuchet", "banking", "castles", "hillmen", "gunpowder",
        "matchlock", "steam_power", "railways", "rifling", "dragoons", "steel_guns",
        "field_engineering", "grenadiers", "machine_guns", "combustion", "heavy_artillery",
        "tanks", "anti_tank_guns", "assault_rifles", "flight", "mechanisation",
        "rocket_artillery", "heavy_armour", "bombers", "jet_engines", "rocketry",
        "composite_armour", "satellites", "guided_weapons", "ballistic_missiles",
        "galleys", "sailing", "navigation", "ships_of_the_line", "ironclads",
        "dreadnoughts", "submarines", "carriers"]

def _afford(api, typ, n=1, extra=15):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) < c.get("res", 0) * n + extra: return False
    if api.mp < c.get("mp", 0) * n + 5: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0) * n: return False
    return True

RESEARCH = ["farming", "conscription", "logistics", "mining", "staffwork", "medicine", "drill",
            "inf.protection", "inf.weapons", "industry", "art.weapons", "grn.weapons",
            "refining", "drilling", "discipline", "fieldworks", "rkt.weapons",
            "art.protection", "grn.protection", "atg.weapons", "cav.mobility", "inf.mobility",
            "cav.weapons", "rkt.protection", "art.mobility", "grn.mobility", "atg.protection"]

def _discover(api, busy):
    tree = api.tree or {}
    if not tree: return False
    if api.income < 0 and api.stock.get("res", 0) < 3000: return False
    res = api.stock.get("res", 0)
    reserve = 250 + 0.2 * api.t / 24.0 * 10
    if reserve > 1200: reserve = 1200
    order = list(DISC) + [k for k in tree if k not in DISC]
    for d in order:
        if d in busy: continue
        tr = tree.get(d)
        if not tr or tr.get("status") != "open": continue
        need = tr.get("res_now")
        if need is None:
            c = tr.get("cost") or {}
            need = c.get("res", 0) if isinstance(c, dict) else 0
        try: need = float(need)
        except Exception: need = 9999.0
        if res < need + reserve: return False
        r = api.cmd("research " + d)
        if r.startswith("ok"):
            busy.add(d)
            api.count("disc_" + d[:12])
            return True
        return False
    return False

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    tree = api.tree or {}
    ndisc = sum(1 for b in busy if b in tree)
    if ndisc == 0:
        _discover(api, busy)
        if len(busy) >= 2: return
    lines = list(RESEARCH) + [k for k in api.tech.keys() if k not in RESEARCH]
    early = bool(api.neutral_border) and api.t < 600
    for line in lines:
        if len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        if early and line not in ("farming", "conscription", "logistics", "mining", "medicine"):
            continue
        cost = tl.get("cost") or {}
        ok = True
        for k in cost:
            v = cost[k]
            if k == "res": v = v + 150
            if api.stock.get(k, 0) < v:
                ok = False
                break
        if not ok: continue
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            busy.add(line)
            return
    if len(busy) < 2 and api.stock.get("res", 0) > 2500:
        _discover(api, busy)

def _economy(api):
    if api.t < 48 or api.t % 24 >= 6: return
    eco = api.economy or {}
    works = eco.get("works") or []
    busy = set()
    for w in works:
        try: busy.add(w[1])
        except Exception: pass
    if len(works) >= 8: return
    st = api.stock
    res = st.get("res", 0); coal = st.get("coal", 0); steel = st.get("steel", 0)
    reserve = 700.0
    if api.income < 0: reserve = 1500.0
    bord = api.border or {}
    cands = []
    for p in eco.get("provs") or []:
        pid = p.get("prov")
        if pid is None or pid in busy or pid in bord: continue
        d = p.get("dev", 0) or 0
        inf = p.get("infra", 0) or 0
        city = p.get("city")
        cap = 2 + 1.5 * inf - (0 if city else 1)
        base = p.get("base", 0) or 0
        agg = p.get("agg", 1.0) or 1.0
        lvl = d + 1
        if lvl <= cap and lvl <= 6:
            gain = (base * 0.3 + 0.8) * agg - 0.12 * (lvl * lvl - d * d)
            cost = 50.0 * lvl + 8 * lvl * 3
            if gain > 0: cands.append((gain / cost, "develop", pid, 50 * lvl, 8 * lvl, 0))
        elif inf < 3 and (city or d >= 1):
            il = inf + 1
            gain = (base * 0.3 + 0.8) * agg * 0.8
            cost = 30.0 * il + 6 * il * 5
            cands.append((gain / cost * 0.7, "build", pid, 30 * il, 0, 6 * il))
    cands.sort(reverse=True)
    n = 0
    lim = 2
    if res > 3000: lim = 4
    if res > 8000: lim = 7
    for sc, kind, pid, cr, cc, cs in cands:
        if n >= lim or len(works) + n >= 8: break
        if res - cr < reserve or coal < cc or steel < cs + (40 if cs else 0): continue
        r = api.cmd("%s P%d" % (kind, pid))
        if r.startswith("ok"):
            n += 1; res -= cr; coal -= cc; steel -= cs
            api.count(kind)

def _pick(api, prefs, fallback="inf"):
    for t in prefs:
        if t in (api.can_raise or []) and _afford(api, t):
            return t
    return fallback

def _recruit(api, counts, armor_seen, nown, contact):
    if len(api.units) > 0 and api.income < 2 and api.t > 48: return
    if len(api.units) > 18 * nown + 80: return
    pend = api.mem.get("rq", 0)
    res = api.stock.get("res", 0)
    n = 3
    if res > 500: n = 5
    if res > 1200: n = 8
    if res > 2500: n = 12
    if res > 5000: n = 20
    nb = bool(api.neutral_border)
    early = nb and api.t < 900
    if early: n += 2
    for _ in range(n):
        nrec = counts.get("rec", 0)
        ncomb = len(api.units) - nrec
        if nrec < (5 if api.t < 400 else 3) or (nrec < 14 and api.t > 300 and ncomb > 20 and nrec * 18 < ncomb):
            typ = "rec"
        elif early and (not contact or pend % 3 != 2):
            typ = _pick(api, ["mot", "cav"]) if pend % 4 != 3 else "inf"
        elif nb and pend % 3 == 0:
            typ = _pick(api, ["mot", "cav"])
        else:
            k = pend % 10
            if armor_seen and k in (3, 8): typ = _pick(api, ["atg", "art"])
            elif k in (2, 6): typ = _pick(api, ["rkt", "art"])
            elif k == 1: typ = _pick(api, ["art"])
            elif k == 9: typ = _pick(api, ["hvt", "arm", "art"])
            elif k in (4, 7): typ = _pick(api, ["mec", "grn", "mtn"])
            elif k == 5: typ = _pick(api, ["eng", "arm"])
            elif k == 0: typ = _pick(api, ["arm", "cav"])
            else: typ = "inf"
            if not _afford(api, typ): typ = "inf"
        if not _afford(api, typ, 1, 400 if api.t > 600 else 15): return
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): return
        counts[typ] = counts.get(typ, 0) + 1
        if typ != "rec": pend += 1
        api.mem["rq"] = pend

def _refit(api, inop):
    if not api.old_units: return
    res = api.stock.get("res", 0)
    if res < 500: return
    lim = 10
    if res > 3000: lim = 30
    done = 0
    for u in api.units:
        if done >= lim: break
        if not u.get("old") or u["id"] in inop: continue
        if u.get("dom", 0) != 0: continue
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

def _depots(api):
    t = api.t
    if t < 72 or t % 24 >= 6: return
    deps = api.depots or {}
    for d in deps.values():
        if (d.get("opens_in") or 0) > 0: return
    over = False
    for d in deps.values():
        if (d.get("load") or 0) > (d.get("capacity") or 30) * 0.9: over = True
    if not over or len(deps) >= 7: return
    dc = api.depot_cost
    if isinstance(dc, dict): dc = dc.get("res", 150)
    try: dc = float(dc)
    except Exception: dc = 150.0
    if api.stock.get("res", 0) < dc + 250: return
    bord = set(api.border.keys())
    provs = api.provs
    dxy = []
    for p in deps:
        pp = provs.get(p)
        if pp: dxy.append((pp.get("x", 0), pp.get("y0", 0)))
    best = None; bs = -1e9
    for pid, p in provs.items():
        if p.get("owner") != "me" or not p.get("supplied") or pid in deps or pid in bord: continue
        bad = False
        for n in p.get("nbrs", []):
            if n in bord or provs.get(n, {}).get("owner") == "enemy":
                bad = True; break
        if bad: continue
        x = p.get("x", 0); y = p.get("y0", 0)
        dmin = 1e9
        for (a, b) in dxy:
            d = math.sqrt((x - a) ** 2 + (y - b) ** 2)
            if d < dmin: dmin = d
        if dmin < 20: continue
        sc = min(dmin, 80) + (40 if p.get("city") else 0) - (40 if p.get("harsh") else 0)
        if sc > bs: bs = sc; best = pid
    if best is not None:
        r = api.cmd("depot P%d" % best)
        api.count("depot_open" if r.startswith("ok") else "depot_fail")

def _trade(api):
    if api.t % 96 >= 6 or api.t < 100: return
    pacts = api.pacts or {}
    fs = [f for f in pacts if f in (api.met or [])]
    if not fs: return
    f = fs[(api.t // 96) % len(fs)]
    res = api.stock.get("res", 0)
    if res > 2500 and api.stock.get("steel", 0) < 200:
        api.cmd("offer %s trade 250 res for 120 steel" % f)
        api.count("buy_steel")
        return
    if res > 2500 and api.stock.get("oil", 0) < 60 and api.fuel_per_day > 0.5:
        api.cmd("offer %s trade 200 res for 100 oil" % f)
        return
    if res > 1500: return
    for k, n in (("oil", 300), ("rare", 150), ("steel", 300), ("coal", 300)):
        if api.stock.get(k, 0) > n + 600:
            api.cmd("offer %s trade %d %s for %d res" % (f, n, k, int(n * 0.6)))
            api.count("trade_offer")
            return

def _val(api, k):
    if k == "res": return 1.0
    if k == "mp": return 2.0
    have = api.stock.get(k, 0)
    if have < 150: return 1.5
    if have < 500: return 0.8
    return 0.2

def _diplo(api):
    mem = api.mem
    met = list(api.met or [])
    pacts = api.pacts or {}
    unpacted = [f for f in met if f not in pacts]
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            if (len(unpacted) >= 2 or o.get("frm") == "maghreb") and o.get("frm") in unpacted:
                r = api.cmd("accept %s" % o["id"])
                if r.startswith("ok"):
                    unpacted.remove(o["frm"])
                    continue
            api.cmd("reject %s" % o["id"])
        elif o.get("kind") in ("trade", "supply"):
            tg = o.get("they_give") or {}
            yg = o.get("you_give") or {}
            bad = False
            vt = 0.0; vy = 0.0
            for k, v in tg.items():
                if str(k).startswith("P"): bad = True; continue
                try: vt += float(v) * _val(api, k)
                except Exception: bad = True
            for k, v in yg.items():
                if str(k).startswith("P"): bad = True; continue
                try: v = float(v)
                except Exception: bad = True; continue
                vy += v * _val(api, k)
                lim = 300 if k == "res" else 100
                if o.get("kind") == "supply": v = v * 10
                if v > api.stock.get(k, 0) - lim and k != "mp": bad = True
                if k == "mp": bad = True
            if not bad and vt > vy * 1.1:
                api.cmd("accept %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
        else:
            api.cmd("reject %s" % o["id"])
    last = mem.get("dip_t", -1000)
    if api.t - last < 240 or len(met) < 3: return
    mem["dip_t"] = api.t
    npact = len(met) - len(unpacted)
    pending = set(o.get("to") for o in (api.offers_out or []))
    for f in unpacted:
        if npact >= len(met) // 2: break
        if len(unpacted) - 1 < 2: break
        if f in pending: continue
        api.cmd("offer %s pact" % f)
        api.cmd("say %s Austral proposes peace. We will not attack you while a pact holds." % f)
        npact += 1

def _dstr(api, tgt):
    e = api.enemy.get(tgt)
    d = 0.0
    if e: d = e["str"] * (1.0 if e.get("exact") else 1.3)
    for n in api.provs.get(tgt, {}).get("nbrs", []):
        e2 = api.enemy.get(n)
        if e2 and api.provs.get(n, {}).get("owner") == "enemy":
            d += 0.15 * e2["str"]
    return d

def _need(api, tgt):
    pr = api.provs.get(tgt, {})
    d = _dstr(api, tgt)
    f = pr.get("fort", 0) or 0
    return d * 4.0 * TDF.get(pr.get("terrain"), 1.0) * (1 + 0.3 * f) * (1.15 if pr.get("city") else 1.0) + 350

def _pwin(api, tgt, att, rdy, bon, heavy, dirs=1):
    m = api.model or {}
    w = m.get("w"); mu = m.get("mean"); sd = m.get("std")
    if not w or not mu or not sd: return 0.5
    pr = api.provs.get(tgt, {})
    e = api.enemy.get(tgt)
    d = e["str"] * (1.0 if e.get("exact") else 1.3) if e else 0.0
    x = [math.log((att + 1.0) / (d + 1.0)), TDF.get(pr.get("terrain"), 1.0),
         float(pr.get("fort", 0) or 0), 1.0 if pr.get("city") else 0.0,
         bon / 100.0, rdy / 100.0, heavy, float(dirs)]
    z = m.get("b", 0.0)
    for i in range(min(len(w), len(x))):
        s = sd[i] if sd[i] else 1.0
        z += w[i] * (x[i] - mu[i]) / s
    return _sig(z)

def _targets(api, base, taken):
    provs = api.provs
    pacts = api.pacts or {}
    fails = api.mem.setdefault("fails", {})
    caps = set(api.enemy_capitals.values())
    out = []
    seen = set()
    for b in base:
        for n in provs.get(b, {}).get("nbrs", []):
            if n in seen or n in taken: continue
            seen.add(n)
            pr = provs.get(n)
            if not pr or pr.get("owner") != "enemy": continue
            if api.owner_name.get(n) in pacts: continue
            if fails.get(str(n), -9999) > api.t - 400: continue
            f = pr.get("fort", 0) or 0
            if f >= 3: continue
            if f >= 2 and n not in caps: continue
            need = _need(api, n)
            sc = need - (pr.get("y", 0) or 0) * 8
            if pr.get("city"): sc -= 60
            if pr.get("harsh"): sc += 150
            if n in caps: sc -= 500
            if n in (api.enemy_depots or {}): sc -= 300
            out.append((sc, n, b))
    out.sort()
    return out

def _stages_for(api, tgt, cnt):
    c = []
    for n in api.provs.get(tgt, {}).get("nbrs", []):
        pr = api.provs.get(n, {})
        if pr.get("owner") != "me": continue
        s = cnt.get(n, 0) * 10 - (50 if pr.get("harsh") else 0)
        if tgt in (pr.get("sea") or []): s -= 40
        if tgt in (pr.get("river") or []): s -= 30
        c.append((s, n))
    c.sort(reverse=True)
    return [n for s, n in c[:3]]

def _free(api, u, inop):
    if u["id"] in inop or u["type"] in ("rec", "mil"): return False
    if u.get("dom", 0) != 0: return False
    if u.get("expand") or u.get("explore"): return False
    if u["str"] < 80 or u["mor"] < 55 or u["rdy"] < 70: return False
    if u["state"] in ("routing", "shaken", "refitting", "assault", "preparing"): return False
    return True

def _heavy(byid, ids):
    if not ids: return 0.0
    return sum(1 for i in ids if byid[i]["type"] in HEAVY) / float(len(ids))

def _csv(ids):
    return ",".join(str(i) for i in ids)

def _rich_neutral(api):
    mem = api.mem
    if api.t - mem.get("rn_t", -999) < 24 and "rn" in mem:
        return mem["rn"]
    lst = []
    for pid, p in api.provs.items():
        if p.get("owner") != "neutral" or p.get("harsh"): continue
        v = (p.get("y", 0) or 0) + 0.5 * (p.get("mp", 0) or 0) + 2 * ((p.get("steel", 0) or 0) + (p.get("oil", 0) or 0) + (p.get("rare", 0) or 0) + (p.get("coal", 0) or 0))
        if p.get("city"): v += 5
        lst.append((v, pid))
    lst.sort(reverse=True)
    rn = [pid for v, pid in lst[:12]]
    mem["rn"] = rn; mem["rn_t"] = api.t
    return rn

def tick(api):
    mem = api.mem
    ops = mem.setdefault("ops", {})
    fails = mem.setdefault("fails", {})
    provs = api.provs
    units = [u for u in api.units if u.get("dom", 0) == 0]
    t = api.t
    byid = {}
    counts = {}
    cnt = {}
    for u in units:
        byid[u["id"]] = u
        counts[u["type"]] = counts.get(u["type"], 0) + 1
        cnt[u["prov"]] = cnt.get(u["prov"], 0) + 1
    armor_seen = mem.get("armor", False)
    for e in api.enemy.values():
        ty = e.get("types") or {}
        try:
            if ty.get("arm") or ty.get("hvt") or ty.get("mec"): armor_seen = True
        except Exception:
            pass
    mem["armor"] = armor_seen
    nown = 0
    for p in provs.values():
        if p.get("owner") == "me": nown += 1
    contact = bool(api.enemy) or bool(api.enemy_capitals)

    try:
        _research(api)
    except Exception:
        api.count("res_err")
    try:
        _depots(api)
    except Exception:
        api.count("depot_err")
    try:
        _economy(api)
    except Exception:
        api.count("eco_err")
    try:
        _recruit(api, counts, armor_seen, nown, contact)
    except Exception:
        api.count("rec_err")
    if t % 24 < 6:
        try:
            _diplo(api)
        except Exception:
            api.count("dip_err")
        try:
            _trade(api)
        except Exception:
            pass

    inop = set()
    for tk in list(ops.keys()):
        for i in ops[tk]["u"]:
            if i in byid: inop.add(i)

    taken = set(int(k) for k in ops.keys())
    for tk in list(ops.keys()):
        op = ops[tk]
        tgt = op["tgt"]
        us = op.setdefault("us", {})
        ids = [i for i in op["u"] if i in byid]
        weak = [i for i in ids if byid[i]["str"] < 35 or byid[i]["state"] in ("routing", "shaken")]
        ids = [i for i in ids if i not in weak]
        if weak:
            api.cmd("front " + _csv(weak))
            for i in weak: inop.discard(i)
        lostst = [i for i in ids if provs.get(us.get(str(i), op["stage"]), {}).get("owner") != "me"]
        if lostst and op["ph"] != "a":
            api.cmd("front " + _csv(lostst))
            for i in lostst: inop.discard(i)
            ids = [i for i in ids if i not in lostst]
        op["u"] = ids
        pr = provs.get(tgt, {})
        def disband():
            if ids:
                api.cmd("front " + _csv(ids))
                for i in ids: inop.discard(i)
            del ops[tk]
            taken.discard(tgt)
        if not ids:
            disband(); continue
        if api.owner_name.get(tgt) in (api.pacts or {}):
            disband(); continue
        if pr.get("owner") == "me" and tgt not in api.enemy:
            api.count("op_taken")
            good = [i for i in ids if byid[i]["str"] >= 65 and byid[i]["rdy"] >= 55]
            nxt = _targets(api, [tgt], taken)
            have = sum(byid[i]["str"] for i in good)
            chosen = None
            for sc, n, b in nxt[:4]:
                if have >= _need(api, n) and _pwin(api, n, have, 70, 40, _heavy(byid, good)) >= 0.55:
                    chosen = n
                    break
            if chosen is None or len(good) < 4:
                disband(); continue
            rest = [i for i in ids if i not in good]
            if rest:
                api.cmd("front " + _csv(rest))
                for i in rest: inop.discard(i)
            del ops[tk]
            taken.discard(tgt)
            ops[str(chosen)] = {"tgt": chosen, "stage": tgt, "u": good, "ph": "g", "t0": t, "s0": have,
                                "us": dict((str(i), tgt) for i in good)}
            taken.add(chosen)
            api.cmd("move %s P%d" % (_csv(good), tgt))
            continue
        tot = sum(byid[i]["str"] for i in ids)
        if tot < 0.55 * op.get("s0", tot):
            fails[str(tgt)] = t
            api.count("op_failed")
            disband(); continue
        ph = op["ph"]
        if ph == "g":
            at = []
            lagby = {}
            for i in ids:
                s = us.get(str(i), op["stage"])
                u = byid[i]
                if u["prov"] == s and not u["path"]:
                    at.append(i)
                elif not u["path"]:
                    lagby.setdefault(s, []).append(i)
            for s in lagby:
                api.cmd("move %s P%d" % (_csv(lagby[s]), s))
            if len(at) >= 0.8 * len(ids) or (t - op["t0"] > 100 and len(at) >= 6):
                r = api.cmd("prepare %s P%d" % (_csv(at), tgt))
                if r.startswith("ok"):
                    op["ph"] = "p"; op["tp"] = t
                    late = [i for i in ids if i not in at]
                    if late:
                        api.cmd("front " + _csv(late))
                        for i in late: inop.discard(i)
                    op["u"] = at
                else:
                    disband()
            elif t - op["t0"] > 160:
                disband()
            continue
        if ph == "p":
            bon = sum(byid[i].get("bonus", 0) for i in ids) / float(len(ids))
            rdy = sum(byid[i]["rdy"] for i in ids) / float(len(ids))
            e = api.enemy.get(tgt)
            waited = t - op.get("tp", t)
            dirs = len(set(us.get(str(i), op["stage"]) for i in ids))
            p = _pwin(api, tgt, tot, rdy, bon, _heavy(byid, ids), dirs)
            go = False
            if not e and waited >= 6 and rdy >= 55: go = True
            elif bon >= 45 and rdy >= 75 and p >= 0.6: go = True
            elif bon >= 60 and rdy >= 70 and p >= 0.5: go = True
            elif waited >= 220:
                if p >= 0.55 and rdy >= 70: go = True
                else:
                    fails[str(tgt)] = t
                    disband(); continue
            if go:
                api.count("op_launch")
                mv = [i for i in ids if byid[i]["type"] not in ("art", "rkt")]
                hd = [i for i in ids if byid[i]["type"] in ("art", "rkt")]
                if not mv: mv = ids; hd = []
                api.cmd("move %s P%d" % (_csv(mv), tgt))
                if hd: api.cmd("hold " + _csv(hd))
                op["ph"] = "a"; op["lt"] = t
            continue
        if ph == "a":
            if t - op.get("lt", t) > 120:
                fails[str(tgt)] = t
                disband()

    comb = [u for u in units if u["type"] != "rec"]
    maxops = min(10, 1 + len(comb) // 80)
    budget = int(len(comb) * 0.4) - len(inop)
    if contact and len(ops) < maxops and t % 12 < 6 and budget > 10:
        cands = _targets(api, list(api.border.keys()), taken)
        pool = [u for u in comb if _free(api, u, inop)]
        tries = 0
        usedp = {}
        for sc, tgt, b in cands:
            if len(ops) >= maxops or tries >= 6 or len(pool) < 6 or budget < 10: break
            tries += 1
            sts = _stages_for(api, tgt, cnt)
            if not sts: continue
            sp = provs.get(sts[0], {})
            sx = sp.get("x", 0); sy = sp.get("y0", 0)
            need = _need(api, tgt)
            ds = []
            for u in pool:
                pp = provs.get(u["prov"])
                if not pp: continue
                d = (pp.get("x", 0) - sx) ** 2 + (pp.get("y0", 0) - sy) ** 2
                if d > 1600: continue
                if u["prov"] == api.capital and cnt.get(api.capital, 0) <= 4: continue
                ds.append((d, u["id"], u))
            ds.sort()
            pick = []; s = 0.0
            lim = min(260, budget)
            loc = dict(usedp)
            for d, i, u in ds:
                if s >= need or len(pick) >= lim: break
                p0 = u["prov"]
                if p0 in api.border and loc.get(p0, 0) + 1 > 0.55 * cnt.get(p0, 0): continue
                loc[p0] = loc.get(p0, 0) + 1
                pick.append(u); s += u["str"]
            if s < need or len(pick) < 6:
                api.count("cand_short")
                continue
            ids = [u["id"] for u in pick]
            hv = _heavy(byid, ids)
            f = provs.get(tgt, {}).get("fort", 0) or 0
            if f >= 1 and hv < 0.25 and any(k in (api.can_raise or []) for k in ("art", "eng")): continue
            if len(sts) > 1 and len(pick) < 8: sts = sts[:1]
            if _pwin(api, tgt, s, 75, 45, hv, len(sts)) < 0.55:
                api.count("cand_lowp")
                continue
            groups = {}
            us = {}
            for k, i in enumerate(ids):
                st = sts[k % len(sts)]
                groups.setdefault(st, []).append(i)
                us[str(i)] = st
            ok = False
            for st in groups:
                r = api.cmd("move %s P%d" % (_csv(groups[st]), st))
                if r.startswith("ok"): ok = True
            if not ok: continue
            api.count("op_start")
            usedp = loc
            ops[str(tgt)] = {"tgt": tgt, "stage": sts[0], "u": ids, "ph": "g", "t0": t, "s0": s, "us": us}
            taken.add(tgt)
            pset = set(ids)
            for i in ids: inop.add(i)
            budget -= len(ids)
            pool = [u for u in pool if u["id"] not in pset]

    if t % 12 < 6:
        try:
            _refit(api, inop)
        except Exception:
            pass

    recpost = mem.setdefault("recpost", {})
    for k in list(recpost.keys()):
        if int(k) not in byid or str(recpost[k]) not in ops:
            del recpost[k]
    covered = set(recpost.values())
    needs = [ops[k]["tgt"] for k in ops if ops[k]["tgt"] not in covered]
    nexp = sum(1 for u in comb if u.get("expand"))
    cap_exp = len(comb) if not contact else int(len(comb) * 0.6)
    nexplore = sum(1 for u in units if u["type"] == "rec" and u.get("explore"))
    rn = []
    if api.neutral_border:
        try:
            rn = _rich_neutral(api)
        except Exception:
            rn = []
    ri = mem.get("ri", 0)
    for u in units:
        if u.get("at_sea"): continue
        if u["type"] == "rec":
            if str(u["id"]) in recpost: continue
            if u["state"] == "routing": continue
            if needs and not (u.get("explore") and nexplore <= 2 and api.unexplored):
                tgt = needs.pop(0)
                st = ops[str(tgt)]["stage"]
                if u.get("explore"): nexplore -= 1
                api.cmd("move %d P%d" % (u["id"], st))
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
        if api.neutral_border and (nexp < cap_exp or u["type"] in ("cav", "mot")):
            r = "x"
            if rn and ri % 3 == 0:
                r = api.cmd("expand %d P%d" % (u["id"], rn[(ri // 3) % len(rn)]))
            ri += 1
            if not r.startswith("ok"):
                r = api.cmd("expand %d" % u["id"])
            if r.startswith("ok"):
                nexp += 1
                continue
        api.cmd("front %d" % u["id"])
    mem["ri"] = ri
    mem["calls"] = mem.get("calls", 0) + 1
```

```letters
to maghreb: Austral accepts a lasting pact again from the first hour. Spare oil for res is welcome once we need it.
to kongo: Austral will keep a lasting pact with Kongo if you offer one; we seek no war in the south.
```

```feedback
Shared research slots between discoveries and upgrade lines is unclear: say explicitly whether 2 slots total or 2 each. api.tree res_now is very useful. A field like api.tree[d]['value_hint'] is not wanted (blind is fine), but an api.can_research list would save iteration. Please state whether can_raise includes ship/air kinds before a coastal city exists.
```

REVIEW: standard