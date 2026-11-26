**Review:** Across three wars we placed 19 to 20 of 30 and held 65 to 78 provinces. Assaults succeeded 8 times in 200, mostly against fort 3 to 4 targets. About 44% of units were on outdated models at the end, and steel, oil and rare sat unused while res stayed near zero. Pacts were offered repeatedly but we never used them.

**Changes:**
- **Research:** Prioritise res-yield and res-cost lines (farming, industry, conscription, logistics), since res is the bottleneck. Drop the mining, drilling and refining lines, since special stock is already in surplus.
- **Refit:** Lower the res reserve so more veterans get re-equipped.
- **Assaults:** Require a higher win probability against forts of level 2 and above, and never attack pact partners.
- **Diplomacy:** Accept pacts, accept trades that do not lose value, and offer 240 h pacts to met factions every 96 h. Pacts free our fronts from low-odds fighting.

The rest of the structure (recruit mix, front and expand orders, prepared attacks) stays, since the main failure was attacking into forts and not the army mix.

```python
RESEARCH_ORDER = [
    "farming", "industry", "conscription", "logistics", "arm.protection",
    "inf.weapons", "art.weapons", "inf.protection", "arm.weapons",
    "medicine", "drill", "discipline", "fieldworks", "staffwork", "mobility",
]

MIX = [
    ("inf", 0.24), ("mtn", 0.04), ("art", 0.12), ("arm", 0.18),
    ("atg", 0.10), ("eng", 0.05), ("mot", 0.08), ("hvt", 0.08),
    ("mec", 0.04), ("rec", 0.01), ("cav", 0.06),
]

MIN_INCOME = 20
ASSAULT_P_START = 0.75
ASSAULT_P_LAUNCH = 0.65
FORT_P_MIN = 0.9
PREP_HOURS = 8
MAX_PREP = 4
REFIT_KEEP_RES = 80
REFIT_MAX_PER_TICK = 60
PACT_EVERY = 96
PACT_HOURS = 240


def _diplo(api, m):
    w = {"res": 1.0, "mp": 1.0, "steel": 0.5, "oil": 1.0, "rare": 1.5}
    for o in list(api.offers_in):
        try:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o["id"])
            elif o.get("kind") == "trade":
                give = sum(w.get(k, 1.0) * v for k, v in (o.get("you_give") or {}).items())
                get = sum(w.get(k, 1.0) * v for k, v in (o.get("they_give") or {}).items())
                if get >= give:
                    api.cmd("accept %s" % o["id"])
                else:
                    api.cmd("reject %s" % o["id"])
        except Exception:
            pass


def _pact_offers(api, m):
    if api.t - m.get("last_pact", -10000) < PACT_EVERY:
        return
    m["last_pact"] = api.t
    for f in api.met:
        if f in api.pacts:
            continue
        api.cmd("offer %s pact %d" % (f, PACT_HOURS))


def _research(api, m):
    active = [r[0] for r in api.research]
    st = api.stock
    for line in RESEARCH_ORDER:
        if len(active) >= 2:
            return
        info = api.tech.get(line)
        if not info or info.get("status") != "open" or line in active:
            continue
        cost = info.get("cost") or {}
        if all(st.get(k, 0) >= v + 40 for k, v in cost.items()):
            if api.cmd("research " + line).startswith("ok"):
                active.append(line)


def _refit(api, m):
    if api.res < REFIT_KEEP_RES + 20 or api.old_units <= 0:
        return
    cands = [u for u in api.units
             if u.get("old") and not u["fighting"] and not u["path"]
             and u["state"] == "ready" and u.get("supplied")]
    if not cands:
        return
    budget = api.res - REFIT_KEEP_RES
    stock = dict(api.stock)
    chosen = []
    for u in cands:
        rc = api.refit_cost.get(u["type"], {})
        if rc.get("res", 0) > budget:
            continue
        if any(rc.get(k, 0) > stock.get(k, 0) for k in ("steel", "oil", "rare")):
            continue
        budget -= rc.get("res", 0)
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - rc.get(k, 0)
        chosen.append(u["id"])
        if len(chosen) >= REFIT_MAX_PER_TICK:
            break
    if chosen:
        api.cmd("refit " + ",".join(str(i) for i in chosen))


def _recruit(api, m):
    if api.income < MIN_INCOME or api.res < 80:
        return
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total_now = len(api.units)
    res = api.res
    mp = api.mp
    stock = dict(api.stock)
    for _ in range(4):
        total = total_now + 1
        best = None
        bd = -1e9
        for typ, share in MIX:
            if typ not in api.costs:
                continue
            rc, mc = api.costs[typ]
            if rc > res - 40 or mc > mp:
                continue
            uc = api.unit_costs.get(typ, {})
            if any(uc.get(k, 0) > stock.get(k, 0) for k in ("steel", "oil", "rare")):
                continue
            d = share * total - counts.get(typ, 0)
            if d > bd:
                bd = d
                best = typ
        if best is None:
            return
        r = api.cmd("recruit %s 1 P%d" % (best, api.capital))
        if not r.startswith("ok"):
            return
        rc, mc = api.costs[best]
        res -= rc
        mp -= mc
        uc = api.unit_costs.get(best, {})
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - uc.get(k, 0)
        counts[best] = counts.get(best, 0) + 1
        total_now += 1


def _ids(us):
    return ",".join(str(u["id"]) for u in us)


def _assign(api, m):
    idle = [
        u for u in api.units
        if not u["path"] and not u["front"] and not u["expand"]
        and not u["explore"] and not u["fighting"] and u["state"] == "ready"
    ]
    if not idle:
        return
    scouts = [u for u in idle if u["type"] == "rec"]
    rest = [u for u in idle if u["type"] != "rec"]
    if scouts:
        api.cmd("explore " + _ids(scouts))
    if not rest:
        return
    if api.neutral_border:
        half = rest[: max(1, len(rest) // 2)]
        api.cmd("expand " + _ids(half))
        rest = rest[len(half):]
    if rest:
        ids = _ids(rest)
        api.cmd("front " + ids)
        if m.get("line_init"):
            api.cmd("group line + " + ids)
        elif api.cmd("group line " + ids).startswith("ok"):
            m["line_init"] = True


def _terr(pr):
    t = str(pr.get("terrain", "")).lower()
    if t.startswith("mountain") or t.startswith("mtn"):
        return 2.0
    if t.startswith("hill"):
        return 1.5
    if t.startswith("forest") or t.startswith("for"):
        return 1.25
    return 1.0


def _pwin(api, att_units, tgt, dirs):
    e = api.enemy.get(tgt)
    if not e or not att_units:
        return 0.0
    att = sum(u["str"] for u in att_units)
    if att <= 0:
        return 0.0
    mdl = api.model or {}
    if not mdl.get("w"):
        return 1.0 if att > 3.0 * e["str"] else 0.0
    pr = api.provs.get(tgt, {})
    n = len(att_units)
    feats = {
        "log_ratio": math.log((att + 1) / (e["str"] + 1)),
        "terrain_dfn": _terr(pr),
        "fort": float(pr.get("fort", 0) or 0),
        "city": 1.0 if pr.get("city") else 0.0,
        "bonus": max(u.get("bonus", 0) for u in att_units) / 100.0,
        "att_rdy": sum(u["rdy"] for u in att_units) / n / 100.0,
        "heavy_share": sum(1 for u in att_units
                           if u["type"] in ("art", "eng", "arm", "hvt")) / n,
        "dirs": float(dirs),
    }
    z = mdl["b"]
    for f, w, mu, sd in zip(mdl["features"], mdl["w"], mdl["mean"], mdl["std"]):
        z += w * (feats.get(f, 0.0) - mu) / sd
    return 1.0 / (1.0 + math.exp(-z))


def _attack(api, m):
    prep = m.setdefault("prep", {})
    t = api.t
    by_prov = {}
    for u in api.units:
        if u["path"] or u["type"] == "rec":
            continue
        by_prov.setdefault(u["prov"], []).append(u)

    for pid, (tgt, t0) in list(prep.items()):
        if pid not in by_prov or api.provs.get(tgt, {}).get("owner") == "me":
            del prep[pid]
            continue
        if t - t0 >= PREP_HOURS:
            us = [u for u in by_prov[pid] if u["rdy"] >= 60]
            p = _pwin(api, us, tgt, 1)
            if p >= ASSAULT_P_LAUNCH:
                api.cmd("move @P%d P%d" % (pid, tgt))
            else:
                api.cmd("hold @P%d" % pid)
            del prep[pid]

    if len(prep) >= MAX_PREP:
        return
    busy = set(prep.keys()) | set(v[0] for v in prep.values())
    cands = []
    for pid, us in by_prov.items():
        if pid in prep:
            continue
        pr = api.provs.get(pid)
        if not pr:
            continue
        ready = [u for u in us if u["rdy"] >= 70 and u["str"] >= 40
                 and u["state"] == "ready" and not u["fighting"]]
        if sum(u["str"] for u in ready) < 150:
            continue
        for nb in pr.get("nbrs", []):
            if nb not in api.enemy or nb in busy:
                continue
            if api.owner_name.get(nb) in api.pacts:
                continue
            pn = api.provs.get(nb, {})
            if pn.get("owner") == "me":
                continue
            need = ASSAULT_P_START if (pn.get("fort", 0) or 0) <= 1 else FORT_P_MIN
            p = _pwin(api, ready, nb, 1)
            if p >= need:
                cands.append((p, pid, nb))
    used = set()
    for p, pid, nb in sorted(cands, key=lambda c: c[0], reverse=True):
        if len(prep) >= MAX_PREP:
            break
        if pid in used or nb in used:
            continue
        if api.cmd("prepare @P%d P%d" % (pid, nb)).startswith("ok"):
            prep[pid] = (nb, t)
            used.add(pid)
            used.add(nb)


def tick(api):
    m = api.mem
    for f in (_diplo, _pact_offers, _research, _refit, _recruit, _attack, _assign):
        try:
            f(api, m)
        except Exception:
            pass
```

```letters
to germania: Sarmatia accepts your lasting peace. Keep your borders and we will keep ours.
to siberia: Sarmatia accepts your non-aggression pact. We will honour any pact we sign.
```