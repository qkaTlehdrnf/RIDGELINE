Last war we finished 1st (175 provinces, the largest army), so I am keeping the strategy: peace with every neighbour, steady trade, fast expansion with cavalry and infantry, then an artillery-heavy front that only attacks when the odds are strong.

The clear weakness was supply. We ended with a single depot serving 175 provinces at load 139 against a capacity of 60. Its output fell to x0.43, and 29% of the army was short of supplies. New depots were apparently never opened. The likely cause is that recruitment keeps the treasury near its reserve, so the depot check (150 cost plus 120 spare) rarely passed on its one daily slot.

Changes:
- **Depot check:** it now runs twice a day. It needs only the depot cost plus 30 spare.
- **Recruitment pause:** when the depot is overloaded, recruitment stops for a few hours so the money builds up.
- **Distance threshold:** a new depot can now sit closer to existing ones (more than 12 cells away instead of 15).
- **Tallies:** I added counters for why depots fail to open, so the next review shows it.

Everything else is unchanged.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

RES_ORDER = ["farming", "logistics", "staffwork", "medicine", "art.weapons", "inf.protection", "conscription",
             "discipline", "industry", "inf.weapons", "drill", "mining", "drilling",
             "refining", "fieldworks", "art.protection", "grn.weapons", "art.mobility", "inf.mobility",
             "cav.mobility", "grn.protection", "cav.weapons", "atg.weapons"]

def _afford(api, cost):
    if not cost: return False
    st = api.stock
    for k, v in cost.items():
        if st.get(k, 0) < v: return False
    return True

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    lines = list(RES_ORDER) + sorted(k for k in api.tech.keys() if k not in RES_ORDER)
    for line in lines:
        tl = api.tech.get(line)
        if not tl or line in busy or tl.get("status") != "open": continue
        c = tl.get("cost")
        if c and _afford(api, c) and api.stock.get("res", 0) - c.get("res", 0) > 60:
            r = api.cmd("research " + line)
            if r.startswith("ok"):
                busy.add(line)
                if len(busy) >= 2: return

def _can_build(api, typ, reserve, mpres):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) - c.get("res", 0) < reserve: return False
    if api.mp < c.get("mp", 0) + mpres: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0): return False
    return True

def _neutrals(api, m):
    if api.t - m.get("nt_t", -99) < 6 and "nt" in m: return m["nt"]
    out = []
    for i, pr in api.provs.items():
        if pr.get("owner") == "neutral" and not pr.get("harsh"):
            out.append(i)
    m["nt"] = out; m["nt_t"] = api.t
    return out

def _overloaded(api):
    deps = api.depots or {}
    for d in deps.values():
        cap = d.get("capacity", 30) or 30
        if (d.get("load", 0) or 0) > 0.85 * cap: return True
    return False

def _depots(api, m):
    m["dep_save"] = False
    if api.t < 24: return
    deps = api.depots or {}
    if not deps or len(deps) >= 12: return
    for d in deps.values():
        if (d.get("opens_in", 0) or 0) > 0: return
    if not _overloaded(api): return
    cost = api.depot_cost or 150
    if api.stock.get("res", 0) < cost + 30:
        m["dep_save"] = True
        api.count("depot_wait_res")
        return
    if api.t % 12 != 9: return
    border = api.border or {}
    pts = []
    for p in deps:
        pr = api.provs.get(p)
        if pr: pts.append((pr.get("x", 0) or 0, pr.get("y0", 0) or 0))
    best = None
    for i, pr in api.provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied") or pr.get("harsh"): continue
        if i in deps or i in border: continue
        risky = False
        for n in pr.get("nbrs", []):
            if n in border or api.provs.get(n, {}).get("owner") == "enemy": risky = True; break
        if risky: continue
        x = pr.get("x", 0) or 0; y = pr.get("y0", 0) or 0
        dmin = min(math.sqrt((x - a) ** 2 + (y - b) ** 2) for a, b in pts) if pts else 100
        sc = dmin * (1.6 if pr.get("city") else 1.0)
        if best is None or sc > best[0]: best = (sc, i)
    if best and best[0] > 12:
        r = api.cmd("depot P%d" % best[1])
        if r.startswith("ok"): api.count("depot_opened")
        else: api.count("depot_rejected")
    else:
        api.count("depot_no_site")

