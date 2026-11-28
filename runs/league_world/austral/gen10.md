Last war we were eliminated, in 27th place. Three things went wrong:

- **We fell behind in technology.** We stopped in the medieval age while the others reached space. A model two or three ages ahead destroys older ones at almost no loss, so this lost the war. Most research money went to upgrade lines, many of them dead ends.
- **Our assaults were wasted.** We took 2 of 65 defended provinces and lost 65k strength against 24k.
- **We lost depots near the border.** Each one took a share of the treasury with it.

The new orders:

- **Research:** one slot always works on a tree discovery, cheapest first. Seepage from neighbours lowers the price, and key military discoveries are weighted ahead. The second slot takes another discovery or a few useful upgrade lines.
- **Saving:** while we save for a discovery, recruitment and building hold back.
- **Army size:** recruiting stops when unit upkeep passes about 45% of income.
- **Stance:** mostly defensive, with the front order digging in. We attack only with an overwhelming, prepared edge (model win chance at least 0.72).
- **Diplomacy:** accept every pact and alliance, offer pacts to everyone we have met, and renew dated pacts before they end.
- **Depots:** new depots go well behind the front. The capital depot holds most of the treasury.
- **Calls home:** a few, when we lose heavy ground, run out of money, or fall an age behind. Two scheduled reviews as well.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
HEAVY = ("art", "eng", "arm", "hvt", "rkt")
AGES = ["ancient", "medieval", "gunpowder", "industrial", "great-war", "modern", "space"]
PRI = ("iron_working", "pikes_crossbows", "matchlock", "rifling", "machine_guns", "assault_rifles",
       "siege_engines", "trebuchet", "gunpowder", "steel_guns", "heavy_artillery", "masonry", "castles",
       "roads", "crop_rotation", "banking", "steam_power", "railways", "combustion", "tanks",
       "anti_tank_guns", "mechanisation", "rocket_artillery", "horse_riding", "stirrup")
NAVAL = ("galleys", "sailing", "navigation", "ships_of_the_line", "ironclads", "dreadnoughts",
         "submarines", "carriers")
UPG = ["farming", "industry", "conscription", "medicine", "inf.protection", "inf.weapons",
       "fieldworks", "logistics", "art.weapons", "discipline", "mining", "drilling", "refining"]

def _afford(api, typ, n=1, extra=15):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) < c.get("res", 0) * n + extra: return False
    if api.mp < c.get("mp", 0) * n + 5: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0) * n: return False
    return True

def _dneed(tr):
    need = tr.get("res_now")
    if need is None:
        c = tr.get("cost") or {}
        need = c.get("res", 9999) if isinstance(c, dict) else 9999
    try: return float(need)
    except Exception: return 9999.0

def _research(api):
    mem = api.mem
    busy = set(r[0] for r in api.research)
    tree = api.tree or {}
    ndisc = sum(1 for b in busy if b in tree)
    res = api.stock.get("res", 0)
    opens = []
    for d, tr in tree.items():
        if d in busy or tr.get("status") != "open": continue
        need = _dneed(tr)
        w = 1.0
        if d in PRI: w = 0.75
        if d in NAVAL: w = 1.6
        opens.append((need * w, need, d))
    opens.sort()
    mem["save"] = 0
    if len(busy) >= 2: return
    if opens:
        pr, need, d = opens[0]
        if ndisc == 0:
            if res >= need + 100:
                r = api.cmd("research " + d)
                if r.startswith("ok"):
                    busy.add(d); ndisc += 1
                    api.count("disc_" + d[:12])
                    res -= need
            else:
                mem["save"] = need
        if len(busy) < 2 and ndisc == 1 and len(opens) > 1:
            for pr2, need2, d2 in opens:
                if d2 in busy: continue
                if res >= need2 + 1500:
                    r = api.cmd("research " + d2)
                    if r.startswith("ok"):
                        busy.add(d2); res -= need2
                        api.count("disc2")
                break
    if len(busy) >= 2: return
    if mem.get("save", 0) > 0 and res < mem["save"] * 0.8 + 400: return
    for line in UPG:
        if len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        cost = tl.get("cost") or {}
        ok = True
        for k in cost:
            v = cost[k]
            if k == "res": v = v + 300
            if api.stock.get(k, 0) < v:
                ok = False; break
        if not ok: continue
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            busy.add(line); api.count("upg")
            return

