**Review of war 4 (133 provinces, 11th of 30):** Assaults failed completely: 0 of 137 against defended provinces, including 0 of 114 against fort level 3-4. Almost all the rest of the field was stalemate. Land ran out by day 95, and 947 of 2184 units were still on outdated models. Steel sat at 4394 unused while res stayed near 200-350, so res is the real bottleneck.

**Changes:**
- Assaults now need a model-estimated win chance of at least 0.6, at least 3x the enemy strength, and no forts at level 3 or above. Odds are rechecked before the move.
- Expansion into neutral land keeps priority. Scoring favours neutral and low-fort targets.
- Refit starts at 150 res instead of 400, and works through 20 units per tick, to reduce the outdated-model backlog.
- Recruitment reserve drops to 200 res, and armour and heavy armour get extra weight while steel is above 1500.
- Pact diplomacy and research priorities are kept.

I can't verify the fitted model against this map, so I've treated it as one input, not as ground truth.

```python
def tick(api):
    mem = api.mem
    now = api.t
    units = api.units
    byid = {u["id"]: u for u in units}
    owned = [i for i, p in api.provs.items() if p.get("owner") == "me"]
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1

    pact_names = set()
    for f, pd in api.pacts.items():
        e = pd.get("ends")
        if e is None or e > now:
            pact_names.add(f)

    TERR = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}

    def odds(my, en, fort, city, bonus, rdy, heavy, dirs, terr):
        m = api.model or {}
        if not m.get("w"):
            return 1.0 if my >= 3 * en else 0.0
        feats = {"log_ratio": math.log((my + 1.0) / (en + 1.0)), "terrain_dfn": terr,
                 "fort": fort, "city": city, "bonus": bonus, "att_rdy": rdy,
                 "heavy_share": heavy, "dirs": dirs}
        s = m["b"]
        for f, w, mu, sd in zip(m["features"], m["w"], m["mean"], m["std"]):
            s += w * (feats.get(f, 0.0) - mu) / sd
        s = max(-30.0, min(30.0, s))
        return 1.0 / (1.0 + math.exp(-s))

    # ---- diplomacy ----
    try:
        for o in api.offers_in:
            if o.get("kind") == "pact":
                api.cmd("accept %d" % o["id"])
            else:
                api.cmd("reject %d" % o["id"])
        pof = mem.setdefault("pof", {})
        border_with = set()
        for i in owned:
            for nb in api.provs[i].get("nbrs", []):
                o = api.owner_name.get(nb)
                if o:
                    border_with.add(o)
        for f in api.met:
            if f in pact_names or f in border_with:
                continue
            if now - pof.get(f, -1000) < 72:
                continue
            api.cmd("offer %s pact 240" % f)
            pof[f] = now
    except Exception:
        pass

    # ---- one-time letters ----
    try:
        if api.met and not mem.get("said"):
            for f in api.met:
                api.cmd("say %s Abyssinia proposes peace: keep out of our provinces and we will keep out of yours. Reply by letter." % f)
            mem["said"] = now
    except Exception:
        pass

    # ---- research ----
    try:
        if len(api.research) < 2:
            pri = ["farming", "mining", "conscription", "discipline", "medicine",
                   "staffwork", "arm.weapons", "art.weapons", "inf.weapons", "drill",
                   "fieldworks", "industry", "mot.mobility", "hvt.weapons", "mec.weapons",
                   "inf.protection", "arm.protection"]
            names = [l for l in pri if l in api.tech] + [l for l in api.tech if l not in pri]
            for line in names:
                tv = api.tech.get(line) or {}
                if tv.get("status") != "open":
                    continue
                cost = tv.get("cost") or {}
                ok = all(api.stock.get(k, 0) >= cost[k] + 100 for k in cost)
                if ok and api.cmd("research " + line).startswith("ok"):
                    break
    except Exception:
        pass

    # ---- refit old units in the rear ----
    try:
        if api.res > 150:
            rf = [u["id"] for u in units
                  if u.get("old") and not u.get("front") and not u.get("expand")
                  and not u.get("path") and u.get("state") == "ready"
                  and not u.get("fighting") and u.get("supplied")]
            rf = rf[:20]
            if rf:
                api.cmd("refit " + ",".join(str(i) for i in rf))
    except Exception:
        pass

    # ---- recruitment ----
    try:
        rc = api.capital
        for c in owned:
            if api.provs.get(c, {}).get("city") and c in api.border:
                rc = c
                break
        cap_units = 220 + 15 * len(owned)
        weights = {"inf": 3, "mot": 2, "arm": 2, "art": 3, "atg": 1,
                   "eng": 1, "mtn": 1, "mec": 1, "hvt": 1, "grn": 1}
        st = dict(api.stock)
        if st.get("steel", 0) > 1500:
            weights["arm"] += 1
            weights["hvt"] += 1
            weights["mec"] += 1
        res = api.res
        mp = api.mp
        total = len(units)
        for _ in range(20):
            if total >= cap_units:
                break
            best = None
            bs = 1e9
            for ty, w in weights.items():
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

    # ---- one staged assault at a time ----
    try:
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
                if now - op["t0"] >= 24 and len(ready_ids) >= 4 and fort < 3:
                    heavy = sum(1 for i in ready_ids if byid[i]["type"] in ("art", "eng", "arm")) / float(len(ready_ids))
                    p = odds(my, en, fort, 1 if api.provs.get(tgt, {}).get("city") else 0,
                             0.0, 0.5, heavy, 1,
                             TERR.get(api.provs.get(tgt, {}).get("terrain"), 1.0))
                    if p >= 0.6 and my >= 3 * en:
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
                staged = [u for u in units
                          if u["prov"] == s and not u.get("path") and u.get("state") == "ready"
                          and u["str"] >= 70 and u.get("rdy", 100) >= 60 and u["type"] != "rec"]
                if len(staged) < 5:
                    continue
                my = sum(u["str"] for u in staged)
                heavy = sum(1 for u in staged if u["type"] in ("art", "eng", "arm")) / float(len(staged))
                arty = sum(1 for u in staged if u["type"] == "art")
                bonus = 0.0
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
                    if my < 3 * en or my < 200:
                        continue
                    dirs = sum(1 for x in api.provs[nb].get("nbrs", []) if api.provs.get(x, {}).get("owner") == "me")
                    p = odds(my, en, fort, 1 if npr.get("city") else 0, bonus, rdy, heavy,
                             max(1, dirs), TERR.get(npr.get("terrain"), 1.0))
                    if p < 0.6:
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

    # ---- assign idle units ----
    try:
        opset = set()
        if mem.get("op"):
            opset = set(mem["op"]["ids"])
        explore_ids = []
        expand_ids = []
        front_ids = []
        for u in units:
            if u["id"] in opset or u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
                continue
            if u.get("state") != "ready":
                continue
            if u["type"] == "rec":
                explore_ids.append(str(u["id"]))
            elif api.neutral_border and len(expand_ids) < 15:
                expand_ids.append(str(u["id"]))
            else:
                front_ids.append(str(u["id"]))
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

```letters
to kongo: Abyssinia keeps the peace with Kongo. Our pact stands; keep your units out of our provinces and we will do the same.
to sahelia: Abyssinia accepts your peace and will hold to our pact. Keep out of our provinces and we will keep out of yours.
to austral: Abyssinia welcomes the pact. We will keep our fire off your provinces while it holds.
to arabia: Abyssinia accepts your peace. We expect the same from you and will honour the pact while it lasts.
```