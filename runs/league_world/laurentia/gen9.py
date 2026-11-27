RESEARCH = ["farming", "mining", "logistics", "conscription", "drilling",
            "inf.weapons", "art.weapons", "arm.weapons", "atg.weapons",
            "inf.protection", "industry", "mot.mobility",
            "drill", "medicine", "discipline", "fieldworks", "staffwork",
            "arm.protection", "mtn.weapons", "grn.weapons", "rkt.weapons",
            "hvt.weapons", "mot.weapons", "refining", "mec.weapons"]

# discoveries in the order the tree allows (cheap and early first)
DISCOVERIES = ["iron_working", "horse_riding", "siege_engines", "masonry",
               "roads", "galleys", "stirrup", "pikes_crossbows", "hillmen",
               "crop_rotation", "trebuchet", "castles", "sailing",
               "gunpowder", "matchlock", "banking", "navigation",
               "dragoons", "grenadiers", "steam_power", "rifling",
               "field_engineering", "steel_guns", "railways", "combustion",
               "machine_guns", "ironclads", "tanks", "anti_tank_guns",
               "heavy_artillery", "flight", "bombers", "submarines",
               "dreadnoughts", "mechanisation", "heavy_armour",
               "rocket_artillery", "assault_rifles", "jet_engines",
               "carriers", "rocketry", "satellites", "ballistic_missiles",
               "guided_weapons", "composite_armour", "ships_of_the_line"]
DISC_SET = set(DISCOVERIES)

MIX_LOW = [("inf", 0.28), ("mil", 0.04), ("mtn", 0.09), ("grn", 0.07),
           ("art", 0.12), ("atg", 0.06), ("arm", 0.08), ("mot", 0.06),
           ("rkt", 0.06), ("eng", 0.05), ("cav", 0.03), ("rec", 0.03),
           ("hvt", 0.03)]

MIX_HIGH = [("inf", 0.22), ("mil", 0.03), ("mtn", 0.08), ("grn", 0.07),
            ("art", 0.14), ("atg", 0.08), ("arm", 0.10), ("mot", 0.06),
            ("rkt", 0.07), ("eng", 0.05), ("cav", 0.02), ("rec", 0.03),
            ("hvt", 0.05)]

HEAVY = ("arm", "hvt", "art", "atg", "rkt", "eng")
BUSY = ("moving", "routing", "shaken", "pinned", "preparing", "assault")
RESERVE = 300
VALUE = {"res": 1.0, "steel": 3.0, "oil": 3.0, "rare": 6.0, "mp": 0.0}
MAX_DEPOTS = 7
UNIT_CAP_MAX = 3000


def _int(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float):
        return int(x)
    if isinstance(x, str):
        d = "".join(ch for ch in x if ch.isdigit())
        return int(d) if d else None
    if isinstance(x, dict):
        return _int(x.get("id"))
    return None


def _f(d, k):
    try:
        return float(d.get(k, 0) or 0)
    except Exception:
        return 0.0


def _value(d):
    s = 0.0
    for k, v in (d or {}).items():
        try:
            s += VALUE.get(k, 1.0) * float(v)
        except Exception:
            pass
    return s


def _enemy_at(enemy, q):
    return enemy.get(q) or enemy.get("P%d" % q) or {}


def _mix(api):
    st = api.stock or {}
    if _f(st, "steel") >= 300 and _f(st, "oil") >= 100:
        return MIX_HIGH
    return MIX_LOW


def _diplomacy(api, m):
    t = api.t
    for o in list(api.offers_in or []):
        oid = o.get("id")
        if oid is None:
            continue
        kind = o.get("kind")
        if kind == "pact":
            api.cmd("accept %s" % oid)
        elif kind == "trade":
            give = o.get("you_give") or {}
            get = o.get("they_give") or {}
            if "mp" in give:
                api.cmd("reject %s" % oid)
            elif _value(get) >= _value(give):
                api.cmd("accept %s" % oid)
            else:
                api.cmd("reject %s" % oid)
    pacts = api.pacts or {}
    sent = m.setdefault("pact_sent", {})
    outs = set()
    for o in list(api.offers_out or []):
        outs.add(o.get("to"))
    for f in list(api.met or []):
        p = pacts.get(f)
        active = bool(p) and not p.get("broken_by") and (
            p.get("ends") is None or p.get("ends") > t + 12)
        if active or f in outs:
            continue
        if t - sent.get(f, -999) < 48:
            continue
        api.cmd("offer %s pact 480" % f)
        sent[f] = t


