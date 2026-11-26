MIX = {"inf": 0.24, "mtn": 0.05, "mot": 0.08, "arm": 0.10, "mec": 0.07,
       "art": 0.11, "atg": 0.08, "eng": 0.06, "mil": 0.02, "cav": 0.03,
       "hvt": 0.04, "grn": 0.02}
PREF_RES = ["farming", "conscription", "inf.weapons", "arm.weapons",
            "atg.weapons", "art.weapons", "mot.mobility", "medicine",
            "arm.protection", "inf.protection", "discipline", "drill",
            "staffwork", "logistics", "fieldworks", "mec.weapons",
            "industry", "mining", "drilling"]
EXPAND_TYPES = ("inf", "mil", "mtn", "mot", "cav", "eng", "mec", "arm")
MIN_RATIO = 4.0
FORT_EXTRA = 3.0
MIN_ATTACKERS = 8
PREP_HOURS = 24
MAX_STRIKE = 14
EXPAND_PER_TICK = 8
MAX_REFIT = 12
MAX_REC = 3
RES_RESERVE = 150


def _can(api, t, bud):
    uc = api.unit_costs.get(t)
    if not uc:
        return False
    if bud["res"] < uc.get("res", 0) + RES_RESERVE:
        return False
    if bud["mp"] < uc.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if bud[k] < uc.get(k, 0):
            return False
    return True


def _spend(api, t, bud):
    uc = api.unit_costs.get(t, {})
    bud["res"] -= uc.get("res", 0)
    bud["mp"] -= uc.get("mp", 0)
    for k in ("steel", "oil", "rare"):
        bud[k] -= uc.get(k, 0)


def _ids(items):
    out = []
    for x in items:
        out.append(str(x["id"]) if isinstance(x, dict) else str(x))
    return ",".join(out)


def _recruit(api, units):
    if not (api.income >= 0 or api.res > 300):
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    bud = {"res": api.res, "mp": api.mp,
           "steel": api.stock.get("steel", 0),
           "oil": api.stock.get("oil", 0),
           "rare": api.stock.get("rare", 0)}
    if counts.get("rec", 0) < MAX_REC and _can(api, "rec", bud):
        if api.cmd("recruit rec P%d" % api.capital).startswith("ok"):
            counts["rec"] = counts.get("rec", 0) + 1
            _spend(api, "rec", bud)
    for _ in range(3):
        total = sum(counts.values()) + 1
        pick = None
        best = -1e9
        for t, w in MIX.items():
            if not _can(api, t, bud):
                continue
            d = w * total - counts.get(t, 0)
            if d > best:
                best = d
                pick = t
        if pick is None:
            break
        if not api.cmd("recruit %s P%d" % (pick, api.capital)).startswith("ok"):
            break
        counts[pick] = counts.get(pick, 0) + 1
        _spend(api, pick, bud)


def _research(api):
    if len(api.research) >= 2:
        return
    busy = set(r[0] for r in api.research)
    for line in PREF_RES:
        if line in busy:
            continue
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        cost = t.get("cost") or {}
        if api.res < cost.get("res", 0) + 60:
            continue
        ok = True
        for k, v in cost.items():
            if k != "res" and api.stock.get(k, 0) < v:
                ok = False
        if ok:
            api.cmd("research %s" % line)
            return


def _refit(api, units):
    if api.old_units <= 0 or api.income < 0:
        return
    if api.mem.get("refit_t", -99) > api.t - 4:
        return
    api.mem["refit_t"] = api.t
    cands = [u for u in units if u.get("old") and u.get("state") == "ready"
             and not u.get("path") and u.get("supplied")
             and u.get("prov") not in api.border]
    if not cands:
        return
    picked = []
    res_need = 0
    steel_need = 0
    oil_need = 0
    rare_need = 0
    for u in cands:
        if len(picked) >= MAX_REFIT:
            break
        rc = api.refit_cost.get(u["type"], {})
        if api.res - res_need - rc.get("res", 0) < 80:
            break
        if api.stock.get("steel", 0) - steel_need < rc.get("steel", 0):
            continue
        if api.stock.get("oil", 0) - oil_need < rc.get("oil", 0):
            continue
        if api.stock.get("rare", 0) - rare_need < rc.get("rare", 0):
            continue
        res_need += rc.get("res", 0)
        steel_need += rc.get("steel", 0)
        oil_need += rc.get("oil", 0)
        rare_need += rc.get("rare", 0)
        picked.append(u)
    if picked:
        api.cmd("refit " + _ids(picked))


