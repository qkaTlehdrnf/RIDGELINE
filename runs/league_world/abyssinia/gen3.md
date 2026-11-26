**Reasoning (last war, 9th of 30):** Expansion and diplomacy worked. We signed pacts with most neighbours and held 142 provinces. Three things went wrong:

1. **Assaults never succeeded** (0 of 167). Most targets had fort level 3, and we attacked without artillery to counter it.
2. **The bank sat unused**: 6,526 res and 5,480 steel at the end. The unit cap (160 + 12/province) stopped recruiting.
3. **Refits lagged**: 638 of 1,890 units stayed on old models.

Changes:
- Raise the unit cap and spend down to a smaller reserve.
- Recruit more per tick.
- Refit more aggressively.
- Attack only when the target's fort is low, or when the staged group includes at least 3 artillery and a 4x strength edge against high-fort targets.
- Prefer neutral and low-fort targets in target scoring.

Diplomacy and research stay as before.

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

    # ---- refit old units out of combat in the rear (more aggressively) ----
    try:
        if api.res > 400:
            rf = [u["id"] for u in units
                  if u.get("old") and not u.get("front") and not u.get("expand")
                  and not u.get("path") and u.get("state") == "ready"
                  and not u.get("fighting") and u.get("supplied")]
            rf = rf[:40]
            if rf:
                api.cmd("refit " + ",".join(str(i) for i in rf))
    except Exception:
        pass

    # ---- recruitment: spend the stockpile, mix by weights ----
    try:
        rc = api.capital
        for c in owned:
            if api.provs.get(c, {}).get("city") and c in api.border:
                rc = c
                break
        cap_units = 220 + 15 * len(owned)
        weights = {"inf": 3, "mot": 2, "arm": 2, "art": 3, "atg": 1,
                   "eng": 1, "mtn": 1, "mec": 1, "hvt": 1, "grn": 1}
        res = api.res
        mp = api.mp
        st = dict(api.stock)
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
                if res - uc.get("res", 0) < 300 or mp - uc.get("mp", 0) < 25:
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
                fort = api.provs.get(tgt, {}).get("fort") or 0
                arty = sum(1 for i in ready_ids if byid[i]["type"] == "art")
                need = 4 if fort >= 2 else 3
                ok_arty = fort < 2 or arty >= 3
                if now - op["t0"] >= 24 and my >= need * en and len(ready_ids) >= 4 and ok_arty:
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
                arty = sum(1 for u in staged if u["type"] == "art")
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
                    need = 4 if fort >= 2 else 3
                    if fort >= 2 and arty < 3:
                        continue
                    if my < need * en or my < 200:
                        continue
                    sc = my - need * en - 100 * fort + (50 if own == "neutral" else 0)
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
to maghreb: Abyssinia accepts lasting peace. Our pact stands; we will not break first and welcome trade in spare oil and steel.
to austral: Abyssinia agrees to a lasting peace. Keep to your borders and we will keep to ours; a pact is welcome.
to kongo: Abyssinia accepts peace on our borders. We will keep the pact and focus on others.
```