Last war I finished 8th of 31 with 173 provinces. The army wore itself out: readiness fell from 88 to 40 and units short of supplies rose to 56%. My main depot served 146 provinces at load 94 against capacity 60, so the front starved. No assault on a defended province ever launched, because the bar (2.2:1 and model p ≥ 0.5) was too strict. I also kept recruiting about 990 inf into a starving front.

Changes:
1. **Depots by load.** When a depot runs over 85% of capacity, open a new one in a supplied city far from the existing ones, up to 7. The weight follows the load, so the treasury follows the work.
2. **Recruitment tied to supply.** Recruit only while the army is under 8% dry and under 25% spent. A small minimum force is always kept.
3. **Easier assaults.** Launch at a 1.7:1 ratio and p ≥ 0.42 only against factions without a pact with me, and send a scout next to the target for the larger planning bonus.
4. **Economy.** Build roads in the cities that hold depots, keep developing land, and research a new tech order. Every line is redrawn each war, so last war's dead ends are still worth trying.
5. **Diplomacy.** Keep the pacts, but accept a pact only when it is not with one of the weak neighbours I am attacking.

```python
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

def _afford(api, typ, n=1):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if api.res - c.get("res", 0) * n < 150: return False
    if api.mp < c.get("mp", 0) * n + 10: return False
    for k in ("steel", "oil", "rare"):
        if c.get(k, 0) * n > st.get(k, 0): return False
    return True

def _recruit(api, m):
    units = api.units
    n = len(units)
    if n > 40:
        a = m.get("army0") or {}
        tot = max(1, a.get("n", n))
        if a.get("dry", 0) / float(tot) > 0.08 or a.get("spent", 0) / float(tot) > 0.25:
            api.count("recruit_blocked"); return
        if api.income < 20 and n > 200:
            api.count("recruit_blocked_inc"); return
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    want = []
    if cnt.get("rec", 0) < 4: want.append("rec")
    if n > 12 and cnt.get("art", 0) < n * 0.15: want.append("art")
    if n > 20 and cnt.get("grn", 0) < n * 0.12: want.append("grn")
    if n > 30 and cnt.get("eng", 0) < n * 0.04: want.append("eng")
    want.append("inf")
    k = 0
    for typ in want:
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
        if u["id"] in ops_ids: continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("path"): continue
        if u.get("plan", -1) != -1: continue
        if u["type"] == "rec":
            if api.unexplored and nexp < 3:
                api.cmd("explore %d" % u["id"]); nexp += 1
            else:
                api.cmd("front %d" % u["id"])
        elif u["type"] in ("inf", "cav", "mot") and api.neutral_border and nex < 60:
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
            if t - o["start"] >= 48 or (t - o["start"] >= 24 and avg >= 35) or o.get("empty"):
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
                    if u["type"] in ("art", "eng", "arm"): hv += 1
            if not pick: continue
            if dstr <= 0:
                sc = 5.0 + (tp.get("y", 0) or 0)
                if best is None or sc > best[0]:
                    best = (sc, nb, pick[:3], True)
                continue
            if att < 1.7 * dstr: continue
            p = _pwin(api, att, dstr * _tdef(tp) * 1.1, tp, 0.45, rd / nn / 100.0, hv / float(nn), dirs)
            if p < 0.42: continue
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
            # bring a scout next to the target for the bigger plan bonus
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
    # trade surplus rare for coal/steel with a pact partner
    if api.stock.get("rare", 0) > 400 and (api.t // 6) % 32 == 2:
        for f in list(api.pacts.keys())[:2]:
            api.cmd("offer %s trade 60 rare for 80 coal" % f)
            api.cmd("offer %s trade 60 rare for 60 steel" % f)
            api.count("trade_offer")

def _depots(api, m):
    deps = api.depots or {}
    if not deps: return
    # weights follow load
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
    if not over or opening or len(deps) >= 7 or api.res < 450: return
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

def _econ(api, m):
    if (api.t // 6) % 4 != 3: return
    try:
        _depots(api, m)
    except Exception:
        api.count("err_depots")
    eco = api.economy or {}
    works = eco.get("works", []) or []
    nw = len(works)
    if nw < 3 and api.res > 400 and api.income > 5:
        for p in (eco.get("provs") or [])[:8]:
            if p.get("room", 0) > 0 and api.stock.get("coal", 0) >= 8 * (p.get("dev", 0) + 1):
                if str(api.cmd("develop P%d" % p["prov"])).startswith("ok"):
                    api.count("develop"); nw += 1; break
    if nw < 3 and api.res > 500:
        cand = [d for d in (api.depots or {})] + [p["prov"] for p in (eco.get("provs") or [])[:3]]
        for pid in cand:
            pr = api.provs.get(pid, {})
            inf = 0
            for p in (eco.get("provs") or []):
                if p["prov"] == pid: inf = p.get("infra", 0)
            if inf < 3 and api.stock.get("steel", 0) >= 6 * (inf + 1) + 15:
                if str(api.cmd("build P%d" % pid)).startswith("ok"):
                    api.count("build"); break
    if len(api.research) < 2 and api.res > 300:
        order = ["logistics", "farming", "medicine", "inf.weapons", "industry", "inf.protection",
                 "staffwork", "art.weapons", "discipline", "conscription", "grn.weapons", "mining",
                 "drill", "fieldworks", "refining"]
        for line in order:
            tc = api.tech.get(line)
            if not tc or tc.get("status") != "open": continue
            if any(r[0] == line for r in api.research): continue
            cost = tc.get("cost") or {}
            ok = True
            for k, v in cost.items():
                have = api.res - 200 if k == "res" else api.stock.get(k, 0)
                if have < v: ok = False
            if ok and str(api.cmd("research %s" % line)).startswith("ok"):
                api.count("research"); break

def tick(api):
    m = api.mem
    if "ops" not in m:
        m["ops"] = {}
    try:
        m["army0"] = api.army(0)
    except Exception:
        m["army0"] = {}
    for f in (_diplo, _recruit, _ops, _assign, _econ):
        try:
            f(api, m)
        except Exception:
            api.count("err_" + f.__name__)
```

```letters
to zhongyuan: Haedong offers a lasting pact and fair trade; our rare for your coal or steel.
to siberia: Haedong wants a quiet northern border. Pact until broken, and trade if you have coal or steel.
to yamato: Haedong proposes a standing pact with no end date, so we stop renewing every 240 h.
```

```feedback
Depot load is easy to miss: the only warning that my one depot ran at 94/60 came in the review. A live event when a depot passes capacity would help. Also unclear: whether api.army(0) "dry" counts units or provinces.
```

REVIEW: standard