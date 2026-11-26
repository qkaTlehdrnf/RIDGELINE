RESEARCH_ORDER = [
    "conscription", "industry", "farming", "logistics", "drill",
    "inf.protection", "inf.weapons", "medicine", "discipline", "fieldworks",
    "atg.weapons", "art.weapons", "mot.mobility", "mining", "drilling",
    "refining", "arm.weapons", "arm.protection", "staffwork", "mot.weapons",
    "inf.mobility",
]

TARGETS = {
    "inf": 0.30, "mil": 0.04, "mot": 0.08, "mtn": 0.06, "art": 0.12,
    "atg": 0.05, "arm": 0.06, "eng": 0.06, "cav": 0.03, "grn": 0.06,
}

TERRAIN_DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
EXPAND_TYPES = ("inf", "mtn", "mot", "mil", "cav", "eng", "grn")
CONTACT_CAP = 45      # max units standing in each contact province
EXPAND_CAP = 60       # max units out expanding into neutral land
MAX_DEPOTS = 4
DEPOT_EVERY = 48
ASSAULT_RATIO = 3.0
ASSAULT_RDY = 70
MIN_FORCE = 8
PREP_HOURS = 14
PACT_EVERY = 96


def tick(api):
    m = api.mem
    m.setdefault("refit", [])
    m.setdefault("prep", {})
    m.setdefault("pact_offer", {})
    m.setdefault("depot_t", -999)
    now = api.t
    provs = api.provs
    units = api.units
    capital = api.capital
    combat = [u for u in units if u.get("type") != "rec"]
    own = [p for p, pv in provs.items() if pv.get("owner") == "me"]

    def nbrs(pid):
        out = []
        for x in provs.get(pid, {}).get("nbrs", []):
            try:
                out.append(int(str(x).strip("~P ")))
            except Exception:
                pass
        return out

    def ids(lst):
        return ",".join(str(i) for i in lst)

    # provinces of mine that touch enemy land: where the front really is
    contact = [p for p in own
               if any(provs.get(n, {}).get("owner") == "enemy" for n in nbrs(p))]

    budget = {
        "res": api.stock.get("res", 0), "mp": api.mp,
        "steel": api.stock.get("steel", 0), "oil": api.stock.get("oil", 0),
        "rare": api.stock.get("rare", 0),
    }

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

    # 1. Scouting: two recs explore for land
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

    # 2. Recruiting: only while income carries upkeep; army sized to land held
    try:
        healthy = api.income > 5 or budget["res"] > 600
        army_cap = 12 + 4 * len(own)
        if healthy:
            counts = {}
            for u in combat:
                tp = u.get("type")
                counts[tp] = counts.get(tp, 0) + 1
            mix = dict(TARGETS)
            if not api.neutral_border and not contact:
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

    # 4. Refit damaged units; expand into neutral land first; then fill the front with a cap
    try:
        refit = set(m["refit"])
        for u in combat:
            uid = u["id"]
            if uid in refit:
                if u.get("str", 0) >= 85:
                    refit.discard(uid)
                elif u.get("prov") != capital and not u.get("path"):
                    api.cmd("move %d P%d" % (uid, capital))
            elif u.get("str", 100) < 40 and u.get("prov") != capital:
                refit.add(uid)
                api.cmd("move %d P%d" % (uid, capital))
        m["refit"] = list(refit)

        idle = [
            u for u in combat
            if not u.get("path") and u.get("state") == "ready"
            and not u.get("front") and not u.get("expand") and not u.get("explore")
            and u["id"] not in refit
        ]
        expanding = sum(1 for u in combat if u.get("expand"))
        front_now = sum(1 for u in combat if u.get("front"))
        front_cap = CONTACT_CAP * len(contact)

        expand_ids, front_ids = [], []
        for u in idle:
            if api.neutral_border and u.get("type") in EXPAND_TYPES and expanding < EXPAND_CAP:
                expand_ids.append(u["id"])
                expanding += 1
            elif contact and front_now + len(front_ids) < front_cap:
                front_ids.append(u["id"])
            # otherwise the unit stays in reserve where it stands
        for uid in expand_ids:
            api.cmd("expand %d" % uid)
        if front_ids:
            api.cmd("front %s" % ids(front_ids))
    except Exception:
        pass

    # 5. Depot near the front when front supply cannot keep up with burn
    try:
        if (now - m["depot_t"] >= DEPOT_EVERY and budget["res"] > 450
                and len(api.depots) < MAX_DEPOTS and contact):
            st = api.army(1)
            fr = st.get("front") or {}
            short = fr.get("stock_mean", 999) < 300 or fr.get("inflow_per_h", 999) < fr.get("burn_per_h", 0)
            if short:
                cands = [p for p in contact
                         if provs.get(p, {}).get("supplied") and p not in api.depots and p != capital]
                if cands:
                    pick = max(cands, key=lambda p: provs[p].get("mp", 0))
                    if str(api.cmd("depot P%d 1" % pick)).startswith("ok"):
                        budget["res"] -= 150
                        m["depot_t"] = now
    except Exception:
        pass

    # 6. Prepared attacks: launch old plans, else start the best-odds plan
    try:
        alive = {u["id"]: u for u in units}
        for k in list(m["prep"].keys()):
            if now - m["prep"][k]["t"] > 60:
                del m["prep"][k]

        launched = False
        for k, pl in list(m["prep"].items()):
            if now - pl["t"] >= PREP_HOURS:
                live = [i for i in pl["ids"]
                        if i in alive and alive[i].get("state") in ("preparing", "ready", "defending")]
                if len(live) >= MIN_FORCE:
                    api.cmd("move %s P%d" % (ids(live), int(k)))
                del m["prep"][k]
                launched = True
                break

        if not launched:
            refit = set(m["refit"])
            best = None
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
                tm = TERRAIN_DFN.get(pv.get("terrain"), 1.0)
                dm = tm * (1.25 if pv.get("city") else 1.0)
                dm *= 1.25 ** (pv.get("fort", 0) or 0)
                epow = (e.get("str", 0) / 100.0) * 12.0 * dm
                force = [
                    u for u in combat
                    if u.get("prov") in adj and u.get("str", 0) >= 75
                    and u["id"] not in refit and not u.get("path")
                    and u.get("state") in ("ready", "defending")
                    and u.get("rdy", 0) >= ASSAULT_RDY
                ]
                if len(force) < MIN_FORCE:
                    continue
                fpow = 0.0
                for u in force:
                    atk = api.stats.get(u["type"], {}).get("atk", 10)
                    xp = u.get("xp", 25)
                    fpow += (u.get("str", 0) / 100.0) * atk * (0.85 + 0.35 * xp / 100.0)
                ratio = fpow / max(epow, 0.1)
                if ratio < ASSAULT_RATIO:
                    continue
                if best is None or ratio > best[0]:
                    best = (ratio, T, force)

            if best is not None:
                _, T, force = best
                fids = [u["id"] for u in force]
                api.cmd("prepare %s P%d" % (ids(fids), T))
                m["prep"][str(T)] = {"t": now, "ids": fids}
    except Exception:
        pass

    # 7. Diplomacy: pacts with factions that touch our land; accept offered pacts
    try:
        threat = set()
        for p in own:
            for n in nbrs(p):
                f = api.owner_name.get(n)
                if f and f != api.me:
                    threat.add(f)
        for f in api.met:
            if f in api.pacts or f not in threat:
                continue
            last = m["pact_offer"].get(f, -999)
            if now - last >= PACT_EVERY:
                api.cmd("offer %s pact 120" % f)
                m["pact_offer"][f] = now
        for o in api.offers_in:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o.get("id"))
    except Exception:
        pass
