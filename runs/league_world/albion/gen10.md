**Reasoning.** The last war ended with 0 provinces and elimination. The main causes in the review are an upkeep drain (about 40k spent on upkeep against 25k earned, with negative income for most of the war), recruiting that kept running while income was negative, and 73 refused `explore` orders for units at sea. The rewrite keeps the economy, research, front and assault logic and changes four things:

1. Recruiting is gated by the upkeep ratio (`api.budget["upkeep_units"]` against income), with the check repeated after each recruit, so the army stops growing before it bankrupts the purse.
2. Units at sea or of non-land domain are excluded from the land lists, so `explore`/`expand`/`front` are no longer refused.
3. Galleys come earlier in the discovery order, since Albion is an island and needs sea reach.
4. Recs are only sent to explore when on land.

I have not tested this against the engine, so it is a reasoned change rather than a verified improvement.

```python
RESEARCH_ORDER = [
    "conscription", "industry", "farming", "logistics", "drill",
    "inf.protection", "inf.weapons", "medicine", "discipline", "fieldworks",
    "atg.weapons", "art.weapons", "mot.mobility", "mining", "drilling",
    "refining", "arm.weapons", "arm.protection", "staffwork", "mot.weapons",
    "inf.mobility",
]

# discoveries, economy first, then military; locked ones are skipped by status
DISC_ORDER = [
    "roads", "masonry", "iron_working", "galleys", "crop_rotation",
    "horse_riding", "pikes_crossbows", "siege_engines", "castles", "stirrup",
    "banking", "hillmen", "trebuchet", "sailing", "gunpowder", "matchlock",
    "steam_power", "railways", "rifling", "steel_guns", "field_engineering",
    "combustion", "machine_guns", "tanks", "flight", "heavy_artillery",
    "assault_rifles", "mechanisation", "navigation", "ironclads", "carriers",
]

TARGETS = {
    "inf": 0.30, "mil": 0.04, "mot": 0.08, "mtn": 0.06, "art": 0.12,
    "atg": 0.05, "arm": 0.06, "eng": 0.06, "cav": 0.03, "grn": 0.06,
}

TERRAIN_DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
EXPAND_TYPES = ("inf", "mtn", "mot", "mil", "cav", "eng", "grn")
HEAVY = ("art", "eng", "arm")
EXPAND_CAP = 60
CONTACT_MIN = 6
CONTACT_CAP = 40
ARMY_BASE = 20
ARMY_PER_PROV = 6
MAX_DEPOTS = 5
DEPOT_EVERY = 48
ASSAULT_RATIO = 3.0
ASSAULT_P = 0.5
ASSAULT_RDY = 70
MIN_FORCE = 8
PREP_HOURS = 14
PACT_EVERY = 96
ACCESS_EVERY = 120
REST_BELOW = 30
REST_UNTIL = 75
DEV_RESERVE = 300
DISC_RESERVE = 150
RECRUIT_NET = 6.0       # recruit only while net income per day stays above this
UNIT_UPKEEP = 0.1       # rough upkeep added per new unit per day
UPKEEP_SHARE = 0.5      # unit upkeep may not exceed this share of income

# logistic model of 'this assault takes the province' (from api.model defaults)
TAKE_W = [1.1911, -0.275, -0.3529, 0.0081, 0.7296, 0.8341, -0.6001, 1.1763]
TAKE_B = -1.2756
TAKE_MEAN = [0.7328, 1.3633, 0.9561, 0.1624, 0.0369, 0.1156, 0.6737, 2.1411]
TAKE_STD = [1.6387, 0.3925, 1.2109, 0.3688, 0.1131, 0.2127, 0.3452, 1.4387]


def take_prob(feat):
    z = TAKE_B
    for i in range(8):
        z += TAKE_W[i] * (feat[i] - TAKE_MEAN[i]) / TAKE_STD[i]
    if z > 30:
        z = 30
    if z < -30:
        z = -30
    return 1.0 / (1.0 + math.exp(-z))


def tick(api):
    m = api.mem
    m.setdefault("rest", [])
    m.setdefault("prep", {})
    m.setdefault("pact_offer", {})
    m.setdefault("access_offer", {})
    m.setdefault("depot_t", -999)
    m.setdefault("dev_t", -999)
    now = api.t
    provs = api.provs
    units = api.units
    capital = api.capital

    def on_land(u):
        return u.get("dom", 0) == 0 and not u.get("at_sea")

    land_units = [u for u in units if on_land(u)]
    combat = [u for u in land_units if u.get("type") != "rec"]
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

    def is_enemy(p):
        return provs.get(p, {}).get("owner") == "enemy"

    contact = [p for p in own if any(is_enemy(n) for n in nbrs(p))]
    contact_set = set(contact)

    cap = {}
    for p in contact:
        flow = provs[p].get("flow", 5.0) or 5.0
        cap[p] = max(CONTACT_MIN, min(CONTACT_CAP, int(flow * 20)))
    front_cap = sum(cap.values())

    budget = {
        "res": api.stock.get("res", 0), "mp": api.mp,
        "steel": api.stock.get("steel", 0), "oil": api.stock.get("oil", 0),
        "rare": api.stock.get("rare", 0),
    }

    try:
        upk = float((api.budget or {}).get("upkeep_units", 0) or 0)
    except Exception:
        upk = 0.0

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

    # 1. Scouting: two recs on land explore for land
    try:
        recs = [u for u in land_units if u.get("type") == "rec"]
        if len(recs) < 2 and can("rec", 60.0) and upk < UPKEEP_SHARE * max(api.income, 1.0):
            if str(api.cmd("recruit rec P%d" % capital)).startswith("ok"):
                spend("rec")
                upk += UNIT_UPKEEP
        for u in recs:
            if (not u.get("path") and not u.get("explore") and not u.get("expand")
                    and u.get("state") == "ready"):
                api.cmd("explore %d" % u["id"])
    except Exception:
        pass

    # 2. Recruiting: only while income is positive and unit upkeep stays a
    #    modest share of income (bankruptcy ended the last war)
    try:
        rich = budget["res"] > 1500
        army_cap = ARMY_BASE + ARMY_PER_PROV * len(own)
        counts = {}
        for u in combat:
            tp = u.get("type")
            counts[tp] = counts.get(tp, 0) + 1
        mix = {tp: w for tp, w in TARGETS.items() if tp in api.costs}
        if not api.neutral_border and not contact:
            mix["mil"] = 0.0
        for _ in range(3):
            if not (api.income > RECRUIT_NET or rich):
                api.count("recruit_paused_income", 1)
                break
            if upk >= UPKEEP_SHARE * max(api.income, 1.0):
                api.count("recruit_paused_upkeep", 1)
                break
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
            upk += UNIT_UPKEEP
            counts[best] = counts.get(best, 0) + 1
    except Exception:
        pass

    # 3. Research: discoveries first, upgrades in the other slot
    try:
        started = False
        if len(api.research) < 2 and budget["res"] > 200:
            for d in DISC_ORDER:
                t = api.tree.get(d) or {}
                if t.get("status") != "open":
                    continue
                c = t.get("cost") or {}
                need = float(t.get("res_now") or c.get("res", 0) or 0)
                if budget["res"] >= need + DISC_RESERVE:
                    if str(api.cmd("research %s" % d)).startswith("ok"):
                        budget["res"] -= need
                        started = True
                        api.count("discovery_started", 1)
                break  # save up for the first open discovery in order

        if not started and len(api.research) < 2 and budget["res"] > 300:
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

    # 4. Rest exhausted units; cap each contact province; fill the front within caps
    try:
        rest = set(m["rest"])
        rest &= set(u["id"] for u in combat)
        for u in combat:
            uid = u["id"]
            p = u.get("prov")
            moving = bool(u.get("path"))
            if uid in rest:
                if u.get("rdy", 0) >= REST_UNTIL and u.get("str", 0) >= 70:
                    rest.discard(uid)
                elif p != capital and not moving:
                    api.cmd("move %d P%d" % (uid, capital))
            elif (p in contact_set and not moving
                  and (u.get("rdy", 100) < REST_BELOW or u.get("str", 100) < 40)):
                rest.add(uid)
                api.cmd("move %d P%d" % (uid, capital))

        front_by = {}
        for u in combat:
            p = u.get("prov")
            if p in contact_set and u.get("front") and u["id"] not in rest:
                front_by.setdefault(p, []).append(u)
        for p, lst in front_by.items():
            over = len(lst) - cap.get(p, CONTACT_MIN)
            if over > 0:
                lst.sort(key=lambda u: u.get("rdy", 0))
                for u in lst[:over]:
                    if u.get("path"):
                        continue
                    rest.add(u["id"])
                    api.cmd("move %d P%d" % (u["id"], capital))
        m["rest"] = list(rest)

        idle = [
            u for u in combat
            if not u.get("path") and u.get("state") == "ready"
            and not u.get("front") and not u.get("expand") and not u.get("explore")
            and u["id"] not in rest
        ]
        expanding = sum(1 for u in combat if u.get("expand"))
        front_all = sum(1 for u in combat if u.get("front"))
        room = front_cap - front_all
        expand_ids, front_ids = [], []
        for u in idle:
            if api.neutral_border and u.get("type") in EXPAND_TYPES and expanding < EXPAND_CAP:
                expand_ids.append(u["id"])
                expanding += 1
            elif contact and room > 0 and u.get("rdy", 0) >= 60:
                front_ids.append(u["id"])
                room -= 1
        if expand_ids:
            api.cmd("expand %s" % ids(expand_ids))
        if front_ids:
            api.cmd("front %s" % ids(front_ids))
    except Exception:
        pass

    # 5. Economy: only spend while net income is healthy
    try:
        eco = api.economy if isinstance(api.economy, dict) else {}
        works = eco.get("works", []) or []
        rows = eco.get("provs", []) or []
        healthy = api.income > RECRUIT_NET
        if (healthy and len(works) < 3 and now - m["dev_t"] >= 6
                and budget["res"] > DEV_RESERVE):
            done = False
            for pv in rows:
                p = pv.get("prov")
                if p is None or p in contact_set or pv.get("dev", 0) >= 4:
                    continue
                lvl = pv.get("dev", 0) + 1
                if budget["res"] >= 50 * lvl + DEV_RESERVE and api.stock.get("coal", 0) >= 8 * lvl:
                    if str(api.cmd("develop P%d" % p)).startswith("ok"):
                        m["dev_t"] = now
                        done = True
                    break
            if not done:
                for pv in rows:
                    p = pv.get("prov")
                    if p is None or p in contact_set or pv.get("dev", 0) < 2 or pv.get("infra", 0) >= 2:
                        continue
                    lvl = pv.get("infra", 0) + 1
                    if budget["res"] >= 30 * lvl + DEV_RESERVE and api.stock.get("steel", 0) >= 6 * lvl:
                        if str(api.cmd("build P%d" % p)).startswith("ok"):
                            m["dev_t"] = now
                        break
    except Exception:
        pass

    # 6. Depot near the front when front supply cannot keep up with burn
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

    # 7. Prepared attacks: launch old plans, else start the best plan that passes both gates
    try:
        alive = {u["id"]: u for u in units}
        for k in list(m["prep"].keys()):
            if now - m["prep"][k]["t"] > 60:
                del m["prep"][k]

        launched = False
        for k, pl in list(m["prep"].items()):
            if now - pl["t"] >= PREP_HOURS:
                live = [i for i in pl["ids"]
                        if i in alive and alive[i].get("state") in ("preparing", "ready", "defending")
                        and alive[i].get("rdy", 0) >= 50]
                if len(live) >= MIN_FORCE:
                    api.cmd("move %s P%d" % (ids(live), int(k)))
                del m["prep"][k]
                launched = True
                break

        if not launched:
            rest = set(m["rest"])
            avail = {}
            for u in combat:
                if (u.get("str", 0) >= 75 and u.get("rdy", 0) >= ASSAULT_RDY and not u.get("path")
                        and u.get("state") in ("ready", "defending") and u["id"] not in rest):
                    avail.setdefault(u.get("prov"), []).append(u)
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
                force = []
                for p in adj:
                    force.extend(avail.get(p, []))
                if len(force) < MIN_FORCE:
                    continue
                tm = TERRAIN_DFN.get(pv.get("terrain"), 1.0)
                dm = tm * (1.25 if pv.get("city") else 1.0) * (1.25 ** (pv.get("fort", 0) or 0))
                uncertain = 1.0 if e.get("exact") else 1.3
                epow = (e.get("str", 0) / 100.0) * 12.0 * dm * uncertain
                fpow = 0.0
                tot_str = 0.0
                for u in force:
                    atk = api.stats.get(u["type"], {}).get("atk", 10)
                    xp = u.get("xp", 25)
                    fpow += (u.get("str", 0) / 100.0) * atk * (0.85 + 0.35 * xp / 100.0)
                    tot_str += u.get("str", 0)
                ratio = fpow / max(epow, 0.1)
                if ratio < ASSAULT_RATIO:
                    continue
                n = len(force)
                feat = [
                    math.log((tot_str + 1.0) / (e.get("str", 0) + 1.0)),
                    tm,
                    float(pv.get("fort", 0) or 0),
                    1.0 if pv.get("city") else 0.0,
                    0.14,
                    sum(u.get("rdy", 0) for u in force) / (100.0 * n),
                    sum(1 for u in force if u.get("type") in HEAVY) / float(n),
                    float(len(set(u.get("prov") for u in force))),
                ]
                pt = take_prob(feat)
                if pt < ASSAULT_P:
                    api.count("plan_skipped_low_odds", 1)
                    continue
                if best is None or pt > best[0]:
                    best = (pt, T, force)

            if best is not None:
                _, T, force = best
                fids = [u["id"] for u in force]
                api.cmd("prepare %s P%d" % (ids(fids), T))
                m["prep"][str(T)] = {"t": now, "ids": fids}
                api.count("plan_started", 1)
    except Exception:
        pass

    # 8. Diplomacy: pacts with factions that touch our land; access; accept offers
    try:
        touch = set()
        for p in own:
            for n in nbrs(p):
                f = api.owner_name.get(n)
                if f and f != api.me:
                    touch.add(f)
        for f in api.met:
            if f in api.pacts or f not in touch:
                continue
            last = m["pact_offer"].get(f, -999)
            if now - last >= PACT_EVERY:
                api.cmd("offer %s pact 120" % f)
                m["pact_offer"][f] = now
        for f in list(api.pacts.keys()):
            if f in touch and now - m["access_offer"].get(f, -999) >= ACCESS_EVERY:
                api.cmd("offer %s access" % f)
                m["access_offer"][f] = now
        for o in api.offers_in:
            if o.get("kind") in ("pact", "alliance", "access"):
                api.cmd("accept %s" % o.get("id"))
    except Exception:
        pass
```

```feedback
Useful: api.budget with upkeep_units and days_of_net_income; it let me gate recruiting on upkeep. Cost: explore/expand/front are refused for ships and troops at sea (73 refusals last war), so a filter on at_sea and dom would help; the refusal could say which units were skipped. Also unclear: whether api.budget upkeep is per day (I assumed yes). A short per-war summary of how many units were lost to bankruptcy decay would help me judge purse management.
```

REVIEW: standard