def _recruit(api, counts, total):
    t = api.t
    st = api.stock or {}
    inc = api.income_by or {}
    res = _f(st, "res")
    mp = float(api.mp or 0)
    steel = _f(st, "steel")
    oil = _f(st, "oil")
    rare = _f(st, "rare")
    cap = 200 + 40 * (t // 24) + int(max(0.0, res - 6000.0) // 120)
    cap = min(cap, UNIT_CAP_MAX)
    if total >= cap:
        return 0
    if _f(inc, "res") < 0 and res < 1500:
        return 0
    mix = _mix(api)
    done = 0
    for _ in range(24):
        best = None
        bestdef = -1e9
        for typ, frac in mix:
            c = api.unit_costs.get(typ)
            if not c:
                continue  # not raisable yet (tree not reached)
            if (res < _f(c, "res") + RESERVE or mp < _f(c, "mp")
                    or steel < _f(c, "steel") or oil < _f(c, "oil")
                    or rare < _f(c, "rare")):
                continue
            deficit = frac * (total + 1) - counts.get(typ, 0)
            if deficit > bestdef:
                bestdef = deficit
                best = typ
        if best is None:
            break
        r = api.cmd("recruit %s P%d" % (best, api.capital))
        if not str(r).startswith("ok"):
            break
        c = api.unit_costs[best]
        res -= _f(c, "res")
        mp -= _f(c, "mp")
        steel -= _f(c, "steel")
        oil -= _f(c, "oil")
        rare -= _f(c, "rare")
        counts[best] = counts.get(best, 0) + 1
        total += 1
        done += 1
        if total >= cap:
            break
    return done


def _research(api):
    if len(api.research or []) >= 2:
        return
    st = api.stock or {}
    tree = api.tree or {}
    disc_busy = any(r and r[0] in DISC_SET for r in (api.research or []))
    # 1) discoveries first, in tree order, one at a time
    if not disc_busy:
        for d in DISCOVERIES:
            info = tree.get(d)
            if not info or info.get("status") != "open":
                continue
            cost = info.get("cost") or {}
            if _f(st, "res") - _f(cost, "res") < 150:
                continue
            r = api.cmd("research %s" % d)
            if str(r).startswith("ok"):
                return
    # 2) upgrade lines use the remaining slot only when no discovery waits
    if len(api.research or []) >= 1 and disc_busy:
        return
    for line in RESEARCH:
        info = api.tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost") or {}
        if any(_f(st, k) < _f(cost, k) for k in ("res", "steel", "oil", "rare")):
            continue
        if _f(st, "res") - _f(cost, "res") < 200:
            continue
        r = api.cmd("research %s" % line)
        if str(r).startswith("ok"):
            return


def _economy(api, m):
    t = api.t
    if t - m.get("eco_t", -999) < 12:
        return
    st = api.stock or {}
    res = _f(st, "res")
    if res < 2500:
        return
    eco = api.economy or {}
    works = eco.get("works") or []
    busy = set()
    for w in works:
        try:
            busy.add(_int(w[1]))
        except Exception:
            pass
    slots = 4 - len(works)
    if slots <= 0:
        return
    m["eco_t"] = t
    tried = 0
    provs = eco.get("provs") or []
    for pr in provs:
        if slots <= 0 or tried >= 8:
            break
        p = _int(pr.get("prov"))
        if p is None or p in busy:
            continue
        if _f(pr, "dev") >= 6 or _f(pr, "room") <= 0.05:
            continue
        tried += 1
        r = api.cmd("develop P%d" % p)
        if str(r).startswith("ok"):
            slots -= 1
            busy.add(p)
            api.count("develop")
    steel = _f(st, "steel")
    if slots <= 0 or steel < 400:
        return
    for pr in provs:
        if slots <= 0 or tried >= 12:
            break
        p = _int(pr.get("prov"))
        if p is None or p in busy:
            continue
        if _f(pr, "infra") >= 3:
            continue
        tried += 1
        r = api.cmd("build P%d" % p)
        if str(r).startswith("ok"):
            slots -= 1
            busy.add(p)
            api.count("build")


def _depots(api, m):
    t = api.t
    if t - m.get("dep_t", -999) < 36:
        return
    deps = api.depots or {}
    if len(deps) >= MAX_DEPOTS:
        return
    over = False
    for k, d in deps.items():
        cap = _f(d, "capacity")
        load = _f(d, "load")
        if load > 25 or (cap > 0 and load > 0.7 * cap):
            over = True
    if not over:
        return
    st = api.stock or {}
    if _f(st, "res") < 400:
        return
    have = [_int(k) for k in deps.keys()]
    have = [h for h in have if h is not None]
    hpts = []
    for h in have:
        pr = api.provs.get(h) or {}
        try:
            hpts.append((float(pr.get("x", 0) or 0), float(pr.get("y0", 0) or 0)))
        except Exception:
            pass
    best = None
    for p, pr in api.provs.items():
        if pr.get("owner") != "me" or not pr.get("supplied"):
            continue
        if pr.get("city") or p in have:
            continue
        nown = 0
        for n in pr.get("nbrs", []):
            npv = api.provs.get(_int(n)) or {}
            if npv.get("owner") == "me":
                nown += 1
        if nown < 2:
            continue
        try:
            x = float(pr.get("x", 0) or 0)
            y = float(pr.get("y0", 0) or 0)
        except Exception:
            continue
        dmin = 1e9
        for hx, hy in hpts:
            dmin = min(dmin, math.hypot(x - hx, y - hy))
        if not hpts:
            dmin = 0.0
        score = dmin + 0.5 * nown
        if best is None or score > best[0]:
            best = (score, p)
    if best is None:
        return
    r = api.cmd("depot P%d 1" % best[1])
    if str(r).startswith("ok"):
        m["dep_t"] = t
        api.count("depot_open")


def _refit(api, units):
    if not (api.old_units or 0):
        return
    rc = api.refit_cost or {}
    border = set(_int(k) for k in (api.border or {}).keys())
    st = api.stock or {}
    res = _f(st, "res")
    steel = _f(st, "steel")
    oil = _f(st, "oil")
    rare = _f(st, "rare")
    ids = []
    for u in units:
        if not u.get("old") or u.get("path") or u.get("fighting"):
            continue
        if u.get("state") != "ready" or _int(u.get("prov")) in border:
            continue
        if u.get("rdy", 0) < 50 or u.get("str", 0) < 50:
            continue
        c = rc.get(u.get("type"))
        if not c:
            continue
        if (res - _f(c, "res") < 150 or steel < _f(c, "steel")
                or oil < _f(c, "oil") or rare < _f(c, "rare")):
            continue
        res -= _f(c, "res")
        steel -= _f(c, "steel")
        oil -= _f(c, "oil")
        rare -= _f(c, "rare")
        ids.append(u["id"])
        if len(ids) >= 240:
            break
    for i in range(0, len(ids), 25):
        api.cmd("refit " + ",".join(str(x) for x in ids[i:i + 25]))


def _pmodel(api, lst, qp, ms, es, avg_rdy, dirs):
    mdl = api.model or {}
    feats = mdl.get("features")
    if not feats:
        return None
    try:
        w = mdl["w"]
        mean = mdl["mean"]
        std = mdl["std"]
        elev = int(qp.get("elev", 0) or 0)
        tdfn = {0: 1.0, 1: 1.0, 2: 1.5, 3: 2.0}.get(elev, 1.0)
        x = {
            "log_ratio": math.log((ms + 1.0) / (es + 1.0)),
            "terrain_dfn": tdfn,
            "fort": float(qp.get("fort", 0) or 0),
            "city": 1.0 if qp.get("city") else 0.0,
            "bonus": max(u.get("bonus", 0) for u in lst) / 100.0,
            "att_rdy": avg_rdy / 100.0,
            "heavy_share": sum(1 for u in lst if u.get("type") in HEAVY) / float(len(lst)),
            "dirs": float(dirs),
        }
        z = mdl["b"]
        for i, f in enumerate(feats):
            z += w[i] * (x.get(f, 0.0) - mean[i]) / std[i]
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))
    except Exception:
        return None


