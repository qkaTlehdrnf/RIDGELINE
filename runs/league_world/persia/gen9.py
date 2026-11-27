RES_RESERVE = 30
DISC_RESERVE = 80
PREP_TICKS = 12
P_MIN = 0.5
MIN_READY = 55
EXPAND_SHARE = 0.6
REFIT_MIN_READY = 50
REFIT_PER_TICK = 30
MIN_WAVE = 3

BASE_MIX = {"inf": 0.16, "mil": 0.02, "mtn": 0.05, "grn": 0.06, "mot": 0.11,
            "arm": 0.15, "mec": 0.08, "atg": 0.06, "art": 0.15, "eng": 0.05,
            "rkt": 0.05, "hvt": 0.05, "cav": 0.04}

LINES = ["farming", "industry", "conscription", "logistics", "art.weapons",
         "mot.mobility", "inf.protection", "arm.weapons", "staffwork", "drill",
         "discipline", "medicine", "fieldworks", "mtn.weapons", "grn.weapons",
         "arm.protection", "mining", "drilling", "refining"]

DISC_PRIO = ["iron_working", "siege_engines", "roads", "horse_riding", "masonry",
             "pikes_crossbows", "stirrup", "galleys", "crop_rotation", "trebuchet",
             "castles", "sailing", "banking", "gunpowder", "matchlock", "steam_power",
             "rifling", "steel_guns", "combustion", "machine_guns", "tanks",
             "heavy_artillery", "flight", "mechanisation", "heavy_armour",
             "assault_rifles", "rocket_artillery", "jet_engines"]


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def _diplomacy(api):
    # Accept only dated pacts: open-ended pacts froze the land last war.
    for o in list(api.offers_in or []):
        if o.get("kind") == "pact" and o.get("hours"):
            api.cmd("accept %s" % o["id"])
        else:
            api.cmd("reject %s" % o["id"])


def _trade(api):
    # One standing trade offer per tick: res for steel when steel is short,
    # oil for steel when oil piles up. At most one per faction per 96 h.
    st = api.stock
    last = api.mem.setdefault("trade_t", {})
    pending = set(o.get("to") for o in (api.offers_out or []))
    if st.get("steel", 0) < 100 and st.get("res", 0) >= 800:
        kind = "res"
    elif st.get("oil", 0) > 400 and st.get("steel", 0) < 150:
        kind = "oil"
    else:
        return
    for f in api.met or []:
        if f in pending or api.t - last.get(f, -999) < 96:
            continue
        if kind == "res":
            api.cmd("offer %s trade 60 res for 20 steel" % f)
        else:
            api.cmd("offer %s trade 60 oil for 25 steel" % f)
        last[f] = api.t
        break


def _discover(api):
    # Returns True while saving up for a discovery (upgrades then wait).
    tree = api.tree or {}
    running = [r[0] for r in (api.research or [])]
    if any(d in running for d in DISC_PRIO):
        return False
    if len(running) >= 2:
        return False
    for d in DISC_PRIO:
        info = tree.get(d)
        if not info or info.get("status") != "open":
            continue
        need = info.get("res_now") or (info.get("cost") or {}).get("res", 0) or 0
        if api.stock.get("res", 0) < need + DISC_RESERVE:
            return True
        api.cmd("research " + d)
        return False
    return False


def _research(api, saving):
    if saving:
        return
    running = [r[0] for r in (api.research or [])]
    slots = 2 - len(running)
    if slots <= 0:
        return
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
        ok = True
        for k, v in cost.items():
            need = v + (RES_RESERVE if k == "res" else 0)
            if api.stock.get(k, 0) < need:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            slots -= 1


def _economy(api):
    eco = api.economy or {}
    works = eco.get("works") or []
    if len(works) >= 3 or api.res < 400:
        return
    started = 0
    for r in eco.get("provs") or []:
        if started >= 2:
            break
        if r.get("can_dev") and r.get("dev", 0) + 1 <= r.get("room", 0):
            if api.cmd("develop P%d" % r["prov"]).startswith("ok"):
                started += 1
        elif r.get("can_infra") and r.get("infra", 0) < 1 and r.get("dev", 0) >= 2:
            if api.cmd("build P%d" % r["prov"]).startswith("ok"):
                started += 1


