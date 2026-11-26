The last war stalled: assaults took 1 of 200, 752 of 1640 units were still on outdated models, and the stockpile sat unspent (38k res, 5.6k steel, 1.7k rare). The rewrite targets those three gaps:

- **Refit** out-of-contact units that are on outdated models, so research breakthroughs reach the field.
- **Spend the bank**: raise the recruit cap with surplus res, and add rocket artillery, which uses the idle rare stock and ignores 30% of forts.
- **Gate assaults** with the fitted battle model when it is available, requiring about a 45% estimated success and at least 1.5x strength, instead of a fixed ratio.
- **Research** a wider set of lines, keeping two projects running.

I have not been able to test this against the engine, so the model-gate and refit thresholds are first guesses.

```python
RESEARCH = ["inf.weapons", "art.weapons", "arm.weapons", "atg.weapons",
            "industry", "inf.protection", "mot.mobility", "logistics",
            "farming", "mining", "drilling", "drill", "conscription",
            "medicine", "discipline", "fieldworks", "staffwork",
            "mtn.weapons", "grn.weapons", "rkt.weapons", "hvt.weapons",
            "arm.protection", "mot.weapons", "refining", "mec.weapons"]

MIX = [("inf", 0.28), ("mil", 0.04), ("mtn", 0.09), ("grn", 0.07),
       ("art", 0.12), ("atg", 0.06), ("arm", 0.08), ("mot", 0.06),
       ("rkt", 0.06), ("eng", 0.05), ("cav", 0.03), ("rec", 0.03),
       ("hvt", 0.03)]

HEAVY = ("arm", "hvt", "art", "atg", "rkt", "eng")
BUSY = ("moving", "routing", "shaken", "pinned", "preparing", "assault")
RESERVE = 300


def _int(x):
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
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


def _recruit(api, counts, total):
    t = api.t
    st = api.stock or {}
    inc = api.income_by or {}
    res = _f(st, "res")
    mp = float(api.mp or 0)
    steel = _f(st, "steel")
    oil = _f(st, "oil")
    rare = _f(st, "rare")
    cap = 160 + 25 * (t // 24) + int(max(0.0, res - 8000.0) // 400)
    cap = min(cap, 900)
    if total >= cap:
        return 0
    if _f(inc, "res") < 0 and res < 1500:
        return 0
    done = 0
    for _ in range(12):
        best = None
        bestdef = -1e9
        for typ, frac in MIX:
            c = api.unit_costs.get(typ)
            if not c:
                continue
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
        if u.get("rdy", 0) < 60 or u.get("str", 0) < 50:
            continue
        c = rc.get(u.get("type"))
        if not c:
            continue
        if (res - _f(c, "res") < 500 or steel < _f(c, "steel")
                or oil < _f(c, "oil") or rare < _f(c, "rare")):
            continue
        res -= _f(c, "res")
        steel -= _f(c, "steel")
        oil -= _f(c, "oil")
        rare -= _f(c, "rare")
        ids.append(u["id"])
        if len(ids) >= 60:
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

    # launch prepared attacks
    for p in list(prep.keys()):
        ent = prep[p]
        q = ent["q"]
        lst = [u for u in byprov.get(p, []) if u.get("plan", -1) == q]
        if not lst:
            del prep[p]
            continue
        ready = (t - ent["t"] >= 12) or any(u.get("bonus", 0) >= 25 for u in lst)
        if ready:
            e = enemy.get(q) or enemy.get("P%d" % q) or {}
            es = float(e.get("str", 0) or 0)
            ms = sum(u.get("str", 0) for u in lst)
            if es > 0 and ms < es * 1.8:
                api.cmd("hold %s" % ",".join(str(u["id"]) for u in lst))
            else:
                api.cmd("move %s P%d" % (",".join(str(u["id"]) for u in lst), q))
            del prep[p]

    if len(prep) >= 4:
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
               if u.get("str", 0) >= 60 and not u.get("path")
               and u.get("state") not in BUSY]
        if len(lst) < 3:
            continue
        avg_rdy = sum(u.get("rdy", 0) for u in lst) / float(len(lst))
        if avg_rdy < 65:
            continue
        ms = sum(u.get("str", 0) for u in lst)
        for qraw in pr.get("nbrs", []):
            q = _int(qraw)
            if q is None:
                continue
            e = enemy.get(q)
            if e is None:
                e = enemy.get("P%d" % q)
            if not e:
                continue
            qp = provs.get(q) or {}
            if qp.get("owner") == "me":
                continue
            if int(qp.get("fort", 0) or 0) > 1:
                continue
            es = float(e.get("str", 0) or 0)
            dirs = 0
            for nraw in qp.get("nbrs", []):
                npv = provs.get(_int(nraw)) or {}
                if npv.get("owner") == "me":
                    dirs += 1
            pm = _pmodel(api, lst, qp, ms, es, avg_rdy, dirs)
            if pm is not None:
                if pm < 0.45 or ms < es * 1.5:
                    continue
                score = pm * ms / max(es, 1.0)
            else:
                need = 2.0 if e.get("exact") else 2.8
                if ms < es * need:
                    continue
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
        if typ in HEAVY or not neutral or uid % 5 >= 3:
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
```

```letters
to cascadia: Laurentia proposes we leave each other's provinces alone; if you agree, send us a pact offer and we will accept it.
to anahuac: Laurentia is open to a non-aggression pact. Offer one and we will accept, so both of us can turn against weaker neighbours.
to albion: Laurentia would rather not spend units on your coast. Offer a pact if you feel the same and we will accept.
```