def _attack(api, units, m):
    t = api.t
    prep = m.setdefault("prep", {})
    provs = api.provs
    enemy = api.enemy or {}
    byprov = {}
    for u in units:
        if u.get("type") == "rec":
            continue
        byprov.setdefault(_int(u.get("prov")), []).append(u)

    for p in list(prep.keys()):
        ent = prep[p]
        q = ent["q"]
        lst = [u for u in byprov.get(p, []) if u.get("plan", -1) == q]
        if not lst:
            del prep[p]
            continue
        ready = (t - ent["t"] >= 18) or any(u.get("bonus", 0) >= 30 for u in lst)
        if ready:
            e = _enemy_at(enemy, q)
            es = float(e.get("str", 0) or 0)
            ms = sum(u.get("str", 0) for u in lst)
            ids = ",".join(str(u["id"]) for u in lst)
            if es > 0 and ms < es * 3.0:
                api.cmd("hold %s" % ids)
            else:
                r = api.cmd("move %s P%d" % (ids, q))
                if str(r).startswith("ok"):
                    api.count("attack_launch")
            del prep[p]

    if len(prep) >= 2:
        return

    best = None
    for praw in list(api.border.keys()):
        p = _int(praw)
        if p is None or p in prep:
            continue
        pr = provs.get(p)
        if not pr:
            continue
        lst = [u for u in byprov.get(p, [])
               if u.get("str", 0) >= 70 and not u.get("path")
               and u.get("state") not in BUSY and not u.get("dry")
               and u.get("supplied", True)]
        if len(lst) < 6:
            continue
        avg_rdy = sum(u.get("rdy", 0) for u in lst) / float(len(lst))
        if avg_rdy < 80:
            continue
        ms = sum(u.get("str", 0) for u in lst)
        for qraw in pr.get("nbrs", []):
            q = _int(qraw)
            if q is None:
                continue
            e = _enemy_at(enemy, q)
            if not e:
                continue
            qp = provs.get(q) or {}
            if qp.get("owner") == "me":
                continue
            if int(qp.get("fort", 0) or 0) > 0:
                continue
            es = float(e.get("str", 0) or 0)
            elev = int(qp.get("elev", 0) or 0)
            need = 3.5 if elev >= 2 else 3.0
            if ms < es * need:
                continue
            dirs = 0
            for nraw in qp.get("nbrs", []):
                npv = provs.get(_int(nraw)) or {}
                if npv.get("owner") == "me":
                    dirs += 1
            pm = _pmodel(api, lst, qp, ms, es, avg_rdy, dirs)
            if pm is not None:
                if pm < 0.6:
                    continue
                score = pm * ms / max(es, 1.0)
            else:
                score = ms / max(es, 1.0)
            if best is None or score > best[0]:
                best = (score, p, q, lst)

    if best is not None:
        _, p, q, lst = best
        ids = ",".join(str(u["id"]) for u in lst)
        api.cmd("group a%d %s" % (p, ids))
        r = api.cmd("prepare %s P%d" % (ids, q))
        if str(r).startswith("ok"):
            prep[p] = {"q": q, "t": t}
            api.count("attack_prepare")