def _refit(api):
    rc = api.refit_cost
    if not rc:
        return
    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    border = api.border or {}
    cands = []
    for u in api.units:
        if not u.get("old"):
            continue
        if u.get("state") != "ready" or u.get("path"):
            continue
        if u.get("rdy", 0) < REFIT_MIN_READY or not u.get("supplied"):
            continue
        if u.get("prov") not in mine or u.get("prov") in border:
            continue
        cands.append(u)
    budget = dict(api.stock)
    chosen = []
    for u in cands:
        if len(chosen) >= REFIT_PER_TICK:
            break
        c = rc.get(u["type"])
        if not c:
            continue
        ok = True
        for k, v in c.items():
            need = v + (RES_RESERVE if k == "res" else 0)
            if budget.get(k, 0) < need:
                ok = False
                break
        if not ok:
            continue
        for k, v in c.items():
            budget[k] = budget.get(k, 0) - v
        chosen.append(u)
    if chosen:
        api.cmd("refit " + _ids(chosen))


def _mix(api):
    w = dict(BASE_MIX)
    st = api.stock
    oil = st.get("oil", 0)
    steel = st.get("steel", 0)
    if oil > 300 and steel > 200:
        for k in ("mot", "arm", "hvt", "mec"):
            w[k] = w.get(k, 0) * 1.7
    if oil > 900 and steel > 700:
        for k in ("arm", "hvt", "mec"):
            w[k] = w.get(k, 0) * 1.5
    if steel < 30:
        w["cav"] = w.get("cav", 0) * 2.0
        w["inf"] = w.get("inf", 0) * 1.3
    if st.get("rare", 0) > 80:
        w["rkt"] = w.get("rkt", 0) + 0.04
    return w


def _affordable(api, typ):
    uc = api.unit_costs.get(typ)
    if not uc:
        return False
    st = api.stock
    if st.get("res", 0) < uc.get("res", 0) + RES_RESERVE:
        return False
    if api.mp < uc.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < uc.get(k, 0):
            return False
    return True


def _recruit(api, cnt, total):
    if api.res < RES_RESERVE:
        return
    if api.income < 0 and api.res < 150:
        return
    if cnt.get("rec", 0) < 2 and _affordable(api, "rec"):
        r = api.cmd("recruit rec P%d" % api.capital)
        if r.startswith("ok"):
            cnt["rec"] = cnt.get("rec", 0) + 1
            total += 1
    w = _mix(api)
    sum_w = sum(w.values())
    for _ in range(2):
        best, bd = None, -1e9
        size = total + 1
        for typ, wt in w.items():
            if wt <= 0 or not _affordable(api, typ):
                continue
            d = wt / sum_w * size - cnt.get(typ, 0)
            if d > bd:
                best, bd = typ, d
        if best is None:
            break
        r = api.cmd("recruit %s P%d" % (best, api.capital))
        if not r.startswith("ok"):
            break
        cnt[best] = cnt.get(best, 0) + 1
        total += 1


def _assign(api):
    units = api.units
    total = len(units)
    n_exp = sum(1 for u in units if u.get("expand"))
    idle = []
    for u in units:
        if u.get("path"):
            continue
        if u.get("state") not in ("ready", "refitting"):
            continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("group"):
            continue
        idle.append(u)
    scouts, exp, fr = [], [], []
    for u in idle:
        if u["type"] == "rec":
            if api.unexplored:
                scouts.append(u)
        elif (u["type"] in ("art", "atg", "eng") or not api.neutral_border
              or n_exp >= EXPAND_SHARE * total):
            fr.append(u)
        else:
            exp.append(u)
            n_exp += 1
    if scouts:
        api.cmd("explore " + _ids(scouts))
    if exp:
        api.cmd("expand " + _ids(exp))
    if fr:
        api.cmd("front " + _ids(fr))


def _tdfn(pr):
    t = str(pr.get("terrain", ""))
    if "mtn" in t or "mountain" in t:
        return 2.0
    if "hill" in t:
        return 1.5
    if "forest" in t:
        return 1.25
    return 1.0


