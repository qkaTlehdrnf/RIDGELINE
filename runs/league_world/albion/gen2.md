**Reasoning (summary)**

Last war, Albion reached only 44 provinces. Expansion was slow (8 provinces by day 5, 15 by day 25) while neutral land was still open, and income went negative (about -60 per day), which starved recruiting. All 35 assaults failed, and I can't tell from the logs whether the cause was stale enemy estimates, the lack of a scout at the target, or thin force. The first rewrite therefore targets four things:

- **Expansion:** send about half of idle units to `expand` each tick, and recruit cheap `mil` units while neutral land remains.
- **Economy:** recruit only while income is positive or the bank is large, cap the army by province count, and research `farming` and `industry` early.
- **Assaults:** require at least 5 units at 60+ strength and readiness, a 3:1 power ratio, and an attached scout for the +75% prepared bonus. Skip targets owned by pact partners.
- **Diplomacy:** offer 120-hour pacts to factions I've met, accept incoming pacts, and send peace letters to the two factions I know from last war.

```python
RESEARCH_ORDER = [
    "conscription", "farming", "inf.weapons", "inf.protection", "mining",
    "logistics", "industry", "drill", "medicine", "discipline",
    "fieldworks", "atg.weapons", "art.weapons", "mot.mobility",
    "drilling", "refining", "arm.weapons", "arm.protection",
    "staffwork", "mot.weapons", "inf.mobility",
]

TARGETS = {
    "inf": 0.30, "mil": 0.08, "mot": 0.10, "mtn": 0.06, "art": 0.10,
    "atg": 0.06, "arm": 0.08, "eng": 0.05, "cav": 0.05, "grn": 0.07,
}

TERRAIN_DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
EXPAND_TYPES = ("inf", "mtn", "mot", "mil", "cav", "mec", "grn", "eng")


def tick(api):
    m = api.mem
    m.setdefault("refit", [])
    m.setdefault("prep", {})
    m.setdefault("pact_offer", {})
    now = api.t
    provs = api.provs
    units = api.units
    capital = api.capital
    combat = [u for u in units if u.get("type") != "rec"]
    own = [p for p, pv in provs.items() if pv.get("owner") == "me"]
    army_cap = 18 + 6 * len(own)

    budget = {
        "res": api.stock.get("res", 0), "mp": api.mp,
        "steel": api.stock.get("steel", 0), "oil": api.stock.get("oil", 0),
        "rare": api.stock.get("rare", 0),
    }

    def nbrs(pid):
        out = []
        for x in provs.get(pid, {}).get("nbrs", []):
            try:
                out.append(int(x))
            except Exception:
                try:
                    out.append(int(str(x).strip("~P ")))
                except Exception:
                    pass
        return out

    def ids(lst):
        return ",".join(str(i) for i in lst)

    def can(tp, reserve=0.0):
        c = api.costs.get(tp)
        if not c:
            return False
        uc = api.unit_costs.get(tp, {})
        if budget["res"] < c[0] + reserve or budget["mp"] < c[1]:
            return False
        for k in ("steel", "oil", "rare"):
            if budget[k] < uc.get(k, 0):
                return False
        return True

    def spend(tp):
        c = api.costs[tp]
        uc = api.unit_costs.get(tp, {})
        budget["res"] -= c[0]
        budget["mp"] -= c[1]
        for k in ("steel", "oil", "rare"):
            budget[k] -= uc.get(k, 0)

    # 1. Scouting: two recs explore and pick up land
    try:
        recs = [u for u in units if u.get("type") == "rec"]
        if len(recs) < 2 and can("rec", 60.0):
            if str(api.cmd("recruit rec P%d" % capital)).startswith("ok"):
                spend("rec")
        for u in recs:
            if not u.get("path") and not u.get("explore") and not u.get("expand"):
                api.cmd("explore %d" % u["id"])
    except Exception:
        pass

    # 2. Recruiting: only while the economy can carry the upkeep
    try:
        healthy = api.income > 2
        rich = budget["res"] > 700
        if healthy or rich:
            counts = {}
            for u in combat:
                tp = u.get("type")
                counts[tp] = counts.get(tp, 0) + 1
            mix = dict(TARGETS)
            if not api.neutral_border:
                mix["mil"] = 0.0
            for _ in range(3):
                if sum(counts.values()) >= army_cap:
                    break
                total = sum(counts.values()) + 1
                best, bd = None, 0.0
                for tp, w in mix.items():
                    if w <= 0:
                        continue
                    d = w * total - counts.get(tp, 0)
                    if d > bd and can(tp, 150.0):
                        bd, best = d, tp
                if best is None:
                    break
                r = api.cmd("recruit %s P%d" % (best, capital))
                if not str(r).startswith("ok"):
                    break
                spend(best)
                counts[best] = counts.get(best, 0) + 1
    except Exception:
        pass

    # 3. Research: one project at a time, keep a reserve for upkeep
    try:
        if len(api.research) < 2 and budget["res"] > 300:
            for line in RESEARCH_ORDER:
                st = api.tech.get(line)
                if not st or st.get("status") != "open":
                    continue
                c = st.get("cost") or {}
                ok = True
                for k, v in c.items():
                    need = v + (200 if k == "res" else 0)
                    have = budget["res"] if k == "res" else api.stock.get(k, 0)
                    if have < need:
                        ok = False
                        break
                if ok:
                    if str(api.cmd("research %s" % line)).startswith("ok"):
                        for k, v in c.items():
                            if k in budget:
                                budget[k] -= v
                    break
    except Exception:
        pass

    # 4. Refit damaged units; send idle ones to expand or the front
    try:
        refit = set(m["refit"])
        for u in combat:
            uid = u["id"]
            if uid in refit:
                if u.get("str", 0) >= 85:
                    refit.discard(uid)
                elif u.get("prov") != capital and not u.get("path"):
                    api.cmd("move %d P%d" % (uid, capital))
            elif u.get("str", 100) < 45 and u.get("prov") != capital:
                refit.add(uid)
                api.cmd("move %d P%d" % (uid, capital))
        m["refit"] = list(refit)

        idle = [
            u for u in combat
            if not u.get("path") and u.get("state") == "ready"
            and not u.get("front") and not u.get("expand") and not u.get("explore")
            and u["id"] not in refit
        ]
        el = [u for u in idle if u.get("type") in EXPAND_TYPES]
        n_exp = 0
        if api.neutral_border:
            n_exp = min(len(el), max(2, len(el) // 2))
        exp_ids = [u["id"] for u in el[:n_exp]]
        for uid in exp_ids:
            api.cmd("expand %d" % uid)
        exp_set = set(exp_ids)
        rest = [u["id"] for u in idle if u["id"] not in exp_set]
        if rest:
            api.cmd("front %s" % ids(rest))
    except Exception:
        pass

    # 5. Prepared attacks: launch old plans, else start one well-supported plan
    try:
        alive = {u["id"]: u for u in units}
        for k in list(m["prep"].keys()):
            if now - m["prep"][k]["t"] > 60:
                del m["prep"][k]

        launched = False
        for k, pl in list(m["prep"].items()):
            if now - pl["t"] >= 10:
                live = [i for i in pl["ids"]
                        if i in alive and alive[i].get("state") in ("preparing", "ready", "defending")]
                if len(live) >= 4:
                    api.cmd("move %s P%d" % (ids(live), int(k)))
                del m["prep"][k]
                launched = True
                break

        if not launched:
            refit = set(m["refit"])
            scored = []
            for T, pv in provs.items():
                if pv.get("owner") != "enemy" or str(T) in m["prep"]:
                    continue
                if api.owner_name.get(T) in api.pacts:
                    continue
                adj = [p for p in nbrs(T) if provs.get(p, {}).get("owner") == "me"]
                if not adj:
                    continue
                e = api.enemy.get(T)
                if not e:
                    continue  # never attack blind
                scored.append((e.get("str", 0), T, adj))
            scored.sort(key=lambda x: x[0])

            for estr, T, adj in scored:
                pv = provs[T]
                tm = TERRAIN_DFN.get(pv.get("terrain"), 1.0)
                dm = tm * (1.25 if pv.get("city") else 1.0)
                dm *= 1.25 ** (pv.get("fort", 0) or 0)
                epow = estr * 0.12 * dm
                force = [
                    u for u in combat
                    if u.get("prov") in adj and u.get("str", 0) >= 60
                    and u["id"] not in refit and not u.get("path")
                    and u.get("state") in ("ready", "defending")
                    and u.get("rdy", 0) >= 60
                ]
                if len(force) < 5:
                    continue
                fpow = sum(u.get("str", 0) * api.stats.get(u["type"], {}).get("atk", 10) / 100.0
                           for u in force)
                if fpow < 3.0 * epow:
                    continue
                fids = [u["id"] for u in force]
                scouts = [u["id"] for u in units
                          if u.get("type") == "rec" and u.get("prov") in adj
                          and not u.get("path")]
                prep_ids = fids + scouts[:1]
                api.cmd("prepare %s P%d" % (ids(prep_ids), T))
                m["prep"][str(T)] = {"t": now, "ids": fids}
                break
    except Exception:
        pass

    # 6. Diplomacy: offer pacts to met factions, accept pacts offered to us
    try:
        for f in api.met:
            if f in api.pacts:
                continue
            last = m["pact_offer"].get(f, -999)
            if now - last >= 168:
                api.cmd("offer %s pact 120" % f)
                m["pact_offer"][f] = now
        for o in api.offers_in:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o.get("id"))
    except Exception:
        pass
```

```letters
to laurentia: Albion proposes peace. Let us hold a pact so neither side spends units on the other, and we can both grow. We will keep it unless you break it.
to gallia: Albion proposes peace and an open border for trade. Offer us a pact; we will honour it while you do.
```