def _assign(api, units, m):
    budget = 80
    neutral = bool(api.neutral_border)
    buckets = {"expand": [], "front": [], "explore": []}
    for u in units:
        if budget <= 0:
            break
        if u.get("path") or u.get("fighting"):
            continue
        if u.get("state") not in ("ready", "refitting"):
            continue
        if u.get("front") or u.get("expand") or u.get("explore"):
            continue
        uid = u.get("id")
        typ = u.get("type")
        if typ == "rec":
            buckets["explore"].append(uid)
            continue
        if u.get("str", 0) < 50:
            continue
        if typ in HEAVY or not neutral or uid % 5 >= 4:
            buckets["front"].append(uid)
        else:
            buckets["expand"].append(uid)
    for verb in ("explore", "expand", "front"):
        ids = buckets[verb]
        for i in range(0, len(ids), 25):
            if budget <= 0:
                return
            chunk = ",".join(str(x) for x in ids[i:i + 25])
            api.cmd("%s %s" % (verb, chunk))
            budget -= 1


def tick(api):
    m = api.mem
    units = list(api.units or [])
    counts = {}
    for u in units:
        typ = u.get("type")
        counts[typ] = counts.get(typ, 0) + 1
    try:
        _diplomacy(api, m)
    except Exception:
        pass
    try:
        _depots(api, m)
    except Exception:
        pass
    try:
        _economy(api, m)
    except Exception:
        pass
    try:
        _recruit(api, counts, len(units))
    except Exception:
        pass
    try:
        _research(api)
    except Exception:
        pass
    try:
        _refit(api, units)
    except Exception:
        pass
    try:
        _attack(api, units, m)
    except Exception:
        pass
    try:
        _assign(api, units, m)
    except Exception:
        pass
    m["calls"] = m.get("calls", 0) + 1