def _economy(api):
    if api.t < 48 or api.t % 24 >= 6: return
    eco = api.economy or {}
    works = eco.get("works") or []
    busy = set()
    for w in works:
        try: busy.add(w[1])
        except Exception: pass
    if len(works) >= 6: return
    st = api.stock
    res = st.get("res", 0); coal = st.get("coal", 0); steel = st.get("steel", 0)
    reserve = 700.0 + api.mem.get("save", 0) * 0.6
    if api.income < 0: reserve += 1500.0
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
    if res > 3000: lim = 3
    if res > 8000: lim = 5
    for sc, kind, pid, cr, cc, cs in cands:
        if n >= lim or len(works) + n >= 6: break
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
    if len(api.units) > 12 * nown + 60: return
    b = api.budget or {}
    try:
        us = float(b.get("upkeep_share") or 0)
    except Exception:
        us = 0.0
    if api.t > 400 and us > 0.45: 
        api.count("rec_upkeep_cap"); return
    pend = api.mem.get("rq", 0)
    res = api.stock.get("res", 0)
    save = api.mem.get("save", 0)
    extra = 15
    if api.t > 600: extra = 300 + 0.5 * save
    n = 3
    if res > 800: n = 5
    if res > 2500: n = 8
    if res > 6000: n = 14
    nb = bool(api.neutral_border)
    early = nb and api.t < 900
    if early: n += 2
    for _ in range(n):
        nrec = counts.get("rec", 0)
        ncomb = len(api.units) - nrec
        if nrec < (5 if api.t < 400 else 3) or (nrec < 10 and api.t > 300 and ncomb > 20 and nrec * 20 < ncomb):
            typ = "rec"
        elif early and pend % 3 != 2:
            typ = _pick(api, ["mot", "cav"]) if pend % 4 != 3 else "inf"
        else:
            k = pend % 10
            if armor_seen and k in (3, 8): typ = _pick(api, ["atg", "art"])
            elif k in (2, 6): typ = _pick(api, ["rkt", "art"])
            elif k == 9: typ = _pick(api, ["hvt", "arm", "art"])
            elif k in (4, 7): typ = _pick(api, ["mec", "grn", "mtn"])
            elif k == 5: typ = _pick(api, ["eng", "arm"])
            elif k == 0: typ = _pick(api, ["arm", "mot", "cav"])
            else: typ = "inf"
            if not _afford(api, typ): typ = "inf"
        if not _afford(api, typ, 1, extra): return
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): return
        counts[typ] = counts.get(typ, 0) + 1
        if typ != "rec": pend += 1
        api.mem["rq"] = pend

