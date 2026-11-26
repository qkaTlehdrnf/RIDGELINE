**Reasoning**

The last war ended 9th-10th with about 130 provinces. Three problems stand out. First, 74% of units sat below readiness 5 because the `front` order kept reshuffling them, and contact blocked resting. Second, assaults almost never went in with real mass: the staged groups were small and the logged "assaults" were mostly passing fire. Third, stockpiles went unused (1,894 steel and 795 rare at the end), and one depot carried 127 provinces at 103/60 load.

Changes in this policy:
- Border provinces keep up to two ready units fortified in place, which stops the reshuffling and builds defence. Weak units (strength under 40) pull back to the rear.
- The rest of the ready units stay on the `front` order, and the attack staging logic is unchanged.
- Depots scale to about one per 30 provinces, up to 8, checked every 24 h, so no single depot overloads.
- Steel and rare thresholds for heavy armour, hard-hitting units and rockets are lowered so the stockpile gets spent.
- Pacts are accepted, but I stop proactively offering them after tick 300, so land stays open for score.

I have not run this policy, so the thresholds are untested. I will check the review at `standard` detail next time.

```python
def tick(api):
    mem = api.mem
    now = api.t
    units = api.units
    byid = {u["id"]: u for u in units}
    owned = [i for i, p in api.provs.items() if p.get("owner") == "me"]
    owned_set = set(owned)
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1

    W = {"res": 1.0, "mp": 1.0, "steel": 3.0, "oil": 3.0, "rare": 4.0}

    def val(d):
        s = 0.0
        for k, n in (d or {}).items():
            s += W.get(k, 1.0) * n
        return s

    TERR = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}

    pact_names = set()
    for f, pd in api.pacts.items():
        e = pd.get("ends")
        if e is None or e > now:
            pact_names.add(f)

    def odds(my, en, fort, city, bonus, rdy, heavy, dirs, terr):
        m = api.model or {}
        if not m.get("w"):
            return 1.0 if my >= 2.5 * en else 0.0
        feats = {"log_ratio": math.log((my + 1.0) / (en + 1.0)), "terrain_dfn": terr,
                 "fort": fort, "city": city, "bonus": bonus, "att_rdy": rdy,
                 "heavy_share": heavy, "dirs": dirs}
        s = m["b"]
        for f, w, mu, sd in zip(m["features"], m["w"], m["mean"], m["std"]):
            s += w * (feats.get(f, 0.0) - mu) / sd
        s = max(-30.0, min(30.0, s))
        return 1.0 / (1.0 + math.exp(-s))

    # ---- diplomacy: accept dated pacts always; undated only early ----
    try:
        for o in api.offers_in:
            try:
                if o.get("kind") == "pact":
                    dated = o.get("hours") is not None
                    if dated or now < 600:
                        api.cmd("accept %d" % o["id"])
                    else:
                        api.cmd("reject %d" % o["id"])
                elif val(o.get("they_give")) >= 1.3 * val(o.get("you_give")):
                    api.cmd("accept %d" % o["id"])
                else:
                    api.cmd("reject %d" % o["id"])
            except Exception:
                pass
    except Exception:
        pass

    # ---- proactive pacts with neighbours only in the opening ----
    try:
        pof = mem.setdefault("pof", {})
        if now < 300:
            nb_fac = set()
            for i in owned:
                for nb in api.provs[i].get("nbrs", []):
                    f = api.owner_name.get(nb)
                    if f:
                        nb_fac.add(f)
            for f in api.met:
                if f in pact_names or f not in nb_fac:
                    continue
                if now - pof.get(f, -1000) < 72:
                    continue
                api.cmd("offer %s pact 240" % f)
                pof[f] = now
    except Exception:
        pass

    try:
        if api.met and not mem.get("said"):
            for f in api.met:
                api.cmd("say %s Abyssinia seeks peace and free land. Keep out of our provinces and we keep out of yours." % f)
            mem["said"] = now
    except Exception:
        pass

    # ---- research ----
    try:
        if len(api.research) < 2:
            pri = ["farming", "mining", "conscription", "medicine", "staffwork",
                   "discipline", "arm.weapons", "hvt.weapons", "mec.weapons",
                   "art.weapons", "inf.weapons", "drill", "industry", "fieldworks",
                   "mot.mobility", "logistics", "drilling", "arm.protection",
                   "inf.protection"]
            names = [l for l in pri if l in api.tech] + [l for l in api.tech if l not in pri]
            for line in names:
                tv = api.tech.get(line) or {}
                if tv.get("status") != "open":
                    continue
                cost = tv.get("cost") or {}
                ok = all(api.stock.get(k, 0) >= cost[k] + (100 if k == "res" else 0) for k in cost)
                if ok and api.cmd("research " + line).startswith("ok"):
                    break
    except Exception:
        pass

    # ---- depots: one per ~30 owned provinces, farthest from existing ones ----
    try:
        if now - mem.get("dep_t", -100) >= 24 and api.stock.get("res", 0) >= 300:
            mem["dep_t"] = now
            dep = set(int(k) for k in api.depots.keys())
            want = min(8, 1 + len(owned) // 30)
            if dep and len(dep) < want:
                dist = {d: 0 for d in dep}
                q = list(dep)
                qi = 0
                while qi < len(q):
                    x = q[qi]
                    qi += 1
                    for nb in api.provs.get(x, {}).get("nbrs", []):
                        if nb in dist:
                            continue
                        if nb not in owned_set:
                            continue
                        dist[nb] = dist[x] + 1
                        q.append(nb)
                cands = []
                for p in dist:
                    if p in dep or dist[p] < 3:
                        continue
                    sc = dist[p] + (2 if api.provs.get(p, {}).get("city") else 0)
                    cands.append((sc, p))
                if cands:
                    cands.sort(reverse=True)
                    api.cmd("depot P%d 1" % cands[0][1])
    except Exception:
        pass

    # ---- refit outdated units (budgeted) ----
    try:
        if api.old_units > 0:
            rcost = api.refit_cost or {}
            budget = dict(api.stock)
            ids = []
            for u in units:
                if len(ids) >= 40:
                    break
                if not u.get("old") or u.get("path") or u.get("state") != "ready":
                    continue
                if u.get("fighting") or not u.get("supplied"):
                    continue
                c = rcost.get(u["type"])
                if not c:
                    continue
                if budget.get("res", 0) - c.get("res", 0) < 150:
                    continue
                if any(budget.get(k, 0) < c.get(k, 0) for k in ("steel", "oil", "rare")):
                    continue
                for k in ("res", "steel", "oil", "rare"):
                    budget[k] = budget.get(k, 0) - c.get(k, 0)
                ids.append(str(u["id"]))
            if ids:
                api.cmd("refit " + ",".join(ids))
    except Exception:
        pass

    # ---- recruitment: spend the steel, rare and oil stockpiles ----
    try:
        rc = api.capital
        for c in owned:
            if api.provs.get(c, {}).get("city") and c in api.border:
                rc = c
                break
        if counts.get("rec", 0) < 2 and api.res >= 60 and api.mp >= 10:
            if api.cmd("recruit rec 1 P%d" % api.capital).startswith("ok"):
                counts["rec"] = counts.get("rec", 0) + 1
        cap_units = 220 + 15 * len(owned)
        weights = {"inf": 3, "mot": 2, "arm": 2, "art": 3, "atg": 1,
                   "eng": 1, "mtn": 1, "mec": 1, "hvt": 1, "grn": 1}
        st = dict(api.stock)
        if st.get("steel", 0) > 300:
            weights["arm"] += 1
            weights["hvt"] += 1
            weights["mec"] += 1
        if st.get("rare", 0) > 100:
            weights["rkt"] = 1
        res = api.res
        mp = api.mp
        total = len(units)
        for _ in range(20):
            if total >= cap_units:
                break
            best = None
            bs = 1e9
            for ty, w in weights.items():
                if w <= 0:
                    continue
                uc = api.unit_costs.get(ty)
                if not uc:
                    continue
                if res - uc.get("res", 0) < 200 or mp - uc.get("mp", 0) < 25:
                    continue
                if any(st.get(k, 0) < uc.get(k, 0) for k in ("steel", "oil", "rare")):
                    continue
                sc = (counts.get(ty, 0) + 1) / float(w)
                if sc < bs:
                    bs = sc
                    best = ty
            if best is None:
                break
            r = api.cmd("recruit %s 1 P%d" % (best, rc))
            if not r.startswith("ok"):
                break
            uc = api.unit_costs[best]
            res -= uc.get("res", 0)
            mp -= uc.get("mp", 0)
            for k in ("steel", "oil", "rare"):
                st[k] = st.get(k, 0) - uc.get(k, 0)
            counts[best] = counts.get(best, 0) + 1
            total += 1
    except Exception:
        pass

    # ---- staged assaults: one at a time, on good odds ----
    try:
        at = {}
        for u in units:
            if u.get("path") or u.get("state") != "ready":
                continue
            if u["str"] < 60 or u.get("rdy", 100) < 60 or u["type"] == "rec":
                continue
            at.setdefault(u["prov"], []).append(u)

        op = mem.get("op")
        if op:
            tgt = op["tgt"]
            alive = [i for i in op["ids"] if i in byid]
            if api.provs.get(tgt, {}).get("owner") == "me" or not alive or now - op["t0"] > 240:
                mem["op"] = None
            elif not op["go"]:
                ready_ids = [i for i in alive if not byid[i].get("path")]
                my = sum(byid[i]["str"] for i in ready_ids)
                e = api.enemy.get(tgt)
                en = e.get("str", 0) if e else 0
                fort = api.provs.get(tgt, {}).get("fort") or 0
                if now - op["t0"] >= 24 and len(ready_ids) >= 3 and fort < 3:
                    heavy = sum(1 for i in ready_ids if byid[i]["type"] in ("art", "eng", "arm")) / float(len(ready_ids))
                    p = odds(my, en, fort, 1 if api.provs.get(tgt, {}).get("city") else 0,
                             0.0, 0.5, heavy, 1,
                             TERR.get(api.provs.get(tgt, {}).get("terrain"), 1.0))
                    if p >= 0.65 and my >= 2.5 * en:
                        api.cmd("move %s P%d" % (",".join(str(i) for i in ready_ids), tgt))
                        op["go"] = True
                        op["t0"] = now
                    elif now - op["t0"] > 36:
                        mem["op"] = None
                elif now - op["t0"] > 36:
                    mem["op"] = None
            elif now - op["t0"] >= 30:
                mem["op"] = None

        if not mem.get("op"):
            best = None
            bsc = -1e18
            for s in list(api.border.keys()):
                sp = api.provs.get(s)
                if not sp or sp.get("owner") != "me":
                    continue
                staged = at.get(s, [])
                if len(staged) < 3:
                    continue
                my = sum(u["str"] for u in staged)
                heavy = sum(1 for u in staged if u["type"] in ("art", "eng", "arm")) / float(len(staged))
                arty = sum(1 for u in staged if u["type"] == "art")
                rdy = sum(u.get("rdy", 50) for u in staged) / float(len(staged)) / 100.0
                for nb in sp.get("nbrs", []):
                    npr = api.provs.get(nb)
                    if not npr or npr.get("owner") == "me":
                        continue
                    own = npr.get("owner")
                    if own not in ("neutral", "enemy"):
                        continue
                    if api.owner_name.get(nb) in pact_names:
                        continue
                    e = api.enemy.get(nb)
                    if own == "enemy" and e is None:
                        continue
                    en = e.get("str", 0) if e else 0
                    fort = npr.get("fort") or 0
                    if fort >= 3:
                        continue
                    if fort >= 2 and arty < 3:
                        continue
                    if my < 2.5 * en or my < 120:
                        continue
                    dirs = sum(1 for x in api.provs[nb].get("nbrs", []) if api.provs.get(x, {}).get("owner") == "me")
                    p = odds(my, en, fort, 1 if npr.get("city") else 0, 0.0, rdy, heavy,
                             max(1, dirs), TERR.get(npr.get("terrain"), 1.0))
                    if p < 0.65:
                        continue
                    sc = 100 * p + (40 if own == "neutral" else 0) - 20 * fort
                    if sc > bsc:
                        bsc = sc
                        best = (nb, staged)
            if best:
                nb, staged = best
                r = api.cmd("prepare %s P%d" % (",".join(str(u["id"]) for u in staged), nb))
                if r.startswith("ok"):
                    mem["op"] = {"tgt": nb, "ids": [u["id"] for u in staged],
                                 "t0": now, "go": False}
    except Exception:
        pass

    # ---- garrisons and idle units ----
    try:
        opset = set()
        if mem.get("op"):
            opset = set(mem["op"]["ids"])
        explore_ids = []
        expand_ids = []
        front_ids = []
        fort_ids = []
        handled = set()
        garrison_n = {}
        for u in units:
            if u["id"] in opset or u.get("path") or u.get("state") != "ready":
                continue
            p = u["prov"]
            if p in api.border and p in owned_set:
                handled.add(u["id"])
                if u.get("str", 100) < 40:
                    rear = [n for n in api.provs.get(p, {}).get("nbrs", [])
                            if n in owned_set and n not in api.border]
                    if rear:
                        api.cmd("move %d P%d" % (u["id"], rear[0]))
                    continue
                if garrison_n.get(p, 0) < 2:
                    garrison_n[p] = garrison_n.get(p, 0) + 1
                    fort_ids.append(str(u["id"]))
                    continue
                front_ids.append(str(u["id"]))
        for u in units:
            if u["id"] in opset or u["id"] in handled:
                continue
            if u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
                continue
            if u.get("state") != "ready":
                continue
            if u["type"] == "rec":
                explore_ids.append(str(u["id"]))
            elif api.neutral_border and len(expand_ids) < 25:
                expand_ids.append(str(u["id"]))
            else:
                front_ids.append(str(u["id"]))
        if fort_ids:
            api.cmd("fortify " + ",".join(fort_ids))
        if explore_ids:
            api.cmd("explore " + ",".join(explore_ids))
        if expand_ids:
            api.cmd("expand " + ",".join(expand_ids))
        if front_ids:
            api.cmd("front " + ",".join(front_ids))
    except Exception:
        pass

    mem["last_units"] = len(units)
```

REVIEW: standard