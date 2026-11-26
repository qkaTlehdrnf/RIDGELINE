Last war I finished 7th with 154 provinces. My assaults went 0 for 66, and nearly all of them hit level 3-4 forts. My territory stopped growing at day 35, while cascadia, zhongyuan and siberia kept taking the neutral land that was left. I ended with large idle stocks (steel 784, oil 1321, rare 1616) while res, the scarce resource, stayed the bottleneck.

Changes:
1. **Exploring and expanding.** More scouts early (8, then up to 12), and expansion units keep coming as long as any known neutral land exists, not only land next to my border. Every few hours I send groups of expanders toward distant, valuable neutral provinces with `expand P<target>`. This spreads them over several fronts instead of piling onto the nearest land.
2. **Economy.** Surplus steel, oil and rare are traded for res with every faction I have met, not only pact partners. Refit only runs when res is plentiful, so res goes to land and units first.
3. **Attacks.** Fewer and stricter: forts of level 2 or more are skipped unless at least 35% of the attackers are artillery, and launch needs a high prepared bonus. Land counts first in the score, so cheap expansion matters more than costly assaults.
4. **Diplomacy.** Pacts with everyone except one chosen target; I reply to andea's offer.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

RES_ORDER = ["farming", "logistics", "conscription", "staffwork", "art.weapons", "inf.protection", "medicine",
             "industry", "discipline", "inf.weapons", "drill", "mining", "drilling",
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

def _recruit(api, m, neut):
    inc = api.income
    if inc <= 0.5 and api.t > 48: return
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
    reserve = 25 + 0.06 * nu
    mpres = 30 + 0.1 * nu
    built = 0
    cap = 16 + int(max(0, api.stock.get("res", 0) - 300) / 60)
    if cap > 40: cap = 40
    steel = api.stock.get("steel", 0)
    reccap = 8 if t < 200 else 12
    expanding = (api.neutral_border or len(neut) > 0) and t < 1000
    while built < cap:
        rc = m.get("rc", 0)
        if nrec < reccap and api.unexplored:
            typ = "rec"
        elif expanding:
            typ = "cav" if rc % 2 == 0 else "inf"
        else:
            k = rc % 10
            if armour_seen and k == 9: typ = "atg"
            elif k in (1, 4, 7): typ = "art"
            elif k in (3, 8) and steel > 80: typ = "grn"
            elif k == 6 and steel > 400: typ = "grn"
            elif k == 0 and steel > 600: typ = "art"
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
        if u["prov"] in border or not u.get("supplied", True): continue
        if u["state"] in ("routing", "shaken", "refitting", "moving"): continue
        ids.append(u["id"])
        if len(ids) >= 25: break
    if ids:
        api.cmd("refit " + ",".join(str(i) for i in ids))

def _diplo(api, m):
    t = api.t
    met = list(api.met or [])
    pacts = api.pacts or {}
    tgt = m.get("target")
    if tgt is None and t >= 500 and not api.neutral_border and met:
        cnt = {}
        own = api.owner_name or {}
        for p in (api.border or {}):
            pr = api.provs.get(p)
            if not pr: continue
            for n in pr.get("nbrs", []):
                f = own.get(n)
                if f and f in met: cnt[f] = cnt.get(f, 0) + 1
        if cnt:
            tgt = max(cnt.items(), key=lambda kv: kv[1])[0]
            m["target"] = tgt
    for o in api.offers_in or []:
        frm = o.get("frm")
        if o.get("kind") == "pact":
            if frm == tgt: api.cmd("reject %s" % o["id"])
            else: api.cmd("accept %s" % o["id"])
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
    if t % 48 == 6:
        outp = set(o.get("to") for o in (api.offers_out or []) if o.get("kind") == "pact")
        for f in met:
            if f == tgt or f in pacts or f in outp: continue
            api.cmd("offer %s pact 480" % f)
    if t % 48 == 30 and met:
        outt = set(o.get("to") for o in (api.offers_out or []) if o.get("kind") == "trade")
        for f in met:
            if f in outt or f == tgt: continue
            for k in ("rare", "oil", "steel"):
                lim = 300 if k == "rare" else 600
                if api.stock.get(k, 0) > lim + 200:
                    n = 150 if k == "rare" else 250
                    api.cmd("offer %s trade %d %s for %d res" % (f, n, k, 90 if k == "rare" else 100))
                    break
    if t == 12:
        for f in met:
            if f != tgt:
                api.cmd("say %s Amazonia wants lasting peace. We accept every pact and keep them; we trade oil/steel/rare for res." % f)

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
            if el > 48: done = True
            elif el >= 12:
                avs = sum(uby[i]["str"] for i in ids) / max(1, len(ids))
                if avs < 45: done = True
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
            ready = (avgb >= 45 and avgr >= 65) or (t - a["start"] >= 100 and avgr >= 60 and avgb >= 35)
            if not ready: continue
            e = api.enemy.get(tgi)
            ok = True
            if e and pr:
                art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / n
                d = (e.get("str", 0) or 0) * (1.0 if e.get("exact") else 1.3)
                _, fort, ed = _eff_def(pr, d, art)
                a_str = sum(u["str"] * (0.4 + 0.6 * u["rdy"] / 100.0) for u in pool)
                a_str *= 1 + avgb / 100.0
                if a_str < 2.5 * (ed + 1): ok = False
                if fort >= 3: ok = False
            if ok:
                api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgi))
                a["launch"] = t
            else:
                api.cmd("front " + ",".join(str(i) for i in ids))
                del atks[tg]
    maxa = 4 + len(api.units) // 150
    if len(atks) >= maxa: return
    mdl = api.model or {}
    cands = []
    caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
    tgtf = m.get("target")
    for p, e in api.enemy.items():
        pr = provs.get(p)
        if not pr or str(p) in atks: continue
        if own.get(p) in pacts: continue
        fort = pr.get("fort", 0) or 0
        if fort >= 3: continue
        adj = [n for n in pr.get("nbrs", []) if provs.get(n, {}).get("owner") == "me"]
        if not adj: continue
        pool = []; dirs = 0; elev_pen = 0
        for n in adj:
            here = byprov.get(n, [])
            us = [u for u in here if u["id"] not in busy and u["type"] not in ("rec", "mil")
                  and u["str"] >= 75 and u.get("rdy", 0) >= 55 and u.get("mor", 70) >= 50
                  and u["state"] not in ("routing", "shaken", "refitting")]
            if not us: continue
            us.sort(key=lambda u: -u["str"])
            keep = 1 if len(here) <= len(us) else 0
            take = us[keep:]
            if take:
                dirs += 1
                elev_pen += max(0, (pr.get("elev", 0) or 0) - (provs.get(n, {}).get("elev", 0) or 0))
            pool += take
        if len(pool) < 5: continue
        d_str = e.get("str", 0) or 0
        if not e.get("exact"): d_str *= 1.3
        art = sum(1 for u in pool if u["type"] in ("art", "rkt")) / float(len(pool))
        if fort >= 2 and art < 0.35: continue
        tdf, fort, ed = _eff_def(pr, d_str, art)
        rdy = sum(u["rdy"] for u in pool) / (100.0 * len(pool))
        a_eff = sum(u["str"] for u in pool) * (0.4 + 0.6 * rdy) * 1.45
        if elev_pen and dirs: a_eff *= 0.9 ** (elev_pen / float(dirs))
        if a_eff < 3.5 * (ed + 1): continue
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
            if score < 0.55: continue
        val = (pr.get("y", 0) or 0) + 3 * (1 if pr.get("city") else 0) + pr.get("steel", 0) + pr.get("oil", 0) + pr.get("rare", 0)
        if p in caps: val += 50
        if tgtf and own.get(p) == tgtf: val += 5
        cands.append((score + 0.02 * val + 0.12 * dirs, p, pool))
    cands.sort(key=lambda c: -c[0])
    for sc, p, pool in cands:
        if len(atks) >= maxa: break
        ids = [u["id"] for u in pool if u["id"] not in busy]
        if len(ids) < 5: continue
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
        # skip ones directly adjacent to our land (default expand takes them)
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
    neut = _neutrals(api, m)
    _recruit(api, m, neut)
    inatk = set()
    for a in m.get("atk", {}).values(): inatk.update(a["ids"])
    _refit(api, m, inatk)
    exp_ids = []; front_ids = []; explore_ids = []
    for u in api.units:
        if u["id"] in inatk: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u["state"] == "refitting": continue
        if u["type"] == "rec":
            if api.unexplored: explore_ids.append(u["id"])
            continue
        if (api.neutral_border or neut) and u["type"] in ("cav", "inf", "mot", "mtn"):
            exp_ids.append(u["id"])
        else:
            front_ids.append(u["id"])
    if explore_ids: api.cmd("explore " + ",".join(str(i) for i in explore_ids))
    if exp_ids:
        # send part toward distinct far targets to spread expansion
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
to andea: Amazonia accepts. Offer the pact without end date and we accept at once; we will not take your land while it holds.
to platina: Amazonia keeps every pact. Let's keep the peace again this war; we also trade steel, oil and rare for res.
to granada: Amazonia offers peace from hour 0 and fair trades: our steel, oil and rare for your res.
to anahuac: Amazonia offers a standing pact from hour 0; we keep our word.
```