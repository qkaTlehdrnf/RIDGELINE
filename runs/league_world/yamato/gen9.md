The last war went badly: income turned negative by day 5 because the starting army's upkeep outran the economy, expansion stalled at about 10 provinces while 1,800 neutral provinces were still free, and no research was done. Pacts with everyone froze the map.

The rewrite does four things. It caps recruiting by income and province count, so no unit is added while the net income is thin. It runs a discovery priority list (roads and crop rotation first, then the medieval and gunpowder models) and falls back to cheap upgrade lines. It develops and builds infrastructure from the income. It accepts incoming pacts, but offers peace only to larger neighbours, so the weaker ones stay open to attack. Attacks go ahead at a 2.2:1 strength ratio. The unit mix switches by era, based on what can be raised.

The policy relies on field names from the briefing. I have not run it, so the thresholds are estimates.

```python
UPKEEP = {"inf": 0.09, "mil": 0.03, "mtn": 0.105, "mot": 0.135, "arm": 0.18,
          "art": 0.135, "eng": 0.09, "rec": 0.045, "cav": 0.084, "grn": 0.114,
          "atg": 0.075, "mec": 0.15, "hvt": 0.27, "rkt": 0.165}

LAND_TYPES = ("inf", "mil", "mtn", "mot", "arm", "art", "eng", "cav", "grn",
              "atg", "mec", "hvt", "rkt")
EXPAND_TYPES = ("mil", "inf", "cav", "mot", "eng", "mtn", "mec")

# unit mixes by era (filtered to what we can raise now)
MIX_EARLY = {"inf": 0.40, "mil": 0.30, "cav": 0.10, "art": 0.08, "eng": 0.07, "atg": 0.05}
MIX_MID = {"inf": 0.30, "mil": 0.10, "grn": 0.12, "art": 0.15, "cav": 0.05,
           "mtn": 0.08, "mot": 0.12, "eng": 0.05, "atg": 0.03}
MIX_LATE = {"inf": 0.15, "mec": 0.15, "arm": 0.15, "hvt": 0.07, "art": 0.12,
            "mot": 0.05, "atg": 0.08, "grn": 0.07, "mtn": 0.05, "rkt": 0.04, "eng": 0.02}

# discovery order: economy and cheap models first, then the military ladder
TREE = ["roads", "iron_working", "horse_riding", "masonry", "crop_rotation",
        "siege_engines", "pikes_crossbows", "stirrup", "galleys", "castles",
        "trebuchet", "hillmen", "sailing", "gunpowder", "banking", "matchlock",
        "steam_power", "rifling", "grenadiers", "railways", "steel_guns",
        "field_engineering", "combustion", "machine_guns", "tanks", "flight",
        "heavy_artillery", "anti_tank_guns", "navigation", "ships_of_the_line",
        "ironclads", "dragoons", "submarines", "bombers", "dreadnoughts",
        "mechanisation", "heavy_armour", "assault_rifles", "rocket_artillery",
        "carriers", "jet_engines", "rocketry", "satellites", "ballistic_missiles",
        "guided_weapons", "composite_armour"]

# upgrade lines, economy first
UPG = ["farming", "conscription", "mining", "drilling", "logistics", "medicine",
       "drill", "discipline", "fieldworks", "inf.protection", "inf.weapons",
       "industry", "art.weapons", "atg.weapons", "mot.mobility", "arm.protection",
       "arm.weapons"]

RES_FLOOR = 120        # res kept back when recruiting or researching
PER_PROV = 30          # soft cap of units per border province


def _terr_dfn(t):
    t = str(t)
    if "mount" in t:
        return 2.0
    if "hill" in t:
        return 1.5
    if "forest" in t:
        return 1.25
    return 1.0


def _planned(u):
    p = u.get("plan", -1)
    return p is not None and p >= 0


def _ids(lst):
    return ",".join(str(i) for i in lst)


def _chunks(lst, n=50):
    out = []
    for i in range(0, len(lst), n):
        out.append(_ids(lst[i:i + n]))
    return out


def _stock(api, q):
    return (api.provs.get(q) or {}).get("stock", 0)


def _owned_ids(api):
    return [p for p, pr in api.provs.items() if pr.get("owner") == "me"]


def _owned(api):
    return len(_owned_ids(api))


def _contact(api, pid):
    pr = api.provs.get(pid)
    if not pr:
        return False
    for nb in pr.get("nbrs", []):
        q = api.provs.get(nb)
        if q and q.get("owner") == "enemy":
            return True
        if nb in api.enemy:
            return True
    return False


def _border(api):
    return set(p for p in _owned_ids(api) if _contact(api, p))


def _take_prob(api, S, E, nb, us):
    m = api.model
    if not m or "w" not in m:
        return None
    n = float(len(us) or 1)
    heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / n
    rdy = sum(u.get("rdy", 50) for u in us) / n / 100.0
    bonus = max([u.get("bonus", 0) for u in us] + [0])
    if bonus > 1:
        bonus /= 100.0
    nbp = api.provs.get(nb, {})
    feats = [
        math.log((S + 1.0) / (E + 1.0)),
        _terr_dfn(nbp.get("terrain", "")),
        float(nbp.get("fort", 0) or 0),
        1.0 if nbp.get("city") else 0.0,
        bonus,
        rdy,
        heavy,
        1.0,
    ]
    z = m["b"]
    for i, x in enumerate(feats):
        z += m["w"][i] * (x - m["mean"][i]) / m["std"][i]
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _diplomacy(api, B):
    # accept peace and fair trades; offer peace only to larger neighbours
    for o in list(api.offers_in or []):
        try:
            k = o.get("kind")
            if k in ("pact", "alliance"):
                api.cmd("accept %s" % o["id"])
            elif k == "trade":
                give = sum((o.get("you_give") or {}).values())
                get = sum((o.get("they_give") or {}).values())
                api.cmd(("accept %s" if give <= get else "reject %s") % o["id"])
            elif k == "supply":
                gv = o.get("they_give") or {}
                pay = o.get("you_give") or {}
                strat = sum(v for kk, v in gv.items() if kk != "res")
                res_out = pay.get("res", 0)
                only_res = sum(pay.values()) == res_out
                ok = strat > 0 and only_res and res_out <= 3 * strat
                api.cmd(("accept %s" if ok else "reject %s") % o["id"])
        except Exception:
            pass
    pacts = api.pacts or {}
    last = api.mem.setdefault("pact_offer", {})
    nb_owner = set()
    owners = api.owner_name or {}
    for pid in _owned_ids(api):
        for nb in api.provs[pid].get("nbrs", []):
            f = owners.get(nb)
            if f:
                nb_owner.add(f)
    for f in (api.met or []):
        if f in pacts or f not in nb_owner:
            continue
        if api.t - last.get(f, -999) < 240:
            continue
        land = (api.powers or {}).get(f, {}).get("land", 0) or 0
        if land <= _owned(api):
            continue
        last[f] = api.t
        api.cmd("offer %s pact 240" % f)
    if api.stock.get("steel", 0) > 200 and api.stock.get("res", 0) < 150 and api.met:
        if api.t - api.mem.get("trade_t", -999) >= 192:
            cands = [f for f in api.met if f in pacts] or list(api.met)
            api.cmd("offer %s trade 100 steel for 100 res" % cands[0])
            api.mem["trade_t"] = api.t


def _research(api, B):
    running = [r[0] for r in (api.research or [])]
    if len(running) >= 2:
        return
    tree = api.tree or {}
    for d in TREE:
        if len(running) >= 2:
            break
        t = tree.get(d)
        if not t or t.get("status") != "open":
            continue
        need = t.get("res_now")
        if need is None:
            need = (t.get("cost") or {}).get("res", 0)
        if api.stock.get("res", 0) < need + RES_FLOOR:
            break                      # save up for the next one in order
        if api.cmd("research " + d).startswith("ok"):
            running.append(d)
    if len(running) >= 2 or api.income < 6:
        return
    tech = api.tech or {}
    for line in UPG:
        if len(running) >= 2:
            break
        if line in running:
            continue
        t = tech.get(line)
        if not t or t.get("status") != "open":
            continue
        c = t.get("cost")
        if not c:
            continue
        if api.stock.get("res", 0) - c.get("res", 0) < 300:
            continue
        if not all(api.stock.get(k, 0) >= v for k, v in c.items() if k != "res"):
            continue
        if api.cmd("research " + line).startswith("ok"):
            running.append(line)


def _mix(api):
    can = set(api.can_raise or [])
    if "mec" in can or "arm" in can or "hvt" in can:
        base = MIX_LATE
    elif "grn" in can or "mot" in can or "mtn" in can:
        base = MIX_MID
    else:
        base = MIX_EARLY
    return dict((t, w) for t, w in base.items() if t in can)


def _recruit(api, B):
    costs = api.unit_costs or {}
    if not costs or api.income < 4:
        return
    if len(api.units) >= min(400, 60 + 12 * _owned(api)):
        return                         # do not add upkeep beyond what the land carries
    if B:
        ks = [api.provs[p].get("stock", 0) for p in B if p in api.provs]
        if ks and sum(ks) / float(len(ks)) < 60:
            return
    mix = _mix(api)
    if not mix:
        return
    count = {}
    for u in api.units:
        count[u["type"]] = count.get(u["type"], 0) + 1
    total = len(api.units) + 1
    res = api.stock.get("res", 0)
    steel = api.stock.get("steel", 0)
    oil = api.stock.get("oil", 0)
    rare = api.stock.get("rare", 0)
    mp = api.mp
    inc = api.income
    made = 0
    while made < 2:
        best = None
        for t, share in mix.items():
            c = costs.get(t)
            if not c:
                continue
            if res - c.get("res", 0) < RES_FLOOR or mp < c.get("mp", 0):
                continue
            if steel < c.get("steel", 0) or oil < c.get("oil", 0) or rare < c.get("rare", 0):
                continue
            if inc - UPKEEP.get(t, 0.1) < 4:
                continue
            deficit = share * total - count.get(t, 0)
            if best is None or deficit > best[0]:
                best = (deficit, t, c)
        if best is None or best[0] <= 0:
            break
        _, t, c = best
        if not api.cmd("recruit %s P%d" % (t, api.capital)).startswith("ok"):
            break
        res -= c.get("res", 0)
        mp -= c.get("mp", 0)
        steel -= c.get("steel", 0)
        oil -= c.get("oil", 0)
        rare -= c.get("rare", 0)
        inc -= UPKEEP.get(t, 0.1)
        count[t] = count.get(t, 0) + 1
        total += 1
        made += 1
    if made:
        api.count("recruited", made)


def _economy(api, B):
    if api.t < 24 or api.income < 6:
        return
    econ = api.economy or {}
    works = econ.get("works") or []
    if len(works) >= 2:
        return
    res = api.stock.get("res", 0)
    cand = []
    for pr in econ.get("provs") or []:
        pid = pr.get("prov")
        if pid is None or api.provs.get(pid, {}).get("owner") != "me":
            continue
        dev = pr.get("dev", 0) or 0
        if pr.get("can_dev") and dev + 1 <= (pr.get("room", 0) or 0) and dev < 5:
            c = (pr.get("dev_cost") or {}).get("res", 999)
            if res - c >= 200:
                cand.append(((pr.get("yield_now", 0) or 0), "develop", pid))
        if pr.get("can_infra") and pid in B and (pr.get("infra", 0) or 0) < 2:
            c = (pr.get("infra_cost") or {}).get("res", 999)
            if res - c >= 300:
                cand.append((0.5 * (pr.get("yield_now", 0) or 0), "build", pid))
    if not cand:
        return
    cand.sort(reverse=True)
    _, verb, pid = cand[0]
    api.cmd("%s P%d" % (verb, pid))


def _depots(api, B):
    if api.t < 48 or api.t - api.mem.get("dep_t", -999) < 72:
        return
    dep = api.depots or {}
    if len(dep) >= 3 or api.stock.get("res", 0) < 500:
        return
    cap = api.capital
    best = None
    tried = 0
    for pid in sorted(B):
        if pid in dep:
            continue
        pr = api.provs.get(pid, {})
        if not pr.get("supplied", True):
            continue
        tried += 1
        if tried > 8:
            break
        d = len(api.path(cap, pid) or [])
        if d < 3:
            continue
        if best is None or d > best[0]:
            best = (d, pid)
    if best and api.cmd("depot P%d 1" % best[1]).startswith("ok"):
        api.cmd("depot P%d 3" % cap)
        api.mem["dep_t"] = api.t


def _manage(api, B):
    cap = api.capital
    fill = {}
    for u in api.units:
        if u["prov"] in B:
            fill[u["prov"]] = fill.get(u["prov"], 0) + 1
    rec_ids, expand_ids, hold_ids, rest_ids = [], [], [], []
    garrison = {}
    land_free = bool(api.neutral_border)
    for u in api.units:
        if u.get("dom", 0) != 0 or u.get("path") or _planned(u):
            continue
        if u.get("state") in ("routing", "moving", "refitting", "assault", "digging"):
            continue
        if u["type"] == "rec":
            if not u.get("explore"):
                rec_ids.append(u["id"])
            continue
        if u.get("explore") or u.get("expand"):
            continue
        p = u["prov"]
        s = u.get("str", 0)
        inB = p in B
        if s < 35:
            if p != cap and (inB or u.get("front")):
                rest_ids.append(u["id"])
            continue
        if u.get("front"):
            hold_ids.append(u["id"])
        if inB and fill.get(p, 0) <= PER_PROV:
            continue
        if land_free and not inB and s >= 30 and u["type"] in EXPAND_TYPES:
            expand_ids.append(u["id"])
            continue
        if not B:
            continue
        open_ = [q for q in B if fill.get(q, 0) < PER_PROV]
        if not open_:
            continue
        dest = max(open_, key=lambda q: (100 if _stock(api, q) >= 60 else 0) - fill.get(q, 0))
        if inB and dest == p:
            continue
        fill[dest] = fill.get(dest, 0) + 1
        garrison.setdefault(dest, []).append(u["id"])
    if rec_ids:
        api.cmd("explore " + _ids(rec_ids[:12]))
    for ch in _chunks(rest_ids):
        api.cmd("move %s P%d" % (ch, cap))
    for ch in _chunks(hold_ids):
        api.cmd("hold " + ch)
    for ch in _chunks(expand_ids):
        api.cmd("expand " + ch)
    for dest, lst in garrison.items():
        for ch in _chunks(lst):
            api.cmd("move %s P%d" % (ch, dest))


def _attack(api, B):
    prep = api.mem.setdefault("prep", {})
    by_t = {}
    for u in api.units:
        if _planned(u) and not u.get("path"):
            by_t.setdefault(u["plan"], []).append(u)
    for tgt, us in by_t.items():
        ids = _ids([u["id"] for u in us])
        t0 = prep.get(str(tgt), api.t)
        b = max(u.get("bonus", 0) for u in us)
        if b > 1:
            b /= 100.0
        S = sum(u["str"] for u in us)
        E = (api.enemy.get(tgt) or {}).get("str", 0)
        if b >= 0.3 or api.t - t0 >= 12:
            if E and S < 2.2 * E:
                api.cmd("hold " + ids)
            else:
                api.cmd("move %s P%d" % (ids, tgt))
            prep.pop(str(tgt), None)

    occ = {}
    for u in api.units:
        if u.get("path") or _planned(u) or u.get("dom", 0) != 0:
            continue
        if u["prov"] not in B:
            continue
        if u["str"] < 50 or u.get("state") in ("routing", "shaken", "moving", "digging"):
            continue
        occ.setdefault(u["prov"], []).append(u)

    for pid, us in occ.items():
        if len(us) < 4 or any(u.get("dry") for u in us):
            continue
        S = sum(u["str"] for u in us)
        if S < 250:
            continue
        if sum(u.get("rdy", 50) for u in us) / float(len(us)) < 55:
            continue
        pr = api.provs.get(pid, {})
        if pr.get("stock", 0) < 60:
            continue
        best = None
        for nb in pr.get("nbrs", []):
            e = api.enemy.get(nb)
            if not e:
                continue
            E = max(e.get("str", 0), 1)
            nbp = api.provs.get(nb, {})
            fort = float(nbp.get("fort", 0) or 0)
            if fort >= 2 and S < 3.0 * E:
                continue
            if S < (2.2 + fort) * E:
                continue
            p = _take_prob(api, S, E, nb, us)
            if p is None:
                p = 1.0
            if p < 0.5:
                continue
            if best is None or p > best[0]:
                best = (p, nb)
        if best is None or str(best[1]) in prep:
            continue
        api.cmd("prepare %s P%d" % (_ids([u["id"] for u in us]), best[1]))
        prep[str(best[1])] = api.t
        api.count("prepared", 1)


def _fortify(api, B):
    ids = []
    for u in api.units:
        if u["prov"] not in B or u.get("path") or _planned(u):
            continue
        if u.get("state") != "ready" or u.get("fighting"):
            continue
        if u.get("str", 0) < 60 or u.get("fort_lv") or u.get("f_set"):
            continue
        ids.append(u["id"])
        if len(ids) >= 20:
            break
    if ids:
        api.cmd("fortify " + _ids(ids))


def _groups(api, B):
    if api.t - api.mem.get("grp_t", -999) < 48:
        return
    api.mem["grp_t"] = api.t
    gn = api.mem.setdefault("gn", {})
    byp = {}
    for u in api.units:
        if u["prov"] in B and not u.get("path") and u.get("state") not in ("moving", "routing"):
            byp.setdefault(u["prov"], []).append(u)
    for pid, us in byp.items():
        if len(us) < 3:
            continue
        name = "g%d" % pid
        members = gn.setdefault(name, [])
        new = [u["id"] for u in us if u["id"] not in members]
        if not new:
            continue
        if members:
            if not api.cmd("group %s + %s" % (name, _ids(new))).startswith("ok"):
                api.cmd("group %s %s" % (name, _ids(new)))
        else:
            api.cmd("group %s %s" % (name, _ids(new)))
        members.extend(new)


def _refit(api, B):
    if api.t - api.mem.get("refit_t", -999) < 96:
        return
    if not api.old_units:
        return
    api.mem["refit_t"] = api.t
    rc = api.refit_cost or {}
    st = dict(api.stock)
    ids = []
    for u in api.units:
        if len(ids) >= 40:
            break
        if not u.get("old") or u.get("path") or _planned(u):
            continue
        if u["prov"] in B or u.get("state") != "ready" or u.get("str", 0) < 60:
            continue
        c = rc.get(u["type"])
        if not c:
            continue
        if st.get("res", 0) - c.get("res", 0) < 400:
            continue
        if any(st.get(k, 0) < c.get(k, 0) for k in ("steel", "oil", "rare")):
            continue
        st["res"] = st.get("res", 0) - c.get("res", 0)
        for k in ("steel", "oil", "rare"):
            st[k] = st.get(k, 0) - c.get(k, 0)
        ids.append(u["id"])
    for ch in _chunks(ids):
        api.cmd("refit " + ch)


def tick(api):
    try:
        B = _border(api)
    except Exception:
        B = set()
    for f in (_diplomacy, _research, _recruit, _economy, _depots,
              _manage, _attack, _fortify, _groups, _refit):
        try:
            f(api, B)
        except Exception:
            pass
```

```feedback
Income went negative by day 5 because the starting army's upkeep was larger than the land could pay, and there is no way to reduce upkeep except by losing units. A per-unit upkeep field in api.units, or a total upkeep forecast, would help a lot. api.can_raise and api.costs only show raisable kinds, so the era of the army is hard to read; a field for the current era would help. The 'expand' order reports no reason when neutral land is out of reach. Trade and supply deal formats are clear, but a rate hint (res per strategic unit) would make pricing easier. Discovery results only show up in tech events; a short api.tree result with 'known' and 'effect' would help.
```

REVIEW: full