**Review of war 2 (121 provinces, 10th of 30):** Land was won mostly through expansion. Assaults failed badly (5 of 213 taken), mostly at low strength ratios or low readiness. About 45% of the army was still on outdated models, and the stockpile sat unused (res 7,387, steel 3,907). Diplomacy was never used.

**Changes:**
- **Assaults:** Attack only at 3x the enemy's strength, with units at readiness 60+ and strength 70+, after a 24h prepared build-up.
- **Diplomacy:** Accept incoming pacts and reject trades. Offer 240h pacts to met factions that do not border us, and skip pact partners as targets.
- **Refit:** Re-equip out-of-combat old units in the rear while resources allow.
- **Research:** Read open lines from `api.tech` directly, favouring the lines that paid off last war.
- **Recruitment:** Spend the stockpile with a higher unit cap and more artillery and armour.
- **Letters:** Propose peace to the five factions we met, and open with a `say` once.

I have not run this against the engine, so the first trial will show whether the stricter odds still leave enough attacks to take land.

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

    # active pacts (by faction name) - these partners are not targets
    pact_names = set()
    for f, pd in api.pacts.items():
        e = pd.get("ends")
        if e is None or e > now:
            pact_names.add(f)

    # ---- diplomacy: accept pacts, reject trades, offer pacts to non-neighbours ----
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

    # ---- one-time letters to met factions ----
    try:
        if api.met and not mem.get("said"):
            for f in api.met:
                api.cmd("say %s Abyssinia proposes peace: keep out of our provinces and we will keep out of yours. Reply by letter." % f)
            mem["said"] = now
    except Exception:
        pass

    # ---- research: keep two projects running when affordable ----
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

    # ---- refit old units that are out of combat in the rear ----
    try:
        if api.res > 800:
            rf = [u["id"] for u in units
                  if u.get("old") and not u.get("front") and not u.get("expand")
                  and not u.get("path") and u.get("state") == "ready"
                  and not u.get("fighting") and u.get("supplied")]
            rf = rf[:20]
            if rf:
                api.cmd("refit " + ",".join(str(i) for i in rf))
    except Exception:
        pass

    # ---- recruitment: spend the stockpile, mix by weights ----
    try:
        rc = api.capital
        for c in owned:
            if api.provs[c].get("city") and c in api.border:
                rc = c
                break
        cap_units = 160 + 12 * len(owned)
        weights = {"inf": 3, "mot": 2, "arm": 2, "art": 2, "atg": 1,
                   "eng": 1, "mtn": 1, "mec": 1, "hvt": 1, "grn": 1}
        res = api.res
        mp = api.mp
        st = dict(api.stock)
        total = len(units)
        for _ in range(12):
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

    # ---- one staged assault at a time: prepare, wait, check odds, move ----
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
                if now - op["t0"] >= 24 and my >= 3 * en and len(ready_ids) >= 4:
                    api.cmd("move %s P%d" % (",".join(str(i) for i in ready_ids), tgt))
                    op["go"] = True
                    op["t0"] = now
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
                    if my < 3 * en or my < 200:
                        continue
                    sc = my - 3 * en
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

    # ---- assign idle units (operation units are left alone) ----
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
to nilotica: Abyssinia proposes peace: keep out of our provinces and we will keep out of yours. Accept our pact offer and we both hold our land.
to sahelia: Abyssinia proposes peace: keep out of our provinces and we will keep out of yours. Accept our pact offer and we both hold our land.
to kongo: Abyssinia proposes peace: keep out of our provinces and we will keep out of yours. Accept our pact offer and we both hold our land.
to austral: Abyssinia proposes peace: keep out of our provinces and we will keep out of yours. Accept our pact offer and we both hold our land.
to arabia: Abyssinia proposes peace: keep out of our provinces and we will keep out of yours. Accept our pact offer and we both hold our land.
```