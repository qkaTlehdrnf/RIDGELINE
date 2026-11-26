**Reasoning:** Albion has +15 experience and 10% dearer units, so the policy favours quality and avoids spamming cheap units. The loop does five things each call:

1. **Scouting:** keeps two `rec` scouts exploring.
2. **Recruiting:** a deficit-based mix of types, with a reserve kept back and a local budget so the snapshot isn't overspent.
3. **Research:** gambles on upgrade lines in a fixed priority order, only when the bank is comfortable.
4. **Refit and front:** pulls units under 35 strength back to the capital until they reach 85, sends a third of idle infantry to explore free land, and places the rest on the front.
5. **Attacks:** attacks only with a clear margin (at least 2.2x estimated power, readiness 60+). It prepares for about 12 hours, then moves in, one target per call.

Everything is wrapped in try/except, string keys are used in `api.mem`, and there are no imports.

```python
RESEARCH_ORDER = [
    "farming", "conscription", "inf.weapons", "arm.weapons", "inf.protection",
    "mining", "logistics", "drill", "medicine", "discipline", "industry",
    "mot.mobility", "fieldworks", "atg.weapons", "art.weapons", "arm.protection",
    "drilling", "refining", "staffwork", "mot.weapons", "inf.mobility",
]

TARGETS = {
    "inf": 0.34, "mot": 0.12, "mtn": 0.08, "art": 0.12, "atg": 0.08,
    "arm": 0.10, "eng": 0.04, "cav": 0.06, "grn": 0.06,
}

TERRAIN_DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}


def tick(api):
    m = api.mem
    m.setdefault("refit", [])
    m.setdefault("prep", {})
    now = api.t
    provs = api.provs
    units = api.units
    capital = api.capital
    combat = [u for u in units if u.get("type") != "rec"]

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

    # 1. Scouting
    try:
        recs = [u for u in units if u.get("type") == "rec"]
        if len(recs) < 2 and can("rec", 40.0):
            if str(api.cmd("recruit rec P%d" % capital)).startswith("ok"):
                spend("rec")
        for u in recs:
            if not u.get("path") and not u.get("explore") and not u.get("expand"):
                api.cmd("explore %d" % u["id"])
    except Exception:
        pass

    # 2. Recruiting (deficit against target mix, two per call at most)
    try:
        counts = {}
        for u in units:
            tp = u.get("type")
            counts[tp] = counts.get(tp, 0) + 1
        for _ in range(2):
            total = sum(counts.values()) + 1
            best, bd = None, 0.0
            for tp, w in TARGETS.items():
                d = w * total - counts.get(tp, 0)
                if d > bd and can(tp, 80.0):
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

    # 3. Research (gamble on lines in priority order when rich)
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

    # 4. Refit management and idle assignment
    try:
        refit = set(m["refit"])
        for u in combat:
            uid = u["id"]
            if uid in refit:
                if u.get("str", 0) >= 85:
                    refit.discard(uid)
                elif u.get("prov") != capital and not u.get("path"):
                    api.cmd("move %d P%d" % (uid, capital))
            elif u.get("str", 100) < 35 and u.get("prov") != capital:
                refit.add(uid)
                api.cmd("move %d P%d" % (uid, capital))
        m["refit"] = list(refit)

        idle = [
            u for u in combat
            if not u.get("path") and u.get("state") == "ready"
            and not u.get("front") and not u.get("expand") and not u.get("explore")
            and u["id"] not in refit
        ]

        expand_list = []
        if api.neutral_border:
            cand = [u for u in idle if u.get("type") in
                    ("inf", "mtn", "mot", "mil", "cav", "mec", "grn", "eng")]
            expand_list = cand[:4]
            for u in expand_list:
                api.cmd("expand %d" % u["id"])

        taken = set(u["id"] for u in expand_list)
        rest = [u["id"] for u in idle if u["id"] not in taken]
        if rest:
            api.cmd("front %s" % ids(rest))
    except Exception:
        pass

    # 5. Prepared attacks: launch old plans, otherwise start one new plan
    try:
        alive = {u["id"]: u for u in combat}
        for k in list(m["prep"].keys()):
            if now - m["prep"][k]["t"] > 60:
                del m["prep"][k]

        launched = False
        for k, pl in list(m["prep"].items()):
            if now - pl["t"] >= 12:
                live = [i for i in pl["ids"]
                        if i in alive and alive[i].get("state") in ("preparing", "ready", "defending")]
                if live:
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
                adj = [p for p in nbrs(T) if provs.get(p, {}).get("owner") == "me"]
                if not adj:
                    continue
                e = api.enemy.get(T)
                if not e and not pv.get("visible"):
                    continue
                estr = e.get("str", 0) if e else 0
                scored.append((estr, T, adj))
            scored.sort(key=lambda x: x[0])

            for estr, T, adj in scored:
                pv = provs[T]
                tm = TERRAIN_DFN.get(pv.get("terrain"), 1.0)
                dm = tm * (1.25 if pv.get("city") else 1.0)
                dm *= 1.25 ** (pv.get("fort", 0) or 0)
                epow = estr * 0.12 * dm
                force = [
                    u for u in combat
                    if u.get("prov") in adj and u.get("str", 0) >= 40
                    and u["id"] not in refit and not u.get("path")
                    and u.get("state") in ("ready", "defending")
                ]
                if len(force) < 3:
                    continue
                avg_r = sum(u.get("rdy", 0) for u in force) / float(len(force))
                if avg_r < 60:
                    continue
                fpow = sum(u.get("str", 0) * api.stats.get(u["type"], {}).get("atk", 10) / 100.0
                           for u in force)
                if fpow < 2.2 * epow:
                    continue
                fids = [u["id"] for u in force]
                api.cmd("prepare %s P%d" % (ids(fids), T))
                m["prep"][str(T)] = {"t": now, "ids": fids}
                break
    except Exception:
        pass
```