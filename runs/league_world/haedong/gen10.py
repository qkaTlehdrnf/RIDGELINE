def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

def _tdef(pr):
    t = str(pr.get("terrain", "p"))[:1]
    return {"p": 1.0, "f": 1.25, "h": 1.5, "m": 2.0}.get(t, 1.0)

def _pwin(api, att, dfn, pr, bonus, rdy, heavy, dirs):
    md = api.model or {}
    w = md.get("w"); mu = md.get("mean"); sd = md.get("std")
    if not w or not mu or not sd:
        return 1.0 if att > 2.5 * dfn + 50 else 0.0
    x = [math.log((att + 1.0) / (dfn + 1.0)), _tdef(pr), float(pr.get("fort", 0) or 0),
         1.0 if pr.get("city") else 0.0, bonus, rdy, heavy, float(dirs)]
    z = md.get("b", 0.0)
    for i in range(min(len(w), len(x))):
        s = sd[i] if sd[i] else 1.0
        z += w[i] * (x[i] - mu[i]) / s
    return _sig(z)

def _net(api):
    b = api.budget or {}
    n = b.get("net")
    if n is None: n = api.income
    return n or 0

def _afford(api, typ, n=1):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if api.res - c.get("res", 0) * n < 400: return False
    if api.mp < c.get("mp", 0) * n + 10: return False
    for k in ("steel", "oil", "rare"):
        if c.get(k, 0) * n > st.get(k, 0): return False
    return True

def _recruit(api, m):
    units = api.units
    n = len(units)
    b = api.budget or {}
    inc = float(b.get("income", 0) or 0)
    upk = float(b.get("upkeep_units", 0) or 0)
    own = sum(1 for p in api.provs.values() if p.get("owner") == "me")
    if n > 40:
        a = m.get("army0") or {}
        tot = max(1, a.get("n", n))
        if a.get("dry", 0) / float(tot) > 0.08 or a.get("spent", 0) / float(tot) > 0.25:
            api.count("recruit_blocked"); return
        lim = 0.55 if _net(api) > 10 else 0.35
        if inc > 0 and upk > lim * inc:
            api.count("recruit_blocked_upkeep"); return
        if _net(api) < 8 and api.res < 2500:
            api.count("recruit_blocked_net"); return
        if n > max(200, own * 18) or n > 6000:
            api.count("recruit_blocked_cap"); return
    can = set(api.can_raise or [])
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    land = max(1, n)
    want = []
    if cnt.get("rec", 0) < 5: want.append("rec")
    shares = [("art", 0.12), ("arm", 0.10), ("atg", 0.05), ("cav", 0.08), ("grn", 0.08),
              ("eng", 0.03), ("mtn", 0.05), ("mec", 0.06), ("rkt", 0.04)]
    if n > 15:
        for typ, sh in shares:
            if typ in can and cnt.get(typ, 0) < land * sh:
                if typ == "cav" and "arm" in can: continue
                want.append(typ)
    want.append("inf")
    k = 0
    for typ in want:
        if typ not in can: continue
        while k < 3 and _afford(api, typ):
            r = api.cmd("recruit %s 1" % typ)
            if not str(r).startswith("ok"): break
            k += 1
            api.count("recruit_" + typ)
            if typ != "inf": break
        if k >= 3: break

def _assign(api, m):
    ops_ids = set()
    for o in m["ops"].values():
        ops_ids.update(o["ids"])
    nexp = sum(1 for u in api.units if u.get("explore"))
    nex = sum(1 for u in api.units if u.get("expand"))
    for u in api.units:
        if u.get("dom", 0) != 0: continue
        if u["id"] in ops_ids: continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("path"): continue
        if u.get("plan", -1) != -1: continue
        if u.get("state") == "refitting": continue
        if u["type"] == "rec":
            if api.unexplored and nexp < 4:
                api.cmd("explore %d" % u["id"]); nexp += 1
            else:
                api.cmd("front %d" % u["id"])
        elif u["type"] in ("inf", "cav", "mot", "mtn") and api.neutral_border and nex < 70:
            api.cmd("expand %d" % u["id"]); nex += 1
        else:
            api.cmd("front %d" % u["id"])

def _hostile(api, prov):
    name = api.owner_name.get(prov)
    if name and name in api.pacts: return False
    return True

