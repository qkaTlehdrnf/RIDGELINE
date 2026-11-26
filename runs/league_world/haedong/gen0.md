Haedong starts with a defensive doctrine, slow units and a peninsula behind it. So the plan is to grow first and fight only where the numbers clearly favour us.

- **Growth:** scouts explore. Infantry expands into neutral land while any is in reach, then joins the `front` standing order.
- **Recruiting:** a steady mix, mostly infantry with some artillery, assault infantry and scouts. Every purchase is checked against the treasury and stockpiles, keeping a small reserve.
- **Attacks:** limited and prepared, at most two at a time. An attack starts only where nearby fit units have at least 2.2x the visible enemy strength. It also needs at least 0.5 from the fitted assault model, which rewards prepare bonus and attacks from several sides.
  - Units prepare for 24–48 hours, then advance, then rejoin the front.
  - Undefended enemy provinces next to us get small grab parties.
  - Factions we have a pact with are never targeted.
- **Diplomacy:**
  - Accept every pact offer, and offer pacts to the strongest powers we have met so the fights stay on our terms.
  - Accept trades and supplies only if they ask for no land and we get more than we give.
- **Economy:** develop the richest cities and build roads there when the treasury is comfortable. Research farming, industry and logistics first, then weapons, skipping lines we cannot afford. Open a second depot once the land grows.
- **Robustness:** each section runs inside try/except, and the heavy parts run only once a day.

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
    if api.res - c.get("res", 0) * n < 60: return False
    if api.mp < c.get("mp", 0) * n + 10: return False
    for k in ("steel", "oil", "rare"):
        if c.get(k, 0) * n > st.get(k, 0): return False
    return True

def _recruit(api, m):
    units = api.units
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    n = len(units)
    want = []
    if cnt.get("rec", 0) < 3: want.append("rec")
    if n > 12 and cnt.get("art", 0) < n * 0.15: want.append("art")
    if n > 20 and cnt.get("grn", 0) < n * 0.12: want.append("grn")
    if n > 30 and cnt.get("eng", 0) < n * 0.04: want.append("eng")
    want.append("inf")
    k = 0
    for typ in want:
        while k < 4 and _afford(api, typ):
            r = api.cmd("recruit %s 1" % typ)
            if not str(r).startswith("ok"): break
            k += 1
            api.count("recruit_" + typ)
            if typ != "inf": break
        if k >= 4: break