def _recruit(api, m, neut):
    inc = api.income
    if inc <= 0.5 and api.t > 48: return
    if m.get("dep_save"): return
    t = api.t
    nrec = 0
    for u in api.units:
        if u["type"] == "rec": nrec += 1
    armour_seen = m.get("armour", False)
    if not armour_seen:
        for e in api.enemy.values():
            ty = e.get("types") or {}
            if isinstance(ty, dict) and (ty.get("arm", 0) or ty.get("hvt", 0) or ty.get("mec", 0)):
                armour_seen = True; m["armour"] = True; break
    nu = len(api.units)
    reserve = 20 + 0.05 * nu
    if t > 200: reserve += 150
    mpres = 20 + 0.08 * nu
    built = 0
    cap = 20 + int(max(0, api.stock.get("res", 0) - 300) / 60)
    if cap > 40: cap = 40
    steel = api.stock.get("steel", 0)
    reccap = 12 if t < 300 else 14
    expanding = (api.neutral_border or len(neut) > 0) and t < 1000
    while built < cap:
        rc = m.get("rc", 0)
        if nrec < reccap and api.unexplored:
            typ = "rec"
        elif expanding:
            typ = "cav" if rc % 4 != 3 else "inf"
        else:
            k = rc % 10
            if armour_seen and k == 9: typ = "atg"
            elif k in (1, 4, 7, 5): typ = "art"
            elif k in (3, 8) and steel > 80: typ = "grn"
            else: typ = "inf"
        if not _can_build(api, typ, reserve, mpres):
            if typ != "inf" and _can_build(api, "inf", reserve, mpres): typ = "inf"
            else: break
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): break
        m["rc"] = m.get("rc", 0) + 1
        if typ == "rec": nrec += 1
        built += 1

def _refit(api, m, inatk):
    if api.t % 24 != 3: return
    if api.stock.get("res", 0) < 700: return
    border = api.border or {}
    ids = []
    for u in api.units:
        if not u.get("old") or u.get("fighting") or u["id"] in inatk: continue
        if u["type"] not in ("art", "grn", "inf"): continue
        if u["prov"] in border or not u.get("supplied", True): continue
        if u["state"] in ("routing", "shaken", "refitting", "moving"): continue
        ids.append(u["id"])
        if len(ids) >= 20: break
    if ids:
        api.cmd("refit " + ",".join(str(i) for i in ids))

def _diplo(api, m):
    t = api.t
    met = list(api.met or [])
    pacts = api.pacts or {}
    for o in api.offers_in or []:
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
        elif o.get("kind") == "trade":
            yg = o.get("you_give") or {}
            tg = o.get("they_give") or {}
            ok = True
            val_give = 0.0
            for k, v in yg.items():
                if k in ("res", "mp"): ok = False
                elif api.stock.get(k, 0) < v + 400: ok = False
                val_give += v
            val_get = sum(v * (2.5 if k == "res" else 1.0) for k, v in tg.items())
            if ok and val_get >= val_give * 0.4: api.cmd("accept %s" % o["id"])
            else: api.cmd("reject %s" % o["id"])
    if t % 24 == 6:
        outp = set(o.get("to") for o in (api.offers_out or []) if o.get("kind") == "pact")
        for f in met:
            pa = pacts.get(f)
            if f in outp: continue
            if pa:
                en = pa.get("ends")
                if en is None or en - t > 90: continue
            api.cmd("offer %s pact" % f)
    if t % 48 == 30 and met:
        outt = set(o.get("to") for o in (api.offers_out or []) if o.get("kind") == "trade")
        for f in met:
            if f in outt: continue
            for k in ("rare", "oil", "steel"):
                lim = 300 if k == "rare" else 600
                if api.stock.get(k, 0) > lim + 200:
                    n = 150 if k == "rare" else 250
                    api.cmd("offer %s trade %d %s for %d res" % (f, n, k, 90 if k == "rare" else 100))
                    break
    if not m.get("greet") and met:
        m["greet"] = 1
        for f in met:
            api.cmd("say %s Amazonia keeps every pact it signs. Peace and fair trade with all neighbours." % f)

TDF = {"m": 2.0, "h": 1.5, "f": 1.25}