def _ops(api, m):
    t = api.t
    byid = {u["id"]: u for u in api.units}
    provs = api.provs
    done = []
    for tgt, o in m["ops"].items():
        pr = provs.get(tgt, {})
        ids = [i for i in o["ids"] if i in byid]
        o["ids"] = ids
        if pr.get("owner") == "me" or not ids or t - o["start"] > 120 or not _hostile(api, tgt):
            done.append(tgt); continue
        if not o.get("go"):
            bon = [byid[i].get("bonus", 0) for i in ids]
            avg = sum(bon) / max(1, len(bon))
            if t - o["start"] >= 42 or (t - o["start"] >= 24 and avg >= 35) or o.get("empty"):
                api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgt))
                o["go"] = t
                api.count("launch")
        elif t - o["go"] > 72:
            done.append(tgt)
    for tgt in done:
        o = m["ops"].pop(tgt)
        ids = [i for i in o["ids"] if i in byid]
        if ids:
            api.cmd("front %s" % ",".join(str(i) for i in ids))
        if provs.get(tgt, {}).get("owner") == "me":
            api.count("op_won")
        else:
            api.count("op_ended")

    if len(m["ops"]) >= 3 or (t // 6) % 2 != 1: return
    if len(api.units) < 15: return
    used = set()
    for o in m["ops"].values(): used.update(o["ids"])
    byprov = {}
    recs = []
    for u in api.units:
        if u.get("dom", 0) != 0: continue
        if u["id"] in used or u["type"] == "mil": continue
        if u["type"] == "rec":
            if not u.get("explore"): recs.append(u)
            continue
        if u["str"] < 60 or u["rdy"] < 45 or u.get("fighting"): continue
        byprov.setdefault(u["prov"], []).append(u)
    best = None
    for bp in api.border:
        pr = provs.get(bp)
        if not pr: continue
        for nb in pr.get("nbrs", []):
            tp = provs.get(nb)
            if not tp or tp.get("owner") != "enemy" or nb in m["ops"]: continue
            if not _hostile(api, nb): continue
            e = api.enemy.get(nb)
            dstr = float(e["str"]) if e else 0.0
            if not e and not tp.get("visible"): continue
            att = 0.0; rd = 0.0; hv = 0; nn = 0; dirs = 0; pick = []
            for ap in tp.get("nbrs", []):
                if provs.get(ap, {}).get("owner") != "me": continue
                us = byprov.get(ap, [])
                if not us: continue
                us = sorted(us, key=lambda x: -x["str"])
                take = us[:max(1, (len(us) * 2) // 3)] if len(us) > 1 else us
                if len(us) == 1 and dstr > 0: continue
                dirs += 1
                for u in take:
                    pick.append(u["id"]); att += u["str"]; rd += u["rdy"]; nn += 1
                    if u["type"] in ("art", "eng", "arm", "rkt", "hvt"): hv += 1
            if not pick: continue
            if dstr <= 0:
                sc = 5.0 + (tp.get("y", 0) or 0)
                if best is None or sc > best[0]:
                    best = (sc, nb, pick[:3], True)
                continue
            if att < 1.6 * dstr: continue
            p = _pwin(api, att, dstr * _tdef(tp) * 1.1, tp, 0.45, rd / nn / 100.0, hv / float(nn), dirs)
            if p < 0.40: continue
            sc = p * 4 + (tp.get("y", 0) or 0) * 0.3 + (3 if tp.get("city") else 0)
            if best is None or sc > best[0]:
                best = (sc, nb, pick, False)
    if best:
        _, tgt, ids, empty = best
        sel = ",".join(str(i) for i in ids)
        if empty:
            api.cmd("move %s P%d" % (sel, tgt))
            m["ops"][tgt] = {"start": api.t, "ids": ids, "go": api.t, "empty": True}
        else:
            api.cmd("prepare %s P%d" % (sel, tgt))
            m["ops"][tgt] = {"start": api.t, "ids": ids, "go": 0}
            tp = provs.get(tgt, {})
            spot = None
            for ap in tp.get("nbrs", []):
                if provs.get(ap, {}).get("owner") == "me":
                    spot = ap; break
            if spot is not None and recs:
                r = recs.pop()
                api.cmd("move %d P%d" % (r["id"], spot))
                api.count("rec_to_op")
        api.count("op_start")

def _diplo(api, m):
    for o in api.offers_in:
        k = o.get("kind")
        if k in ("pact", "alliance"):
            api.cmd("accept %d" % o["id"]); api.count("acc_pact"); continue
        yg = o.get("you_give", {}) or {}; tg = o.get("they_give", {}) or {}
        if any(str(x).startswith("P") for x in yg):
            api.cmd("reject %d" % o["id"]); continue
        val = {"res": 1, "mp": 2, "steel": 4, "oil": 5, "rare": 3, "coal": 4, "rubber": 4}
        give = sum(val.get(a, 3) * float(b) for a, b in yg.items() if not str(a).startswith("P"))
        get = sum(val.get(a, 3) * float(b) for a, b in tg.items() if not str(a).startswith("P"))
        ok = get > give * 1.05
        for a, b in yg.items():
            have = api.res if a == "res" else api.stock.get(a, 0)
            if have < float(b) * 2: ok = False
        api.cmd(("accept %d" if ok else "reject %d") % o["id"])
    if (api.t // 6) % 8 != 2: return
    sent = m.setdefault("pact_sent", {})
    pw = api.powers or {}
    cand = []
    for f in api.met:
        if f in api.pacts or api.t - sent.get(f, -999) < 200: continue
        land = (pw.get(f, {}) or {}).get("land", 0) or 0
        cand.append((-land, f))
    cand.sort()
    for _, f in cand[:2]:
        api.cmd("offer %s pact" % f); sent[f] = api.t
        api.cmd("say %s Haedong seeks quiet borders and fair trade. A pact serves us both." % f)
    if (api.t // 6) % 32 == 2:
        st = api.stock
        fs = list(api.pacts.keys())[:2]
        for f in fs:
            if st.get("rare", 0) > 400:
                api.cmd("offer %s trade 60 rare for 80 coal" % f)
                api.count("trade_offer")
            if st.get("steel", 0) > 3000 and st.get("coal", 0) < 500:
                api.cmd("offer %s trade 150 steel for 120 coal" % f)
                api.count("trade_offer")

def _depots(api, m):
    deps = api.depots or {}
    if not deps: return
    for p, d in deps.items():
        if d.get("opens_in", 0) > 0: continue
        w = max(1, int(round(d.get("load", 1) or 1)))
        if abs(w - (d.get("weight", 1) or 1)) > max(3, w * 0.3):
            api.cmd("depot P%d %d" % (p, w))
    over = False
    for p, d in deps.items():
        cap = d.get("capacity", 30) or 30
        if (d.get("load", 0) or 0) > 0.85 * cap: over = True
    opening = any((d.get("opens_in", 0) or 0) > 0 for d in deps.values())
    if not over or opening or len(deps) >= 8 or api.res < 450: return
    pts = [(api.provs.get(p, {}).get("x", 0), api.provs.get(p, {}).get("y0", 0)) for p in deps]
    best = None
    for i, p in api.provs.items():
        if p.get("owner") != "me" or not p.get("supplied") or i in deps: continue
        if p.get("harsh"): continue
        d = min((p.get("x", 0) - x) ** 2 + (p.get("y0", 0) - y) ** 2 for x, y in pts)
        sc = d * (2.0 if p.get("city") else 1.0)
        if i in api.border: sc *= 0.5
        if best is None or sc > best[0]: best = (sc, i, d)
    if best and best[2] > 150:
        if str(api.cmd("depot P%d" % best[1])).startswith("ok"):
            api.count("depot")

PRIO = {"roads": 9, "crop_rotation": 9, "banking": 9, "steam_power": 9, "railways": 8,
        "iron_working": 7, "pikes_crossbows": 7, "matchlock": 7, "rifling": 8, "machine_guns": 8,
        "assault_rifles": 8, "masonry": 6, "castles": 5, "siege_engines": 6, "gunpowder": 6,
        "steel_guns": 6, "heavy_artillery": 6, "combustion": 5, "tanks": 5, "anti_tank_guns": 5,
        "mechanisation": 5, "horse_riding": 4, "stirrup": 3, "dragoons": 3, "grenadiers": 4,
        "field_engineering": 4, "hillmen": 3, "trebuchet": 4, "rocket_artillery": 4,
        "heavy_armour": 4, "composite_armour": 4, "flight": 3, "jet_engines": 3, "rocketry": 3,
        "satellites": 3, "galleys": 2, "sailing": 2, "navigation": 2}

LINES = ["logistics", "farming", "medicine", "industry", "inf.weapons", "inf.protection",
         "conscription", "discipline", "art.weapons", "staffwork", "mining", "drill", "fieldworks",
         "refining", "drilling"]

def _research(api, m):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    tree = api.tree or {}
    net = _net(api)
    cands = []
    for d, tr in tree.items():
        if not tr or tr.get("status") != "open" or d in busy: continue
        if tr.get("age") == "space" and d not in ("rocketry", "satellites"): continue
        need = tr.get("res_now") or (tr.get("cost") or {}).get("res", 99999)
        seep = float(tr.get("seeped", 0) or 0)
        if seep > 0.9: continue  # it will arrive by itself soon
        sc = PRIO.get(d, 2) / (1.0 + need / 2000.0)
        cands.append((-sc, d, need))
    cands.sort()
    for _, d, need in cands[:3]:
        if len(busy) >= 2: return
        if api.res - need >= 500 and (net > 0 or api.res - need > 3000):
            if str(api.cmd("research %s" % d)).startswith("ok"):
                api.count("disc"); busy.add(d)
    if len(busy) >= 2 or api.res < 800 or net < 5: return
    for line in LINES:
        tc = api.tech.get(line)
        if not tc or tc.get("status") != "open": continue
        if line in busy: continue
        cost = tc.get("cost") or {}
        ok = True
        for k, v in cost.items():
            have = api.res - 600 if k == "res" else api.stock.get(k, 0)
            if have < v: ok = False
        if ok and str(api.cmd("research %s" % line)).startswith("ok"):
            api.count("research_line"); return

def _refit(api, m):
    if (api.t // 6) % 4 != 1: return
    if api.res < 1200 or not api.old_units: return
    provs = api.provs
    border = api.border or {}
    k = 0
    rcm = api.refit_cost or {}
    for u in api.units:
        if k >= 25: break
        if not u.get("old") or u.get("fighting") or not u.get("supplied"): continue
        if u.get("at_sea"): continue
        pr = provs.get(u.get("prov"))
        if not pr or pr.get("owner") != "me" or not pr.get("supplied"): continue
        if u.get("prov") in border: continue
        if u["rdy"] < 55 or u.get("state") in ("assault", "defending", "routing", "refitting"): continue
        rc = rcm.get(u["type"]) or {}
        if any(api.stock.get(x, 0) < rc.get(x, 0) for x in ("steel", "oil", "rare")): continue
        if api.res - rc.get("res", 0) < 1000: break
        r = api.cmd("refit %d" % u["id"])
        if str(r).startswith("ok"):
            k += 1; api.count("refit")
        else:
            api.count("refit_fail")
    # rotate a few old border units back so they can be refitted
    if k < 5 and api.res > 3000 and (api.t // 6) % 16 == 1:
        cap = api.capital
        moved = 0
        for u in api.units:
            if moved >= 10: break
            if not u.get("old") or u.get("fighting") or u.get("path") or u.get("dom", 0) != 0: continue
            if u.get("prov") not in border: continue
            if u["type"] == "rec": continue
            n_here = sum(1 for x in api.units if x.get("prov") == u.get("prov"))
            if n_here < 30: continue
            if cap is not None:
                api.cmd("move %d P%d" % (u["id"], cap)); moved += 1
                api.count("rotate_refit")

def _econ(api, m):
    if (api.t // 6) % 4 != 3: return
    try:
        _depots(api, m)
    except Exception:
        api.count("err_depots")
    eco = api.economy or {}
    works = eco.get("works", []) or []
    busy = set((w[0], w[1]) for w in works)
    nw = len(works)
    if nw < 4 and api.res > 500 and _net(api) > 3:
        for p in (eco.get("provs") or [])[:15]:
            if ("dev", p["prov"]) in busy: continue
            if p.get("can_dev") and p.get("dev", 0) + 1 <= p.get("room", 0):
                if str(api.cmd("develop P%d" % p["prov"])).startswith("ok"):
                    api.count("develop"); nw += 1; break
    if nw < 4 and api.res > 600:
        cand = [d for d in (api.depots or {})] + [p["prov"] for p in (eco.get("provs") or [])[:6]]
        rows = dict((p["prov"], p) for p in (eco.get("provs") or []))
        for pid in cand:
            if ("infra", pid) in busy: continue
            r = rows.get(pid)
            inf = r.get("infra", 0) if r else (api.provs.get(pid, {}).get("infra", 0) or 0)
            if inf >= 3: continue
            if r is not None and not r.get("can_infra"): continue
            if api.stock.get("steel", 0) < 6 * (inf + 1) + 10: continue
            if str(api.cmd("build P%d" % pid)).startswith("ok"):
                api.count("build"); break

def _home(api, m):
    if api.calls_left <= 0: return
    net = _net(api)
    if net < 0:
        m["neg"] = m.get("neg", 0) + 6
    else:
        m["neg"] = 0
    calls = len(api.calls or [])
    if calls == 0 and api.t >= 28800:
        api.call_home("Mid-war review (year ~1000): check army size vs income, refit progress, research, whether any border is worth attacking.")
    elif calls <= 1 and m.get("neg", 0) >= 240 and api.t > 2000:
        if api.call_home("Net income negative for 10 days; res %d, units %d. Rebalance upkeep." % (int(api.res), len(api.units))):
            m["neg"] = 0

def tick(api):
    m = api.mem
    if "ops" not in m:
        m["ops"] = {}
    try:
        m["army0"] = api.army(0)
    except Exception:
        m["army0"] = {}
    for f in (_diplo, _research, _refit, _recruit, _ops, _assign, _econ, _home):
        try:
            f(api, m)
        except Exception:
            api.count("err_" + f.__name__)
