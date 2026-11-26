Arabia's edge is speed and cheaper units, so the policy leans on mobile infantry and motorised units, spreads blind upgrade picks across lines, and expands onto neutral land before attacking. Attacks happen only from my own border provinces, against visible enemy provinces, and only when my force is clearly stronger: at least 1.8x the visible enemy strength plus a margin for fort level. Each attack is prepared for 12 hours, then moved in as a named group to build formation experience. Battered units retreat to the capital to refit, and engineers fortify border provinces. Each section is wrapped in its own try/except, so one failure does not lose the whole tick.

```python
PREF = {"inf": 5.0, "mot": 2.0, "arm": 2.0, "art": 1.0, "eng": 1.0, "atg": 1.0, "grn": 1.0, "mtn": 1.0}
BACK = ("art", "atg", "eng", "hvt", "rkt")
LINES = ["farming", "inf.weapons", "inf.protection", "mot.mobility", "arm.weapons",
         "logistics", "medicine", "drill", "mot.weapons", "arm.protection",
         "conscription", "discipline", "staffwork", "fieldworks", "industry",
         "mining", "drilling", "refining", "mtn.weapons", "inf.mobility"]
NEED = {"mining": "steel", "drilling": "oil", "refining": "rare"}


def _sel(ids):
    return ",".join(str(i) for i in ids)


def _border_keys(api):
    b = api.border
    try:
        return list(b.keys())
    except Exception:
        return list(b)


def _alarm(api, ctx):
    cap = api.capital
    near = [cap] + list(api.provs.get(cap, {}).get("nbrs", []))
    if any(p in api.enemy for p in near if isinstance(p, int)):
        api.mem["alarm"] = api.t


def _recruit(api, ctx):
    m = api.mem
    if api.income_by.get("res", 0) < -2:
        return
    counts = {}
    for u in ctx["units"]:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    res = api.res
    mp = api.mp
    stock = api.stock
    reserve = 25
    cap = api.capital
    if counts.get("rec", 0) < 2:
        c = api.costs.get("rec")
        if c and res - reserve >= c[0] and mp >= c[1]:
            if api.cmd("recruit rec P%d" % cap).startswith("ok"):
                res -= c[0]
                mp -= c[1]
                counts["rec"] = counts.get("rec", 0) + 1
    pref = dict(PREF)
    if api.t - m.get("alarm", -999) <= 12:
        pref["inf"] = 9.0
    n = 0
    while n < 6:
        fight = sum(counts.get(k, 0) for k in pref)
        tw = sum(pref.values())
        ranked = sorted(((w / tw * (fight + 4) - counts.get(k, 0), k) for k, w in pref.items()),
                        reverse=True)
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
            break
        c = api.costs[pick]
        res -= c[0]
        mp -= c[1]
        counts[pick] = counts.get(pick, 0) + 1
        n += 1


def _research(api, ctx):
    t = api.t
    maxp = 1 if t < 96 else 2
    running = [r[0] for r in api.research]
    slots = maxp - len(running)
    if slots <= 0:
        return
    avail = dict(api.stock)
    resv = 60 if len(ctx["units"]) < 8 else 25
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


def _assign(api, ctx):
    nb = api.neutral_border or []
    front, expand = [], []
    for u in ctx["units"]:
        if u["type"] == "rec" or u.get("path"):
            continue
        if u.get("expand") or u.get("front") or u.get("explore") or u.get("fighting"):
            continue
        if u.get("state") != "ready" or u.get("plan", -1) != -1:
            continue
        if u.get("str", 0) < 60:
            continue
        if len(front) + len(expand) >= 60:
            break
        if u["type"] in BACK or not nb or u["id"] % 3 == 0:
            front.append(u["id"])
        else:
            expand.append(u["id"])
    if front:
        api.cmd("front %s" % _sel(front))
    if expand:
        api.cmd("expand %s" % _sel(expand))


def _retreat(api, ctx):
    m = api.mem
    t = api.t
    cap = api.capital
    if cap is None:
        return
    ids = []
    for u in ctx["units"]:
        if u["type"] == "rec" or u.get("path") or u.get("front"):
            continue
        if u.get("str", 100) >= 30 or u["prov"] == cap:
            continue
        key = str(u["id"])
        if t - m["retreat"].get(key, -99) < 12:
            continue
        m["retreat"][key] = t
        ids.append(u["id"])
    if ids:
        api.cmd("move %s P%d" % (_sel(ids), cap))


def _attacks(api, ctx):
    m = api.mem
    t = api.t
    plans = m["plan"]
    # launch or drop existing plans
    for key in list(plans.keys()):
        p, t0, ids = plans[key]
        q = int(key)
        alive = [u["id"] for u in ctx["units"]
                 if u["id"] in ids and u["prov"] == p and not u.get("path")]
        if not alive or t - t0 > 36:
            del plans[key]
            continue
        if t - t0 >= 12:
            g = "g%d_%d" % (q, t)
            api.cmd("group %s %s" % (g, _sel(alive)))
            api.cmd("move %s P%d" % (g, q))
            del plans[key]
    if len(plans) >= 2:
        return
    busy = set(int(k) for k in plans)
    for p in ctx["border"]:
        pr = api.provs.get(p)
        if not pr or pr.get("owner") != "me":
            continue
        force = [u for u in ctx["byprov"].get(p, [])
                 if u["type"] != "rec" and u.get("state") == "ready"
                 and u.get("plan", -1) == -1 and not u.get("path") and u.get("str", 0) >= 50]
        if len(force) < 2:
            continue
        force.sort(key=lambda u: -u.get("str", 0))
        force = force[:6]
        mine = sum(u.get("str", 0) for u in force)
        for q in pr.get("nbrs", []):
            if not isinstance(q, int) or q in busy:
                continue
            qp = api.provs.get(q)
            if not qp or qp.get("owner") != "enemy" or qp.get("harsh"):
                continue
            e = api.enemy.get(q)
            es = e.get("str", 0) if e else 0
            fort = qp.get("fort", 0) or 0
            if mine < 1.8 * es + 60 + 80 * fort:
                continue
            ids = [u["id"] for u in force]
            api.cmd("prepare %s P%d" % (_sel(ids), q))
            plans[str(q)] = [p, t, ids]
            busy.add(q)
            break
        if len(plans) >= 2:
            return


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
    m.setdefault("err", 0)
    units = list(api.units)
    byprov = {}
    for u in units:
        byprov.setdefault(u["prov"], []).append(u)
    ctx = {"units": units, "byprov": byprov, "border": _border_keys(api)}
    for fn in (_alarm, _recruit, _research, _scouts, _assign, _retreat, _attacks, _fort):
        try:
            fn(api, ctx)
        except Exception:
            m["err"] = m.get("err", 0) + 1
```