def _refit(api, inop):
    if not api.old_units: return
    res = api.stock.get("res", 0)
    if res < 600 + 0.5 * api.mem.get("save", 0): return
    lim = 10
    if res > 3000: lim = 30
    done = 0
    for u in api.units:
        if done >= lim: break
        if not u.get("old") or u["id"] in inop: continue
        if u.get("dom", 0) != 0: continue
        if u.get("fighting") or not u.get("supplied") or u["path"]: continue
        if u["state"] in ("routing", "assault", "preparing", "refitting", "shaken", "moving"): continue
        pp = api.provs.get(u["prov"], {})
        if pp.get("owner") != "me" or not pp.get("supplied"): continue
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
    cap = api.capital
    if cap in deps and not api.mem.get("capw"):
        r = api.cmd("depot P%d 4" % cap)
        if r.startswith("ok"): api.mem["capw"] = 1
    for d in deps.values():
        if (d.get("opens_in") or 0) > 0: return
    over = False
    for d in deps.values():
        if (d.get("load") or 0) > (d.get("capacity") or 30) * 0.9: over = True
    if not over or len(deps) >= 5: return
    if api.stock.get("res", 0) < 500: return
    bord = set(api.border.keys())
    provs = api.provs
    near = set(bord)
    for b in bord:
        for n in provs.get(b, {}).get("nbrs", []): near.add(n)
    dxy = []
    for p in deps:
        pp = provs.get(p)
        if pp: dxy.append((pp.get("x", 0), pp.get("y0", 0)))
    best = None; bs = -1e9
    for pid, p in provs.items():
        if p.get("owner") != "me" or not p.get("supplied") or pid in deps or pid in near: continue
        bad = False
        for n in p.get("nbrs", []):
            if n in near or provs.get(n, {}).get("owner") == "enemy":
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
        r = api.cmd("depot P%d 1" % best)
        api.count("depot_open" if r.startswith("ok") else "depot_fail")

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
    for o in (api.offers_in or []):
        k = o.get("kind")
        if k in ("pact", "alliance"):
            r = api.cmd("accept %s" % o["id"])
            api.count("pact_acc" if r.startswith("ok") else "pact_accfail")
        elif k in ("trade", "supply"):
            tg = o.get("they_give") or {}
            yg = o.get("you_give") or {}
            bad = False
            vt = 0.0; vy = 0.0
            for kk, v in tg.items():
                if str(kk).startswith("P"): continue
                try: vt += float(v) * _val(api, kk)
                except Exception: bad = True
            for kk, v in yg.items():
                if str(kk).startswith("P"): bad = True; continue
                try: v = float(v)
                except Exception: bad = True; continue
                vy += v * _val(api, kk)
                lim = 300 if kk == "res" else 100
                if k == "supply": v = v * 10
                if kk == "mp" or v > api.stock.get(kk, 0) - lim: bad = True
            if not bad and vt > vy * 1.1:
                api.cmd("accept %s" % o["id"])
            else:
                api.cmd("reject %s" % o["id"])
        else:
            api.cmd("reject %s" % o["id"])
    if api.t - mem.get("dip_t", -1000) < 120: return
    mem["dip_t"] = api.t
    pending = set(o.get("to") for o in (api.offers_out or []))
    sent = 0
    for f in met:
        if sent >= 8: break
        if f in pending: continue
        p = pacts.get(f)
        if p is None or p.get("kind") == "truce":
            api.cmd("offer %s pact" % f)
            if f not in mem.setdefault("wrote", {}):
                api.cmd("say %s Austral wants lasting peace with you and fair trade. We will not attack while a pact holds." % f)
                mem["wrote"][f] = api.t
            sent += 1
        elif p.get("ends") is not None and p.get("ends") - api.t < 90:
            api.cmd("offer %s pact" % f)
            sent += 1