def _eff_def(pr, d_str, art_share):
    ter = pr.get("terrain", "plain") or "plain"
    tdf = TDF.get(ter[0], 1.0)
    fort = pr.get("fort", 0) or 0
    fort_eff = fort * (1 - 0.6 * art_share)
    return tdf, fort, d_str * tdf * (1 + 0.25 * fort_eff) * (1.25 if pr.get("city") else 1.0)

def _attacks(api, m, byprov, uby):
    atks = m.setdefault("atk", {})
    t = api.t
    provs = api.provs
    pacts = api.pacts or {}
    own = api.owner_name or {}
    busy = set()
    for tg, a in list(atks.items()):
        tgi = int(tg)
        pr = provs.get(tgi)
        ids = [i for i in a["ids"] if i in uby]
        done = (pr and pr.get("owner") == "me") or len(ids) < 3 or own.get(tgi) in pacts
        if a.get("launch") is not None:
            el = t - a["launch"]
            if el > 72: done = True
            elif el >= 18:
                avs = sum(uby[i]["str"] for i in ids) / max(1, len(ids))
                if avs < 35: done = True
        elif t - a["start"] > 120: done = True
        if done:
            if ids: api.cmd("front " + ",".join(str(i) for i in ids))
            del atks[tg]; continue
        busy.update(ids)
        if a.get("launch") is None:
            pool = [uby[i] for i in ids]
            n = float(len(pool))
            avgb = sum(u.get("bonus", 0) for u in pool) / n
            avgr = sum(u.get("rdy", 0) for u in pool) / n
            ready = (avgb >= 45 and avgr >= 65) or (t - a["start"] >= 90 and avgr >= 55 and avgb >= 30)
            if not ready: continue
            e = api.enemy.get(tgi)
            ok = True
            if e and pr:
                art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / n
                d = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                _, fort, ed = _eff_def(pr, d, art)
                a_str = sum(u["str"] * (0.4 + 0.6 * u["rdy"] / 100.0) for u in pool)
                a_str *= 1 + avgb / 100.0
                if a_str < 2.2 * (ed + 1): ok = False
            if ok:
                api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgi))
                a["launch"] = t
                api.count("assault_launched")
            else:
                del atks[tg]
    maxa = 2 + len(api.units) // 300
    if len(atks) >= maxa: return
    mdl = api.model or {}
    cands = []
    caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
    for p, e in api.enemy.items():
        pr = provs.get(p)
        if not pr or str(p) in atks: continue
        ow = own.get(p)
        if ow is None or ow in pacts: continue
        fort = pr.get("fort", 0) or 0
        adj = [n for n in pr.get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
        if not adj: continue
        pool = []; dirs = 0; elev_pen = 0
        for n in adj:
            here = byprov.get(n, [])
            us = [u for u in here if u["id"] not in busy and u["type"] not in ("rec", "mil")
                  and u["str"] >= 75 and u.get("rdy", 0) >= 55 and u.get("mor", 70) >= 45
                  and u["state"] not in ("routing", "shaken", "refitting")]
            if not us: continue
            us.sort(key=lambda u: -u["str"])
            keep = 1 if len(here) <= len(us) else 0
            take = us[keep:]
            if take:
                dirs += 1
                elev_pen += max(0, (pr.get("elev", 0) or 0) - (provs.get(n, {}).get("elev", 0) or 0))
            pool += take
        if len(pool) < 6: continue
        d_str = e.get("str", 0) or 0
        if not e.get("exact"): d_str *= 1.3
        art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / float(len(pool))
        if fort >= 3 and art < 0.4: continue
        if fort >= 2 and art < 0.3: continue
        tdf, fort, ed = _eff_def(pr, d_str, art)
        rdy = sum(u["rdy"] for u in pool) / (100.0 * len(pool))
        a_eff = sum(u["str"] for u in pool) * (0.4 + 0.6 * rdy) * 1.45
        if elev_pen and dirs: a_eff *= 0.9 ** (elev_pen / float(dirs))
        if a_eff < 3.0 * (ed + 1): continue
        score = 0.6
        if mdl.get("w"):
            heavy = sum(1 for u in pool if u["type"] in ("art", "eng", "arm")) / float(len(pool))
            a_str = sum(u["str"] for u in pool)
            x = [math.log((a_str + 1) / (d_str + 1)), tdf, fort, 1 if pr.get("city") else 0,
                 0.45, 0.7, heavy, dirs]
            z = mdl["b"]
            for i in range(len(x)):
                z += mdl["w"][i] * (x[i] - mdl["mean"][i]) / (mdl["std"][i] or 1)
            score = _sig(z)
            if score < 0.45: continue
        val = (pr.get("y", 0) or 0) + 3 * (1 if pr.get("city") else 0) + pr.get("steel", 0) + pr.get("oil", 0) + pr.get("rare", 0)
        if p in caps: val += 50
        cands.append((score + 0.02 * val + 0.12 * dirs, p, pool))
    cands.sort(key=lambda c: -c[0])
    for sc, p, pool in cands:
        if len(atks) >= maxa: break
        ids = [u["id"] for u in pool if u["id"] not in busy]
        if len(ids) < 6: continue
        r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in ids), p))
        if r.startswith("ok"):
            atks[str(p)] = {"ids": ids, "start": api.t, "launch": None}
            busy.update(ids)

