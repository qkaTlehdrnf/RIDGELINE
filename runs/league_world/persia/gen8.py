RES_RESERVE = 30
PREP_TICKS = 12
P_MIN = 0.5
MIN_READY = 60
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


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def _diplomacy(api):
    # Accept only dated pacts: open-ended pacts froze the land last war.
    for o in list(api.offers_in or []):
        if o.get("kind") == "pact" and o.get("hours"):
            api.cmd("accept %s" % o["id"])
        else:
            api.cmd("reject %s" % o["id"])


def _steel_trade(api):
    # Steel ran out in every war while res and oil piled up: ask for steel
    # with surplus res, one offer per tick, at most one per faction per 96 h.
    if api.stock.get("steel", 0) >= 100 or api.stock.get("res", 0) < 800:
        return
    last = api.mem.setdefault("trade_t", {})
    pending = set(o.get("to") for o in (api.offers_out or []))
    for f in api.met or []:
        if f in pending:
            continue
        if api.t - last.get(f, -999) < 96:
            continue
        api.cmd("offer %s trade 60 res for 20 steel" % f)
        last[f] = api.t
        break


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
        # Steel-free fallbacks when steel is short.
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


def _research(api):
    running = [r[0] for r in api.research]
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
        return 2.2, 0
    if fort == 1:
        return 3.5, 1
    if fort == 2:
        return 5.0, 2
    return 7.0, 3


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
    try:
        _diplomacy(api)
    except Exception:
        pass
    try:
        _steel_trade(api)
    except Exception:
        pass
    try:
        _research(api)
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
