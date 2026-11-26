**Review of war 2:** We finished 16th with 91 provinces. The main problems were:

- **Assaults almost never succeed** (1 of 376). The strict attack gate meant the army mostly sat still once neutral land ran out.
- **Hoarding:** we ended with 4,281 oil and 2,615 steel unused, while armour and motorised units were capped at small shares.
- **Stale models:** 575 of 1,300 units were still on old models. We never refit.
- **No diplomacy:** we never sent or received a pact or offer.

**Changes:**
1. Refit idle rear units on old models when resources allow, keeping a reserve for replacements.
2. Scale the armour and motorised shares up when oil is plentiful, and draw on the steel and oil stockpiles.
3. Relax the attack threshold to about 2.5× against exactly known enemies and 3.5× against estimates, still prepared and never blind. Skip pacted factions.
4. Offer 120-hour pacts to met factions, at most once every 96 hours each, to reduce losses on fronts we cannot win.
5. Add research lines for other unit types, which are skipped when the unit type is absent.

```python
INF = ("inf", "mil", "mtn", "mot", "cav")
ARMOURED = ("arm", "hvt", "mec")
LINES = [
    "conscription", "inf.protection", "discipline", "inf.weapons", "fieldworks",
    "art.weapons", "logistics", "mining", "medicine", "industry", "drill",
    "arm.protection", "arm.weapons", "atg.weapons", "mtn.protection",
    "mot.mobility", "mot.weapons", "hvt.protection", "hvt.weapons",
    "mec.protection", "staffwork", "farming",
]


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def _bon(u):
    b = u.get("bonus", 0) or 0
    return b * 100 if b <= 1 else b


def _ok(api, t, n=1):
    c = api.costs.get(t, (0, 0))
    uc = api.unit_costs.get(t, {}) or {}
    if api.res < c[0] * n + 60 or api.mp < c[1] * n:
        return False
    st = api.stock
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < uc.get(k, 0) * n:
            return False
    return True


def _pick(api, counts, total, armour):
    oil = api.stock.get("oil", 0)
    prio = []
    if counts.get("rec", 0) < 2 and total >= 4:
        prio.append("rec")
    if counts.get("art", 0) < 0.14 * total:
        prio.append("art")
    if armour and counts.get("atg", 0) < 0.10 * total:
        prio.append("atg")
    arm_share = 0.18 if oil >= 800 else (0.12 if oil >= 200 else 0.0)
    mot_share = 0.15 if oil >= 800 else (0.12 if oil >= 150 else 0.0)
    if total >= 30 and counts.get("arm", 0) < arm_share * total:
        prio.append("arm")
    if total >= 30 and counts.get("mot", 0) < mot_share * total:
        prio.append("mot")
    if total >= 60 and counts.get("eng", 0) < 0.04 * total:
        prio.append("eng")
    prio.append("inf")
    for t in prio:
        if _ok(api, t):
            return t
    return None


def _refit(api):
    try:
        if (api.old_units or 0) <= 0:
            return
        border = api.border or {}
        rc = api.refit_cost or {}
        cands = [u for u in api.units
                 if u.get("old") and u.get("state") == "ready"
                 and u.get("supplied") and u["prov"] not in border]
        ids = []
        res_used = 0
        st_used = {"steel": 0, "oil": 0, "rare": 0}
        for u in cands[:40]:
            c = rc.get(u["type"], {}) or {}
            if api.res - res_used - c.get("res", 0) < 250:
                break
            short = False
            for k in ("steel", "oil", "rare"):
                if api.stock.get(k, 0) - st_used[k] < c.get(k, 0):
                    short = True
            if short:
                continue
            res_used += c.get("res", 0)
            for k in ("steel", "oil", "rare"):
                st_used[k] += c.get(k, 0)
            ids.append(u)
        if ids:
            api.cmd("refit " + _ids(ids))
    except Exception:
        pass


def _pacts(api):
    try:
        m = api.mem
        pt = m.setdefault("pact_try", {})
        pending = set(o.get("to") for o in (api.offers_out or []))
        for f in api.met or []:
            if f in (api.pacts or {}) or f in pending:
                continue
            if api.t - pt.get(f, -10**9) < 96:
                continue
            pt[f] = api.t
            api.cmd("offer %s pact 120" % f)
    except Exception:
        pass


def tick(api):
    m = api.mem
    me = api.me
    units = api.units or []

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)

    armour = False
    for v in (api.enemy or {}).values():
        ty = str(v.get("types", ""))
        if any(a in ty for a in ARMOURED):
            armour = True

    # 0. Refit old models out of combat
    _refit(api)

    # 1. Recruit (up to 3 per tick)
    try:
        if api.income > 0 or total < 20:
            for _ in range(3):
                pick = _pick(api, counts, total, armour)
                if not pick:
                    break
                r = api.cmd("recruit %s P%d" % (pick, api.capital))
                if not str(r).startswith("ok"):
                    break
                counts[pick] = counts.get(pick, 0) + 1
                total += 1
    except Exception:
        pass

    # 2. Assign idle units
    try:
        idle = [u for u in units
                if u.get("state") == "ready" and not u.get("path")
                and not (u.get("front") or u.get("expand") or u.get("explore"))]
        scouts = [u for u in idle if u["type"] == "rec"]
        inf = [u for u in idle if u["type"] in INF]
        heavy = [u for u in idle if u["type"] not in INF and u["type"] != "rec"]
        if scouts:
            api.cmd("explore " + _ids(scouts))
        if inf:
            api.cmd("expand " + _ids(inf))
        if heavy:
            api.cmd("front " + _ids(heavy))
    except Exception:
        pass

    # 3. Attacks: prepared, against known enemies, with a clear margin
    try:
        if api.stock.get("res", 0) >= 80:
            by_prov = {}
            for u in units:
                if (u.get("state") in ("ready", "preparing") and u.get("str", 0) >= 50
                        and u.get("rdy", 0) >= 50 and not u.get("path")
                        and not u.get("expand") and not u.get("explore")
                        and u["type"] != "rec"):
                    by_prov.setdefault(u["prov"], []).append(u)
            pacts = api.pacts or {}
            owners = api.owner_name or {}
            done = False
            for p, lst in by_prov.items():
                if done:
                    break
                pr = api.provs.get(p)
                if not pr:
                    continue
                for n in pr.get("nbrs", []):
                    nd = api.provs.get(n)
                    if not nd or nd.get("who", -1) in (-1, me):
                        continue
                    if owners.get(n) in pacts:
                        continue
                    e = (api.enemy or {}).get(n)
                    if e is None:
                        continue  # never attack blind
                    exact = bool(e.get("exact"))
                    es = e.get("str", 0)
                    ours = sum(u.get("str", 0) for u in lst)
                    need = (2.5 * es + 60) if exact else (3.5 * es + 80)
                    if ours < need:
                        continue
                    planned = [u for u in lst if u.get("plan") == n]
                    if planned:
                        avg = sum(_bon(u) for u in planned) / len(planned)
                        if avg >= 30:
                            api.cmd("move %s P%d" % (_ids(planned), n))
                            done = True
                            break
                        continue
                    free = [u for u in lst if u.get("plan", -1) in (-1, None)]
                    if free:
                        api.cmd("prepare %s P%d" % (_ids(free), n))
                        done = True
                        break
    except Exception:
        pass

    # 4. Research (blind; two projects at once, keep a reserve)
    try:
        active = set(r[0] for r in (api.research or []))
        if len(active) < 2 and api.res > 220:
            for line in LINES:
                if len(active) >= 2:
                    break
                if line in active:
                    continue
                if "." in line and line.split(".")[0] not in counts:
                    continue
                info = (api.tech or {}).get(line)
                if not info or info.get("status") != "open":
                    continue
                c = info.get("cost") or {}
                if api.res < c.get("res", 0) + 150:
                    continue
                if any(api.stock.get(k, 0) < c.get(k, 0) for k in ("steel", "oil", "rare")):
                    continue
                api.cmd("research %s" % line)
                active.add(line)
    except Exception:
        pass

    # 5. Diplomacy: offer short pacts to met factions
    _pacts(api)

    m["calls"] = m.get("calls", 0) + 1
```