def _attackers(api, tgt, units):
    nb = api.provs.get(tgt, {}).get("nbrs", [])
    out = []
    for u in units:
        if u.get("prov") not in nb:
            continue
        if api.provs.get(u.get("prov"), {}).get("owner") != "me":
            continue
        if u.get("path") or u.get("type") == "rec":
            continue
        if u.get("state") not in ("ready", "preparing"):
            continue
        if u.get("str", 0) < 70 or u.get("rdy", 0) < 80:
            continue
        out.append(u)
    return out


def _odds(att, es):
    if es is None:
        return 0.0
    s = sum(u.get("str", 0) for u in att)
    return s / max(float(es), 1.0)


def _need(api, tgt):
    fort = api.provs.get(tgt, {}).get("fort") or 0
    return MIN_RATIO + (FORT_EXTRA if fort >= 2 else 0.0)


def _free_rec(units):
    for u in units:
        if u["type"] == "rec" and u["state"] == "ready" and not u["path"] \
                and not u["explore"]:
            return u
    return None


def _stage_rec(api, units, att):
    r = _free_rec(units)
    if r is None or not att:
        return
    dest = att[0].get("prov")
    if dest is not None and r.get("prov") != dest:
        api.cmd("move %d P%d" % (r["id"], dest))


def _strike(api, units):
    m = api.mem
    prep = m.get("prep")
    if prep:
        tgt, t0, ids = prep
        if api.provs.get(tgt, {}).get("owner") == "me":
            m["prep"] = None
            return
        if api.t - t0 < PREP_HOURS:
            return
        m["prep"] = None
        byid = dict((u["id"], u) for u in units)
        alive = [byid[i] for i in ids if i in byid]
        if not alive:
            return
        att = _attackers(api, tgt, alive)
        es = api.enemy.get(tgt, {}).get("str")
        if len(att) >= MIN_ATTACKERS and _odds(att, es) >= _need(api, tgt) * 0.9:
            api.cmd("move %s P%d" % (_ids(att), tgt))
        else:
            api.cmd("hold %s" % _ids(alive))
        return

    own = [p for p, pr in api.provs.items() if pr.get("owner") == "me"]
    cands = set()
    for p in own:
        for nb in api.provs[p].get("nbrs", []):
            pr = api.provs.get(nb)
            if pr and pr.get("owner") == "enemy":
                cands.add(nb)
    best = None
    for tgt in cands:
        es = api.enemy.get(tgt, {}).get("str")
        if es is None:
            continue
        att = _attackers(api, tgt, units)
        if len(att) < MIN_ATTACKERS:
            continue
        r = _odds(att, es)
        if r >= _need(api, tgt) and (best is None or r > best[0]):
            best = (r, tgt, att)
    if best:
        r, tgt, att = best
        att = att[:MAX_STRIKE]
        ids = [u["id"] for u in att]
        _stage_rec(api, units, att)
        api.cmd("prepare %s P%d" % (_ids(ids), tgt))
        m["prep"] = (tgt, api.t, ids)


def _neutral_targets(api):
    # explored neutral provinces next to our land, nearest to the capital first
    own = [p for p, pr in api.provs.items() if pr.get("owner") == "me"]
    seen = set()
    out = []
    cap = api.provs.get(api.capital, {})
    cx, cy = cap.get("x", 0), cap.get("y0", 0)
    for p in own:
        for nb in api.provs[p].get("nbrs", []):
            if nb in seen:
                continue
            seen.add(nb)
            pr = api.provs.get(nb)
            if not pr or pr.get("owner") != "neutral":
                continue
            d = (pr.get("x", 0) - cx) ** 2 + (pr.get("y0", 0) - cy) ** 2
            out.append((d, nb))
    out.sort()
    return [nb for d, nb in out]