def _trade(api):
    if api.t % 96 >= 6 or api.t < 100: return
    pacts = api.pacts or {}
    fs = [f for f in pacts if f in (api.met or [])]
    if not fs: return
    f = fs[(api.t // 96) % len(fs)]
    res = api.stock.get("res", 0)
    if res > 2500 and api.stock.get("steel", 0) < 200 and AGES.index(api.age) >= 1 if api.age in AGES else False:
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

def _dstr(api, tgt):
    e = api.enemy.get(tgt)
    d = 0.0
    if e: d = e["str"] * (1.0 if e.get("exact") else 1.4)
    for n in api.provs.get(tgt, {}).get("nbrs", []):
        e2 = api.enemy.get(n)
        if e2 and api.provs.get(n, {}).get("owner") == "enemy":
            d += 0.2 * e2["str"]
    return d

def _need(api, tgt):
    pr = api.provs.get(tgt, {})
    d = _dstr(api, tgt)
    f = pr.get("fort", 0) or 0
    return d * 5.0 * TDF.get(pr.get("terrain"), 1.0) * (1 + 0.3 * f) * (1.15 if pr.get("city") else 1.0) + 400

def _pwin(api, tgt, att, rdy, bon, heavy, dirs=1):
    m = api.model or {}
    w = m.get("w"); mu = m.get("mean"); sd = m.get("std")
    if not w or not mu or not sd: return 0.5
    pr = api.provs.get(tgt, {})
    e = api.enemy.get(tgt)
    d = e["str"] * (1.0 if e.get("exact") else 1.4) if e else 0.0
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
            if fails.get(str(n), -9999) > api.t - 600: continue
            f = pr.get("fort", 0) or 0
            if f >= 2: continue
            need = _need(api, n)
            sc = need - (pr.get("y", 0) or 0) * 8
            if pr.get("city"): sc -= 60
            if pr.get("harsh"): sc += 200
            if n in caps: sc -= 400
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
    if u.get("old"): return False
    if u["str"] < 85 or u["mor"] < 60 or u["rdy"] < 75: return False
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

def _call(api, nown):
    mem = api.mem
    t = api.t
    pk = mem.get("peak", 0)
    if nown > pk: pk = nown; mem["peak"] = pk
    if api.calls_left <= 0: return
    last = mem.get("lastcall", -99999)
    if t - last < 2400: return
    why = None
    if pk >= 20 and nown < 0.6 * pk and api.calls_left > 12:
        why = "Austral lost ground: %d provinces now, peak %d. Year %d, age %s." % (nown, pk, api.year, api.age)
    elif api.res < 50 and api.income < 0 and t > 2000 and api.calls_left > 12:
        why = "Austral treasury empty, income negative. Year %d." % api.year
    elif t >= 9600 and not mem.get("rev1"):
        mem["rev1"] = 1
        why = "Scheduled review year %d: %d provinces, age %s, income %.0f." % (api.year, nown, api.age, api.income)
    elif t >= 28800 and not mem.get("rev2"):
        mem["rev2"] = 1
        why = "Scheduled mid-war review year %d: %d provinces, age %s, income %.0f." % (api.year, nown, api.age, api.income)
    elif t > 6000 and api.age in AGES and api.calls_left > 14:
        exp_age = min(6, int(api.year / 250))
        if AGES.index(api.age) + 2 <= exp_age and not mem.get("behind"):
            mem["behind"] = 1
            why = "Austral behind in tech: age %s in year %d." % (api.age, api.year)
    if why:
        if api.call_home(why):
            mem["lastcall"] = t
            api.count("call_home")

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

    try: _research(api)
    except Exception: api.count("res_err")
    try: _depots(api)
    except Exception: api.count("depot_err")
    try: _economy(api)
    except Exception: api.count("eco_err")
    try: _recruit(api, counts, armor_seen, nown, contact)
    except Exception: api.count("rec_err")
    if t % 24 < 6:
        try: _diplo(api)
        except Exception: api.count("dip_err")
        try: _trade(api)
        except Exception: pass
        try: _call(api, nown)
        except Exception: api.count("call_err")

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
        weak = [i for i in ids if byid[i]["str"] < 40 or byid[i]["state"] in ("routing", "shaken")]
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
        if not ids or api.owner_name.get(tgt) in (api.pacts or {}):
            if ids:
                api.cmd("front " + _csv(ids))
                for i in ids: inop.discard(i)
            del ops[tk]; taken.discard(tgt)
            continue
        if pr.get("owner") == "me" and tgt not in api.enemy:
            api.count("op_taken")
            api.cmd("front " + _csv(ids))
            for i in ids: inop.discard(i)
            del ops[tk]; taken.discard(tgt)
            continue
        tot = sum(byid[i]["str"] for i in ids)
        if tot < 0.6 * op.get("s0", tot):
            fails[str(tgt)] = t
            api.count("op_failed")
            api.cmd("front " + _csv(ids))
            for i in ids: inop.discard(i)
            del ops[tk]; taken.discard(tgt)
            continue
        ph = op["ph"]
        drop = False
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
            if len(at) >= 0.85 * len(ids) or (t - op["t0"] > 100 and len(at) >= 8):
                r = api.cmd("prepare %s P%d" % (_csv(at), tgt))
                if r.startswith("ok"):
                    op["ph"] = "p"; op["tp"] = t
                    late = [i for i in ids if i not in at]
                    if late:
                        api.cmd("front " + _csv(late))
                        for i in late: inop.discard(i)
                    op["u"] = at
                else:
                    drop = True
            elif t - op["t0"] > 160:
                drop = True
        elif ph == "p":
            bon = sum(byid[i].get("bonus", 0) for i in ids) / float(len(ids))
            rdy = sum(byid[i]["rdy"] for i in ids) / float(len(ids))
            e = api.enemy.get(tgt)
            waited = t - op.get("tp", t)
            dirs = len(set(us.get(str(i), op["stage"]) for i in ids))
            p = _pwin(api, tgt, tot, rdy, bon, _heavy(byid, ids), dirs)
            go = False
            if not e and waited >= 12 and rdy >= 60: go = True
            elif bon >= 45 and rdy >= 80 and p >= 0.72: go = True
            elif waited >= 200:
                if p >= 0.72 and rdy >= 75: go = True
                else:
                    fails[str(tgt)] = t
                    drop = True
            if go:
                api.count("op_launch")
                mv = [i for i in ids if byid[i]["type"] not in ("art", "rkt")]
                hd = [i for i in ids if byid[i]["type"] in ("art", "rkt")]
                if not mv: mv = ids; hd = []
                api.cmd("move %s P%d" % (_csv(mv), tgt))
                if hd: api.cmd("hold " + _csv(hd))
                op["ph"] = "a"; op["lt"] = t
        elif ph == "a":
            if t - op.get("lt", t) > 96:
                fails[str(tgt)] = t
                drop = True
        if drop:
            api.cmd("front " + _csv(ids))
            for i in ids: inop.discard(i)
            del ops[tk]; taken.discard(tgt)

    comb = [u for u in units if u["type"] != "rec"]
    maxops = min(5, len(comb) // 100)
    budget = int(len(comb) * 0.3) - len(inop)
    if contact and len(ops) < maxops and t % 12 < 6 and budget > 10:
        cands = _targets(api, list(api.border.keys()), taken)
        pool = [u for u in comb if _free(api, u, inop)]
        tries = 0
        usedp = {}
        for sc, tgt, b in cands:
            if len(ops) >= maxops or tries >= 5 or len(pool) < 8 or budget < 10: break
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
                if u["prov"] == api.capital and cnt.get(api.capital, 0) <= 6: continue
                ds.append((d, u["id"], u))
            ds.sort()
            pick = []; s = 0.0
            lim = min(200, budget)
            loc = dict(usedp)
            for d, i, u in ds:
                if s >= need or len(pick) >= lim: break
                p0 = u["prov"]
                if p0 in api.border and loc.get(p0, 0) + 1 > 0.5 * cnt.get(p0, 0): continue
                loc[p0] = loc.get(p0, 0) + 1
                pick.append(u); s += u["str"]
            if s < need or len(pick) < 8:
                api.count("cand_short"); continue
            ids = [u["id"] for u in pick]
            hv = _heavy(byid, ids)
            f = provs.get(tgt, {}).get("fort", 0) or 0
            if f >= 1 and hv < 0.25 and any(k in (api.can_raise or []) for k in ("art", "eng")): continue
            if len(sts) > 1 and len(pick) < 10: sts = sts[:1]
            if _pwin(api, tgt, s, 80, 45, hv, len(sts)) < 0.75:
                api.count("cand_lowp"); continue
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
        try: _refit(api, inop)
        except Exception: pass

    recpost = mem.setdefault("recpost", {})
    for k in list(recpost.keys()):
        if int(k) not in byid or str(recpost[k]) not in ops:
            del recpost[k]
    covered = set(recpost.values())
    needs = [ops[k]["tgt"] for k in ops if ops[k]["tgt"] not in covered]
    nexp = sum(1 for u in comb if u.get("expand"))
    cap_exp = len(comb) if not contact else int(len(comb) * 0.5)
    nexplore = sum(1 for u in units if u["type"] == "rec" and u.get("explore"))
    rn = []
    if api.neutral_border:
        try: rn = _rich_neutral(api)
        except Exception: rn = []
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
```

```letters
to maghreb: Austral thanks you for the steady peace. We will accept your pact again from hour 0 and welcome oil and steel trades.
to kongo: Austral seeks a lasting pact with Kongo. We will accept any pact you offer and will not attack while it holds.
to sahelia: Austral offers a permanent pact instead of short ones; we accept every pact offer.
to nilotica: Austral wants peace and trade again; any pact you offer will be accepted.
```

```feedback
Useful: a field in api.tree giving the median/most-common age among met factions, so policies can see how far behind they are without guessing from year. Also a "q threats" summary: which met factions border me, their estimated army near my border, and whether we have a pact. The review could show when each depot loss happened relative to who attacked (which faction took it).
```

REVIEW: standard