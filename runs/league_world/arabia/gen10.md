**Reasoning**

Gen9 lost its last depot at day ~395 with 100% of the treasury in it. Upkeep (31,473 res) consumed most of the 39,859 earned. Recruiting only stopped once net income went below -2, which was too late. Discoveries stayed at ancient because the bank was empty, and 0 of 10 assaults on defended provinces succeeded.

Changes in this version:
- **Upkeep gate:** recruit only while net income is at least +3/day, with a 150-res reserve.
- **Depots:** spread the treasury over up to three depots (capital weighted 3) so one loss is not total.
- **Economy and research:** development starts earlier, and discoveries need net income of at least +3/day.
- **Attacks:** require a 3:1 strength ratio (the memory notes ≥3:1 mostly wins) and a model estimate of at least 0.7.

Caveat: I have not run this policy, so the thresholds are estimates.

```python
PREF = {"inf": 4.0, "mot": 4.5, "cav": 1.5, "atg": 2.0, "art": 1.5, "arm": 2.5,
        "mtn": 1.0, "eng": 1.0, "grn": 1.0, "mec": 1.0, "hvt": 0.8, "rkt": 0.5}
NEW_W = {"cav": 1.5, "art": 1.5, "atg": 2.0, "arm": 2.5, "mtn": 1.0, "eng": 1.0,
         "grn": 1.0, "mec": 1.0, "hvt": 0.8, "rkt": 0.5, "mot": 4.5, "mil": 0.5}
LAND = ("inf", "mil", "cav", "mot", "arm", "art", "atg", "eng", "mtn", "grn",
        "mec", "hvt", "rkt")
BACK = ("art", "atg", "eng", "hvt", "rkt")
LINES = ["mining", "farming", "mot.mobility", "arm.weapons", "inf.weapons",
         "logistics", "medicine", "industry", "mot.weapons", "arm.protection",
         "conscription", "drill", "discipline", "staffwork", "fieldworks",
         "refining", "drilling", "mtn.weapons", "inf.mobility"]
NEED = {"mining": "steel", "drilling": "oil", "refining": "rare"}
DISC = ["roads", "masonry", "iron_working", "horse_riding", "siege_engines",
        "stirrup", "pikes_crossbows", "hillmen", "crop_rotation", "galleys",
        "trebuchet", "castles", "banking", "sailing", "gunpowder", "matchlock",
        "steam_power", "dragoons", "grenadiers", "rifling", "railways",
        "steel_guns", "field_engineering", "combustion", "machine_guns", "tanks",
        "flight", "heavy_artillery", "anti_tank_guns", "mechanisation",
        "heavy_armour", "assault_rifles", "rocket_artillery", "navigation",
        "ironclads", "satellites", "rocketry", "composite_armour", "jet_engines",
        "carriers", "dreadnoughts", "ships_of_the_line", "submarines", "bombers",
        "ballistic_missiles", "guided_weapons"]
SCOUTS = 4
EXPLORERS = 4
MIN_FORCE = 6
DISC_RESERVE = 150
RECRUIT_RESERVE = 150
MIN_NET = 3.0
MAX_DEPOTS = 3


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _border_keys(api):
    b = api.border
    try:
        return list(b.keys())
    except Exception:
        return list(b)


def _touching(api):
    touch = set()
    for p, pr in api.provs.items():
        if pr.get("owner") != "me":
            continue
        for q in pr.get("nbrs", []):
            n = api.owner_name.get(q)
            if n:
                touch.add(n)
    return touch


def _tdfn(pr):
    t = str(pr.get("terrain", "plain"))
    if "mount" in t:
        return 2.0
    if "hill" in t:
        return 1.5
    if "forest" in t:
        return 1.25
    return 1.0


def _p_take(api, att, dfn, fort, tdfn, rdy, bonus):
    mdl = getattr(api, "model", None) or {}
    if "w" not in mdl:
        return None
    x = {"log_ratio": math.log((att + 1.0) / (dfn + 1.0)), "terrain_dfn": tdfn,
         "fort": fort, "city": 0.0, "bonus": bonus, "att_rdy": rdy / 100.0,
         "heavy_share": 0.2, "dirs": 1.0}
    s = mdl["b"]
    for i, f in enumerate(mdl["features"]):
        sd = mdl["std"][i] or 1.0
        s += mdl["w"][i] * (x.get(f, 0.0) - mdl["mean"][i]) / sd
    s = max(-30.0, min(30.0, s))
    return 1.0 / (1.0 + math.exp(-s))


def _alarm(api, ctx):
    cap = api.capital
    near = [cap] + list(api.provs.get(cap, {}).get("nbrs", []))
    if any(p in api.enemy for p in near if isinstance(p, int)):
        api.mem["alarm"] = api.t


def _diplo(api, ctx):
    m = api.mem
    t = api.t
    touch = _touching(api)
    for o in (api.offers_in or []):
        if o.get("kind") != "pact":
            continue
        hrs = o.get("hours")
        if o.get("frm") in touch and (hrs is None or hrs > 168):
            continue
        api.cmd("accept %s" % o["id"])
    pacts = api.pacts or {}
    sent = m.setdefault("pact_t", {})
    for f in (api.met or []):
        if f in pacts or f == api.me or f in touch:
            continue
        if t - sent.get(f, -999) < 72:
            continue
        sent[f] = t
        api.cmd("offer %s pact" % f)


def _depots(api, ctx):
    m = api.mem
    t = api.t
    if t - m.get("dep_t", -999) < 120 or api.res < 450:
        return
    deps = api.depots or {}
    if len(deps) >= MAX_DEPOTS:
        return
    if any((v or {}).get("opens_in") for v in deps.values()):
        return
    cap = api.capital
    border = set(ctx["border"])
    best, best_y = None, -1
    for p, pr in api.provs.items():
        if not isinstance(p, int) or p == cap or p in deps or p in border:
            continue
        if pr.get("owner") != "me" or not pr.get("supplied"):
            continue
        y = pr.get("y", 0) or 0
        if y > best_y:
            best, best_y = p, y
    if best is None:
        return
    if api.cmd("depot P%d 1" % best).startswith("ok"):
        m["dep_t"] = t
        if cap in deps:
            api.cmd("depot P%d 3" % cap)


def _discover(api, ctx):
    tree = getattr(api, "tree", None) or {}
    if not tree:
        return
    if any(v.get("status") == "researching" for v in tree.values()):
        return
    if api.income < 3:
        return
    avail = api.res - DISC_RESERVE
    for d in DISC:
        v = tree.get(d)
        if not v or v.get("status") != "open":
            continue
        need = v.get("res_now")
        if need is None:
            c = v.get("cost") or {}
            need = c.get("res", 10 ** 9) if isinstance(c, dict) else 10 ** 9
        if need > avail:
            continue
        if api.cmd("research %s" % d).startswith("ok"):
            return


def _weights(api):
    can = api.can_raise or []
    w = {}
    for k in LAND:
        if k in can:
            w[k] = PREF.get(k, NEW_W.get(k, 1.0))
    return w


def _recruit(api, ctx):
    m = api.mem
    if api.income_by.get("res", 0) < MIN_NET:
        return
    counts = {}
    for u in ctx["units"]:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    res = api.res
    mp = api.mp
    stock = api.stock
    reserve = RECRUIT_RESERVE
    cap = api.capital
    while counts.get("rec", 0) < SCOUTS:
        c = api.costs.get("rec")
        if not c or res - reserve < c[0] or mp < c[1]:
            break
        if not api.cmd("recruit rec P%d" % cap).startswith("ok"):
            break
        res -= c[0]
        mp -= c[1]
        counts["rec"] = counts.get("rec", 0) + 1
    pref = _weights(api)
    if stock.get("oil", 0) > 500 and "arm" in pref:
        pref["arm"] = 4.0
        if "mot" in pref:
            pref["mot"] = 6.0
    if stock.get("oil", 0) > 2000 and "arm" in pref:
        pref["arm"] = 5.0
    if stock.get("rare", 0) > 400 and "hvt" in pref:
        pref["hvt"] = 1.2
    if api.t - m.get("alarm", -999) <= 12:
        if "inf" in pref:
            pref["inf"] = 8.0
        if "atg" in pref:
            pref["atg"] = 3.0
    bad = set()
    n = 0
    while n < 4 and pref:
        fight = sum(counts.get(k, 0) for k in pref)
        tw = sum(pref.values())
        ranked = sorted(((w / tw * (fight + 4) - counts.get(k, 0), k)
                         for k, w in pref.items() if k not in bad), reverse=True)
        pick = None
        for d, k in ranked:
            c = api.costs.get(k)
            uc = api.unit_costs.get(k, {})
            if not c:
                continue
            if res - reserve < c[0] or mp < c[1]:
                continue
            if any(stock.get(s, 0) < uc.get(s, 0) for s in ("steel", "oil", "rare")):
                continue
            pick = k
            break
        if pick is None:
            break
        if not api.cmd("recruit %s P%d" % (pick, cap)).startswith("ok"):
            bad.add(pick)
            continue
        c = api.costs[pick]
        res -= c[0]
        mp -= c[1]
        counts[pick] = counts.get(pick, 0) + 1
        n += 1


def _research(api, ctx):
    t = api.t
    slots = 2 - len(api.research or [])
    if t < 96:
        slots = min(slots, 1)
    if slots <= 0:
        return
    running = [r[0] for r in (api.research or [])]
    avail = dict(api.stock)
    resv = 100
    for line in LINES:
        if slots <= 0:
            break
        if line in running:
            continue
        info = api.tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost")
        if not cost:
            continue
        need = NEED.get(line)
        if need and api.income_by.get(need, 0) <= 0:
            continue
        if api.income_by.get("res", 0) < MIN_NET:
            break
        good = True
        for k, v in cost.items():
            r = resv if k == "res" else 0
            if avail.get(k, 0) - r < v:
                good = False
                break
        if not good:
            continue
        if api.cmd("research %s" % line).startswith("ok"):
            for k, v in cost.items():
                avail[k] = avail.get(k, 0) - v
            slots -= 1
            running.append(line)


def _econ(api, ctx):
    if api.res < 250:
        return
    eco = getattr(api, "economy", None) or {}
    rows = sorted(eco.get("provs", []) or [], key=lambda r: -r.get("yield_now", 0))
    n = 0
    for r in rows:
        if n >= 3 or api.res < 250:
            break
        if r.get("can_dev") and r.get("dev", 0) + 1 <= r.get("room", 0):
            if api.cmd("develop P%d" % r["prov"]).startswith("ok"):
                n += 1
    if api.res < 500:
        return
    for r in rows:
        if n >= 5:
            break
        if r.get("can_infra") and r.get("infra", 0) < 1:
            if api.cmd("build P%d" % r["prov"]).startswith("ok"):
                n += 1


def _scouts(api, ctx):
    m = api.mem
    t = api.t
    ids = []
    for u in ctx["units"]:
        if u["type"] != "rec" or u.get("path") or u.get("explore"):
            continue
        key = str(u["id"])
        if t - m["xp"].get(key, -99) < 24:
            continue
        m["xp"][key] = t
        ids.append(u["id"])
    if ids:
        api.cmd("explore %s" % _sel(ids))
    if not api.unexplored:
        return
    active = sum(1 for u in ctx["units"] if u.get("explore") and u["type"] != "rec")
    need = EXPLORERS - active
    if need <= 0:
        return
    picks = []
    for u in ctx["units"]:
        if len(picks) >= need:
            break
        if u["type"] == "rec" or u["type"] in BACK:
            continue
        if u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
            continue
        if u.get("fighting") or u.get("state") != "ready" or u.get("str", 0) < 60:
            continue
        picks.append(u["id"])
    if picks:
        api.cmd("explore %s" % _sel(picks))


def _attacks(api, ctx):
    m = api.mem
    t = api.t
    plans = m["plan"]
    pacts = api.pacts or {}
    for key in list(plans.keys()):
        src, t0, ids = plans[key]
        q = int(key)
        pq = api.provs.get(q, {})
        alive = [u for u in ctx["units"]
                 if u["id"] in ids and u["prov"] == src and not u.get("path")]
        if pq.get("owner") == "me" or not alive or t - t0 > 48:
            del plans[key]
            continue
        if t - t0 >= 12 and len(alive) >= MIN_FORCE:
            ready_ids = [u["id"] for u in alive if u.get("rdy", 0) >= 65]
            if len(ready_ids) >= MIN_FORCE:
                g = "g%d_%d" % (q, t)
                api.cmd("group %s %s" % (g, _sel(ready_ids)))
                api.cmd("move %s P%d" % (g, q))
                del plans[key]
                continue
            if t - t0 > 36:
                del plans[key]
    if len(plans) >= 2:
        return
    busy = set(int(k) for k in plans)
    for p in ctx["border"]:
        pr = api.provs.get(p)
        if not pr or pr.get("owner") != "me":
            continue
        force = [u for u in ctx["byprov"].get(p, [])
                 if u["type"] != "rec" and u.get("state") in ("ready", "preparing")
                 and u.get("plan", -1) == -1 and not u.get("path")
                 and u.get("str", 0) >= 60 and u.get("rdy", 0) >= 65]
        if len(force) < MIN_FORCE:
            continue
        force.sort(key=lambda u: -u.get("str", 0))
        force = force[:12]
        mine = sum(u.get("str", 0) for u in force)
        avg_rdy = sum(u.get("rdy", 0) for u in force) / len(force)
        for q in pr.get("nbrs", []):
            if not isinstance(q, int) or q in busy:
                continue
            qp = api.provs.get(q)
            if not qp or qp.get("owner") != "enemy" or qp.get("harsh"):
                continue
            if api.owner_name.get(q) in pacts:
                continue
            e = api.enemy.get(q)
            es = e.get("str", 0) if e else 60
            fort = qp.get("fort", 0) or 0
            if mine < 3.0 * es + 150 + 100 * fort:
                continue
            p_take = _p_take(api, mine, es, fort, _tdfn(qp), avg_rdy, 0.0)
            if p_take is not None and p_take < 0.7:
                continue
            ids = [u["id"] for u in force]
            api.cmd("prepare %s P%d" % (_sel(ids), q))
            plans[str(q)] = [p, t, ids]
            busy.add(q)
            break
        if len(plans) >= 2:
            return


def _assign(api, ctx):
    nb = api.neutral_border or []
    contact = len(api.enemy or {}) > 0
    front_quota = 2 * len(ctx["border"]) if contact else 0
    front_now = sum(1 for u in ctx["units"] if u.get("front"))
    front, expand = [], []
    planned = set()
    for key, plan in ctx["plans"].items():
        planned.update(plan[2])
    for u in ctx["units"]:
        if u["type"] == "rec" or u.get("path") or u["id"] in planned:
            continue
        if u.get("expand") or u.get("front") or u.get("explore") or u.get("fighting"):
            continue
        if u.get("state") != "ready" or u.get("plan", -1) != -1:
            continue
        if u.get("str", 0) < 60 or u.get("old"):
            continue
        if len(front) + len(expand) >= 80:
            break
        want_front = front_now + len(front) < front_quota
        if want_front or not nb:
            front.append(u["id"])
        else:
            expand.append(u["id"])
    if front:
        api.cmd("front %s" % _sel(front))
    if expand:
        api.cmd("expand %s" % _sel(expand))


def _refit(api, ctx):
    m = api.mem
    t = api.t
    if t - m.get("refit_t", -99) < 12:
        return
    if api.res < 300:
        return
    rc = getattr(api, "refit_cost", {}) or {}
    own = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    border = set(ctx["border"])
    spend = {}
    ids = []
    for u in ctx["units"]:
        if len(ids) >= 12:
            break
        if not u.get("old") or u.get("path") or u.get("fighting"):
            continue
        if u.get("state") != "ready" or u.get("prov") not in own or u.get("prov") in border:
            continue
        if not u.get("supplied", True):
            continue
        c = rc.get(u["type"])
        if not c:
            continue
        ok = True
        for k in ("res", "steel", "oil", "rare"):
            need = spend.get(k, 0) + c.get(k, 0)
            if need > api.stock.get(k, 0) - (250 if k == "res" else 0):
                ok = False
                break
        if not ok:
            continue
        for k in ("res", "steel", "oil", "rare"):
            spend[k] = spend.get(k, 0) + c.get(k, 0)
        ids.append(u["id"])
    if ids:
        m["refit_t"] = t
        api.cmd("refit %s" % _sel(ids))


def _retreat(api, ctx):
    m = api.mem
    t = api.t
    cap = api.capital
    if cap is None:
        return
    planned = set()
    for key, plan in ctx["plans"].items():
        planned.update(plan[2])
    ids = []
    for u in ctx["units"]:
        if u["type"] == "rec" or u.get("path") or u.get("front") or u["id"] in planned:
            continue
        if u.get("str", 100) >= 25 or u["prov"] == cap:
            continue
        key = str(u["id"])
        if t - m["retreat"].get(key, -99) < 12:
            continue
        m["retreat"][key] = t
        ids.append(u["id"])
    if ids:
        api.cmd("move %s P%d" % (_sel(ids), cap))


def _fort(api, ctx):
    m = api.mem
    t = api.t
    for p in ctx["border"]:
        key = str(p)
        if t - m["fort"].get(key, -99) < 48:
            continue
        pr = api.provs.get(p, {})
        if (pr.get("fort", 0) or 0) >= 3:
            continue
        ids = [u["id"] for u in ctx["byprov"].get(p, [])
               if u["type"] == "eng" and not u.get("path") and u.get("state") != "digging"]
        if ids:
            m["fort"][key] = t
            api.cmd("fortify %s" % _sel(ids))


def tick(api):
    m = api.mem
    m.setdefault("plan", {})
    m.setdefault("retreat", {})
    m.setdefault("fort", {})
    m.setdefault("xp", {})
    m.setdefault("alarm", -999)
    m.setdefault("refit_t", -99)
    m.setdefault("dep_t", -999)
    m.setdefault("pact_t", {})
    m.setdefault("err", 0)
    units = list(api.units)
    byprov = {}
    for u in units:
        byprov.setdefault(u["prov"], []).append(u)
    ctx = {"units": units, "byprov": byprov, "border": _border_keys(api),
           "plans": m["plan"]}
    for fn in (_alarm, _diplo, _depots, _discover, _recruit, _research, _econ,
               _scouts, _attacks, _assign, _refit, _retreat, _fort):
        try:
            fn(api, ctx)
        except Exception:
            m["err"] = m.get("err", 0) + 1
```

```feedback
The biggest loss in the last war was upkeep: units cost 31k of 40k res earned and the bank hit zero, and the policy only saw the problem at net -2/day. A per-unit upkeep forecast (what the next recruit adds to net income per day) would help. Depot loss took 100% of the treasury; a line in q budget or api.depots showing treasury at risk per depot would make spreading it easier. Per-assault odds from api.model were not very predictive for us; a fitted model on the unit's own factions would help.
```

REVIEW: standard