def _assign(api, m):
    ops_ids = set()
    for o in m["ops"].values():
        ops_ids.update(o["ids"])
    nexp = sum(1 for u in api.units if u.get("explore"))
    for u in api.units:
        if u["id"] in ops_ids: continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("path"): continue
        if u.get("plan", -1) != -1: continue
        if u["type"] == "rec":
            if api.unexplored and nexp < 3:
                api.cmd("explore %d" % u["id"]); nexp += 1
            else:
                api.cmd("front %d" % u["id"])
        elif u["type"] in ("inf", "cav", "mot") and api.neutral_border:
            api.cmd("expand %d" % u["id"])
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
            if t - o["start"] >= 48 or (t - o["start"] >= 24 and avg >= 30) or o.get("empty"):
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

    if len(m["ops"]) >= 2 or (t // 6) % 4 != 1: return
    if len(api.units) < 15: return
    used = set()
    for o in m["ops"].values(): used.update(o["ids"])
    byprov = {}
    for u in api.units:
        if u["id"] in used or u["type"] in ("rec", "mil"): continue
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
            if att < 2.2 * dstr: continue
            p = _pwin(api, att, dstr * _tdef(tp) * 1.1, tp, 0.4, rd / nn / 100.0, hv / float(nn), dirs)
            if p < 0.5: continue
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
        api.count("op_start")

def _diplo(api, m):
    for o in api.offers_in:
        k = o.get("kind")
        if k in ("pact", "alliance"):
            api.cmd("accept %d" % o["id"]); api.count("acc_pact"); continue
        yg = o.get("you_give", {}) or {}; tg = o.get("they_give", {}) or {}
        if any(str(x).startswith("P") for x in yg): 
            api.cmd("reject %d" % o["id"]); continue
        val = {"res": 1, "mp": 2, "steel": 4, "oil": 5, "rare": 10, "coal": 3, "rubber": 4}
        give = sum(val.get(a, 3) * float(b) for a, b in yg.items() if not str(a).startswith("P"))
        get = sum(val.get(a, 3) * float(b) for a, b in tg.items() if not str(a).startswith("P"))
        ok = get > give * 1.1
        for a, b in yg.items():
            if api.stock.get(a, api.res if a == "res" else 0) < float(b) * 2: ok = False
        api.cmd(("accept %d" if ok else "reject %d") % o["id"])
    if (api.t // 6) % 8 != 2: return
    sent = m.setdefault("pact_sent", {})
    pw = api.powers or {}
    myland = (pw.get(api.me, {}) or {}).get("land", 0) if isinstance(api.me, str) else 0
    cand = []
    for f in api.met:
        if f in api.pacts or api.t - sent.get(f, -999) < 200: continue
        land = (pw.get(f, {}) or {}).get("land", 0) or 0
        cand.append((-land, f))
    cand.sort()
    for _, f in cand[:2]:
        api.cmd("offer %s pact" % f); sent[f] = api.t
        api.cmd("say %s Haedong seeks quiet borders and fair trade. A pact serves us both." % f)

def _econ(api, m):
    if (api.t // 6) % 4 != 3: return
    eco = api.economy or {}
    works = eco.get("works", []) or []
    if len(works) < 2 and api.res > 450 and api.income > 5:
        for p in (eco.get("provs") or [])[:6]:
            if p.get("room", 0) > 0 and api.stock.get("coal", 0) >= 8 * (p.get("dev", 0) + 1):
                if str(api.cmd("develop P%d" % p["prov"])).startswith("ok"):
                    api.count("develop"); break
    if len(works) < 2 and api.res > 650:
        for p in (eco.get("provs") or [])[:3]:
            if p.get("infra", 0) < 3 and api.stock.get("steel", 0) >= 6 * (p.get("infra", 0) + 1) + 20:
                if str(api.cmd("build P%d" % p["prov"])).startswith("ok"):
                    api.count("build"); break
    if len(api.research) < 2 and api.res > 250:
        order = ["farming", "industry", "logistics", "inf.weapons", "conscription", "art.weapons",
                 "inf.protection", "medicine", "mining", "discipline", "staffwork", "grn.weapons"]
        for line in order:
            tc = api.tech.get(line)
            if not tc or tc.get("status") != "open": continue
            cost = tc.get("cost") or {}
            ok = True
            for k, v in cost.items():
                have = api.res - 150 if k == "res" else api.stock.get(k, 0)
                if have < v: ok = False
            if ok and str(api.cmd("research %s" % line)).startswith("ok"):
                api.count("research"); break
    own = [i for i, p in api.provs.items() if p.get("owner") == "me"]
    if len(api.depots) < 2 and len(own) > 35 and api.res > 500:
        cap = api.provs.get(api.capital, {})
        cx, cy = cap.get("x", 0), cap.get("y0", 0)
        best = None
        for i in own:
            p = api.provs[i]
            if not p.get("city") or not p.get("supplied") or i in api.depots: continue
            d = (p.get("x", 0) - cx) ** 2 + (p.get("y0", 0) - cy) ** 2
            if best is None or d > best[0]: best = (d, i)
        if best and best[0] > 400:
            api.cmd("depot P%d" % best[1]); api.count("depot")

def tick(api):
    m = api.mem
    if "ops" not in m:
        m["ops"] = {}
    for f in (_diplo, _recruit, _ops, _assign, _econ):
        try:
            f(api, m)
        except Exception:
            api.count("err_" + f.__name__)
```

```feedback
A compact per-province "my effective strength vs visible enemy" figure in api would make attack decisions cheaper and less error-prone than re-summing units every tick.
```

REVIEW: Defensive-growth policy: expand/explore early, front for most units, at most two prepared attacks at 2.2x odds plus model check, pacts with the strongest, economy and research when affordable.