def _far_targets(api, neut, k):
    cap = api.provs.get(api.capital) or {}
    cx = cap.get("x", 0) or 0; cy = cap.get("y0", 0) or 0
    nb = set(api.neutral_border or [])
    sc = []
    for i in neut:
        pr = api.provs.get(i)
        if not pr: continue
        adj = False
        for n in pr.get("nbrs", []):
            if n in nb: adj = True; break
        v = (pr.get("y", 0) or 0) + 2 * (1 if pr.get("city") else 0) + (pr.get("mp", 0) or 0) * 0.3
        v += 0.5 * (pr.get("steel", 0) + pr.get("oil", 0) + pr.get("rare", 0))
        d = math.sqrt(((pr.get("x", 0) or 0) - cx) ** 2 + ((pr.get("y0", 0) or 0) - cy) ** 2)
        sc.append((v - 0.004 * d + (0 if adj else 0.5), i))
    sc.sort(key=lambda s: -s[0])
    return [i for _, i in sc[:k]]

def tick(api):
    m = api.mem
    byprov = {}; uby = {}
    for u in api.units:
        byprov.setdefault(u["prov"], []).append(u); uby[u["id"]] = u
    try:
        _diplo(api, m)
    except Exception:
        pass
    _research(api)
    try:
        _depots(api, m)
    except Exception:
        m["dep_save"] = False
    neut = _neutrals(api, m)
    _recruit(api, m, neut)
    inatk = set()
    for a in m.get("atk", {}).values(): inatk.update(a["ids"])
    _refit(api, m, inatk)
    expanding = bool(api.neutral_border or neut)
    exp_ids = []; front_ids = []; explore_ids = []
    for u in api.units:
        if u["id"] in inatk: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u["state"] == "refitting": continue
        if u["type"] == "rec":
            if api.unexplored: explore_ids.append(u["id"])
            continue
        if expanding and u["type"] in ("cav", "inf", "mot", "mtn"):
            exp_ids.append(u["id"])
        else:
            front_ids.append(u["id"])
    if explore_ids: api.cmd("explore " + ",".join(str(i) for i in explore_ids))
    if exp_ids:
        if neut and len(exp_ids) >= 3:
            tg = _far_targets(api, neut, max(1, len(exp_ids) // 4))
            j = 0
            for p in tg:
                grp = exp_ids[j:j + 2]
                if len(grp) < 2: break
                r = api.cmd("expand %s P%d" % (",".join(str(i) for i in grp), p))
                if r.startswith("ok"): j += 2
            exp_ids = exp_ids[j:]
        if exp_ids: api.cmd("expand " + ",".join(str(i) for i in exp_ids))
    if front_ids: api.cmd("front " + ",".join(str(i) for i in front_ids))
    if api.t >= 150 and api.enemy:
        _attacks(api, m, byprov, uby)
```

```letters
to anahuac: Amazonia renews its pact and keeps it as before. Steel and oil trades will continue whenever we have surplus.
to granada: Thank you for fair trading last war. Amazonia will again offer pact and steel/oil for res; we keep our word.
to andea: Our pact held all war; Amazonia will keep it again. Trade offers stay open if you want them.
to platina: Lasting peace accepted. Amazonia will offer the pact at once and keep it; fair trades as before.
```

REVIEW: standard