def _pwin(api, att, srcs, q, sa, sd):
    m = api.model
    if not m or "w" not in m or "features" not in m:
        return None
    pr = api.provs.get(q, {})
    n = float(len(att)) or 1.0
    avg_rdy = sum(u.get("rdy", 50) for u in att) / n / 100.0
    heavy = sum(1 for u in att if u["type"] in ("art", "eng", "arm")) / n
    vals = {
        "log_ratio": math.log((sa + 1.0) / (sd + 1.0)),
        "terrain_dfn": _tdfn(pr),
        "fort": float(pr.get("fort", 0) or 0),
        "city": 1.0 if pr.get("city") else 0.0,
        "bonus": 0.0,
        "att_rdy": avg_rdy,
        "heavy_share": heavy,
        "dirs": float(len(srcs)),
    }
    z = m["b"]
    for i, name in enumerate(m["features"]):
        if name not in vals:
            continue
        z += m["w"][i] * (vals[name] - m["mean"][i]) / m["std"][i]
    return 1.0 / (1.0 + math.exp(-z))


def _thresholds(fort):
    # (strength ratio needed, artillery needed)
    if fort == 0:
        return 2.5, 0
    if fort == 1:
        return 3.5, 1
    if fort == 2:
        return 4.5, 2
    return 6.0, 3


def _attack(api):
    mem = api.mem
    prep = mem.setdefault("prep", {})
    t = api.t
    for q in list(prep.keys()):
        if t - prep[q] > 60:
            del prep[q]
    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    by_prov = {}
    for u in api.units:
        if u.get("path"):
            continue
        if u.get("prov") in mine:
            by_prov.setdefault(u["prov"], []).append(u)
    cands = {}
    for p in by_prov:
        for q in api.provs[p].get("nbrs", []):
            if q in api.enemy and api.provs.get(q, {}).get("owner") != "me":
                cands.setdefault(q, []).append(p)
    order = sorted(cands.keys(), key=lambda q: (
        api.provs.get(q, {}).get("fort", 0) or 0,
        api.enemy[q].get("str", 0)))
    used = set()
    for q in order:
        srcs = cands[q]
        if q in used:
            continue
        pr = api.provs.get(q, {})
        fort = pr.get("fort", 0) or 0
        ratio, arty_need = _thresholds(fort)
        en = api.enemy[q]
        sd = en.get("str", 0) * 1.3
        att = []
        for p in srcs:
            for u in by_prov.get(p, []):
                if u["id"] in used or u["type"] == "rec":
                    continue
                if u.get("rdy", 0) >= MIN_READY and u.get("str", 0) >= 50 and \
                   u.get("state") in ("ready", "preparing"):
                    att.append(u)
        if len(att) < MIN_WAVE:
            api.count("gate_wave_small")
            continue
        sa = sum(u["str"] * u.get("rdy", 50) / 100.0 for u in att)
        if sa < ratio * sd:
            api.count("gate_ratio")
            continue
        arty = sum(1 for u in att if u["type"] in ("art", "rkt"))
        if arty < arty_need:
            api.count("gate_arty")
            continue
        p_win = _pwin(api, att, srcs, q, sa, sd)
        if p_win is not None and p_win < P_MIN:
            api.count("gate_model")
            continue
        if q not in prep:
            api.cmd("prepare %s P%d" % (_ids(att), q))
            prep[q] = t
            api.count("prep_started")
            used.update(u["id"] for u in att)
        elif t - prep[q] >= PREP_TICKS:
            api.cmd("move %s P%d" % (_ids(att), q))
            del prep[q]
            api.count("launched")
            used.update(u["id"] for u in att)
            break


def tick(api):
    api.mem["n"] = api.mem.get("n", 0) + 1
    cnt = {}
    for u in api.units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    total = len(api.units)
    saving = False
    try:
        _diplomacy(api)
    except Exception:
        pass
    try:
        _trade(api)
    except Exception:
        pass
    try:
        saving = _discover(api)
    except Exception:
        pass
    try:
        _research(api, saving)
    except Exception:
        pass
    try:
        _economy(api)
    except Exception:
        pass
    try:
        _refit(api)
    except Exception:
        pass
    try:
        _recruit(api, cnt, total)
    except Exception:
        pass
    try:
        _assign(api)
    except Exception:
        pass
    try:
        _attack(api)
    except Exception:
        pass
