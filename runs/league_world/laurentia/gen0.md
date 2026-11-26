**Reasoning**

Laurentia's doctrine is neutral. New units start at +15 experience but cost 10% more, so I'll rely on a steady army and avoid large early costs.

- **Economy:** Recruit when affordable and income is positive, with a reserve kept back. The unit mix targets infantry as the core, with artillery, anti-tank, armour, and engineers. Cap the army size as days pass to protect upkeep.
- **Research:** Start one line at a time from a fixed priority list, skipping any line that is dead-ended or already in progress. Keep a bank reserve.
- **Land:** Idle units with healthy strength take free land through `expand`, while heavy units and some others hold the `front`. Scouts `explore`.
- **Attacks:** Attack only with a clear strength advantage (about 2x against unknown enemies, 1.6x against exact counts). Prepare, group, and launch once the bonus builds or after about 12 hours.

Every section is wrapped in a try/except so one failure cannot stop the others. I cap commands per tick to stay within the time budget.

```python
RESEARCH = ["farming", "inf.weapons", "inf.protection", "conscription",
            "art.weapons", "arm.weapons", "atg.weapons", "industry",
            "drill", "medicine", "logistics", "mining", "drilling",
            "arm.protection", "mtn.weapons", "grn.weapons", "discipline",
            "arm.mobility", "mot.mobility", "staffwork", "fieldworks"]

MIX = [("inf", 0.30), ("mtn", 0.08), ("grn", 0.07), ("art", 0.09),
       ("atg", 0.07), ("arm", 0.10), ("mot", 0.08), ("eng", 0.04),
       ("cav", 0.03), ("rec", 0.03)]

HEAVY = ("arm", "hvt", "art", "atg", "rkt", "eng")
BUSY = ("moving", "routing", "shaken", "pinned", "preparing", "assault")


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
    res = _f(st, "res")
    mp = float(api.mp or 0)
    steel = _f(st, "steel")
    oil = _f(st, "oil")
    rare = _f(st, "rare")
    inc = api.income_by or {}
    if total >= 70 + 5 * (t // 24):
        return 0
    if _f(inc, "res") < 0 and res < 800:
        return 0
    done = 0
    for _ in range(3):
        best = None
        bestdef = -1e9
        for typ, frac in MIX:
            c = api.unit_costs.get(typ)
            if not c:
                continue
            if (res < _f(c, "res") + 120 or mp < _f(c, "mp")
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
    return done


def _research(api):
    if len(api.research or []) >= 2:
        return
    st = api.stock or {}
    if _f(st, "res") < 250:
        return
    for line in RESEARCH:
        info = api.tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost") or {}
        if any(_f(st, k) < _f(cost, k) for k in ("res", "steel", "oil", "rare")):
            continue
        if _f(st, "res") - _f(cost, "res") < 150:
            continue
        r = api.cmd("research %s" % line)
        if str(r).startswith("ok"):
            return


def _attack(api, units, m):
    t = api.t
    prep = m.setdefault("prep", {})
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
            ids = ",".join(str(u["id"]) for u in lst)
            api.cmd("move %s P%d" % (ids, q))
            del prep[p]

    if len(prep) >= 6:
        return
    provs = api.provs
    enemy = api.enemy or {}
    for praw in list(api.border.keys()):
        p = _int(praw)
        if p is None or p in prep:
            continue
        pr = provs.get(p)
        if not pr:
            continue
        lst = [u for u in byprov.get(p, [])
               if u.get("str", 0) >= 50 and not u.get("path")
               and u.get("state") not in BUSY]
        if len(lst) < 2:
            continue
        avg_rdy = sum(u.get("rdy", 0) for u in lst) / float(len(lst))
        if avg_rdy < 55:
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
            if (provs.get(q) or {}).get("owner") == "me":
                continue
            es = float(e.get("str", 0) or 0)
            need = 1.6 if e.get("exact") else 2.2
            if ms < es * need:
                continue
            ids = ",".join(str(u["id"]) for u in lst)
            api.cmd("group a%d %s" % (p, ids))
            r = api.cmd("prepare %s P%d" % (ids, q))
            if str(r).startswith("ok"):
                prep[p] = {"q": q, "t": t}
            return  # one new preparation per tick


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
        _attack(api, units, m)
    except Exception:
        pass
    try:
        _assign(api, units, m)
    except Exception:
        pass
    m["calls"] = m.get("calls", 0) + 1
```