def _expand_far(api, units, used):
    m = api.mem
    claims = m.get("claims", {})
    # drop claims whose unit stopped expanding or whose target is no longer free
    live = {}
    byid = dict((u["id"], u) for u in units)
    for uid_s, (tgt, t0) in claims.items():
        uid = int(uid_s)
        u = byid.get(uid)
        pr = api.provs.get(tgt, {})
        if u and u.get("expand") and pr.get("owner") != "me" and api.t - t0 < 240:
            live[uid_s] = (tgt, t0)
    claimed = set(v[0] for v in live.values())
    free_targets = [t for t in _neutral_targets(api) if t not in claimed]
    if not free_targets:
        m["claims"] = live
        return
    cands = [u for u in units if u["state"] == "ready" and not u["path"]
             and not u["expand"] and not u["explore"]
             and u["type"] in EXPAND_TYPES and u["id"] not in used
             and u["prov"] not in api.border]
    cands.sort(key=lambda u: -u.get("str", 0))
    k = 0
    for tgt in free_targets:
        if k >= EXPAND_PER_TICK or k >= len(cands):
            break
        u = cands[k]
        if api.cmd("expand %d P%d" % (u["id"], tgt)).startswith("ok"):
            live[str(u["id"])] = (tgt, api.t)
            used.add(u["id"])
            k += 1
    m["claims"] = live


def _diplomacy(api, n):
    for o in list(api.offers_in):
        oid = o.get("id")
        if o.get("kind") == "pact":
            api.cmd("accept %s" % oid)
            continue
        if o.get("kind") == "trade":
            give = o.get("you_give", {})
            ok = True
            for k, v in give.items():
                if k in ("steel", "oil"):
                    if api.stock.get(k, 0) < v + 100:
                        ok = False
                elif k == "res":
                    if v > 150:
                        ok = False
                else:
                    ok = False
            if ok:
                api.cmd("accept %s" % oid)
    if n % 36 == 0:
        pending = set(o.get("to") for o in api.offers_out)
        for f in api.met:
            if f in api.pacts or f in pending:
                continue
            api.cmd("offer %s pact 240" % f)
    if n % 96 == 0:
        for f in api.met:
            api.cmd("say %s Scandia keeps its pacts and takes only free land." % f)


def tick(api):
    m = api.mem
    n = m.get("n", 0) + 1
    m["n"] = n
    units = api.units

    try:
        _recruit(api, units)
    except Exception:
        pass

    try:
        _research(api)
    except Exception:
        pass

    try:
        _diplomacy(api, n)
    except Exception:
        pass

    used = set()
    try:
        if api.unexplored:
            explorers = [u for u in units if u["type"] == "rec" and u["state"] == "ready"
                         and not u["path"] and not u["explore"]]
            if len(explorers) > 1:
                pick = explorers[:2]
                api.cmd("explore " + _ids(pick))
                used.update(u["id"] for u in pick)
    except Exception:
        pass

    try:
        _strike(api, units)
        for u in units:
            if u["state"] == "preparing":
                used.add(u["id"])
    except Exception:
        pass

    try:
        _refit(api, units)
    except Exception:
        pass

    try:
        _expand_far(api, units, used)
    except Exception:
        pass

    idle = [u for u in units if u["state"] == "ready" and not u["path"]
            and not u["front"] and not u["expand"] and not u["explore"]
            and u["type"] != "rec" and u["id"] not in used]

    try:
        rest = [str(u["id"]) for u in idle]
        if rest:
            api.cmd("front " + ",".join(rest))
    except Exception:
        pass

    try:
        if n % 12 == 0:
            core = ("inf", "mtn", "mil", "atg", "mec", "arm", "hvt", "art", "grn")
            new = [str(u["id"]) for u in units if u["front"] and not u["group"]
                   and u["type"] in core]
            if new:
                if not m.get("grp"):
                    api.cmd("group line " + ",".join(new))
                    m["grp"] = True
                else:
                    api.cmd("group line + " + ",".join(new))
    except Exception:
        pass

    m["calls"] = n
