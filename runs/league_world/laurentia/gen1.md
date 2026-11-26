**Review of war 1 (5th of 30, 225 provinces):**

- **Unspent resources.** We ended with 64,657 res, 5,994 steel, 2,740 oil and 28,525 manpower in the bank. The self-imposed unit cap (`70 + 5*days`) and the 120-res reserve starved production while the economy piled up. Raise the cap and spend.
- **Assaults almost never worked.** We took 3 of 163. Success was 1/72 at strength ratio 0-1, and 0/115 against fort level 3-4. The trigger ignored fort level and used weak ratio thresholds. Require fort ≤1 and a larger strength margin.
- **Defence held better than offence.** Enemies succeeded on only 16 of 146 assaults against us, so the front order works. Keep it, and expand into neutral land, which is where our gains came from.
- **Research.** Weapons lines (inf, art, arm, atg), logistics, medicine and drill paid off. Farming, conscription and industry hit dead ends late. Prioritise the paying lines and skip closed ones via the status check.
- **Mix.** Keep infantry as the backbone, add militia for cheap bulk, and cut heavy armour, which is costly.

```python
RESEARCH = ["inf.weapons", "art.weapons", "arm.weapons", "atg.weapons",
            "logistics", "medicine", "drill", "farming", "conscription",
            "inf.protection", "mining", "drilling", "discipline",
            "fieldworks", "staffwork", "mtn.weapons", "grn.weapons",
            "mot.mobility", "arm.protection", "mot.weapons", "industry"]

MIX = [("inf", 0.34), ("mil", 0.05), ("mtn", 0.10), ("grn", 0.08),
       ("art", 0.10), ("atg", 0.07), ("arm", 0.08), ("mot", 0.07),
       ("eng", 0.04), ("cav", 0.04), ("rec", 0.03)]

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
    cap = 150 + 15 * (t // 24)
    if total >= cap:
        return 0
    if _f(inc, "res") < 0 and res < 1500:
        return 0
    done = 0
    for _ in range(6):
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
        _attack(api, units, m)
    except Exception:
        pass
    try:
        _assign(api, units, m)
    except Exception:
        pass
    m["calls"] = m.get("calls", 0) + 1
```