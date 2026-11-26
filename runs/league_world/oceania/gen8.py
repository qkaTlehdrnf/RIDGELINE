W = {"inf": 0.12, "mot": 0.10, "arm": 0.20, "mec": 0.14, "art": 0.20,
     "atg": 0.08, "mtn": 0.05, "eng": 0.06, "rec": 0.02}

RESEARCH = ["medicine", "logistics", "fieldworks", "art.weapons", "arm.weapons",
            "mining", "drilling", "conscription", "drill", "discipline",
            "staffwork", "industry", "farming", "refining",
            "mot.mobility", "inf.weapons", "inf.protection", "arm.protection"]

RES_RESERVE = 150
P_GATE = 0.65
NEED_MULT = 2.5
MIN_ATTACKERS = 10
MAX_ATTACK_FORT = 1
PREP_WAIT = 24
LAUNCH_MIN_RDY = 50
MIN_READY = 70
REFIT_RES_FLOOR = 250
PACT_EVERY = 96
REST_BELOW = 35
REST_UNTIL = 80
DEPOT_RES = 200
DEPOT_LOAD = 0.6
DEPOT_GAP = 24
DEPOT_SEARCH = 10
ECON_FLOOR = 700
ECON_GAP = 12
ECON_MAX_WORKS = 3


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def _idlist(ids):
    return ",".join(str(i) for i in ids)


def _nbs(p):
    out = []
    for nb in (p.get("nbrs") or []):
        try:
            if isinstance(nb, dict):
                out.append(int(nb.get("id", -1)))
            elif isinstance(nb, (list, tuple)):
                out.append(int(nb[0]))
            elif isinstance(nb, str):
                out.append(int(nb.strip().lstrip("~P")))
            else:
                out.append(int(nb))
        except Exception:
            pass
    return [x for x in out if x >= 0]


def _bfs(provs, start, maxd, ok, walk):
    seen = {start: 0}
    q = [start]
    out = []
    i = 0
    while i < len(q):
        p = q[i]
        i += 1
        d = seen[p]
        if d > 0 and ok(p):
            out.append((d, p))
        if d >= maxd:
            continue
        pr = provs.get(p)
        if not pr:
            continue
        if d > 0 and not walk(p):
            continue
        for n in _nbs(pr):
            if n not in seen:
                seen[n] = d + 1
                q.append(n)
    return out


def _diplomacy(api):
    m = api.mem
    for o in (api.offers_in or []):
        try:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o.get("id"))
        except Exception:
            pass
    pacts = api.pacts or {}
    out_to = set(o.get("to") for o in (api.offers_out or []))
    last = m.setdefault("pact_t", {})
    for f in (api.met or []):
        if f in pacts or f in out_to:
            continue
        if api.t - last.get(f, -10000) < PACT_EVERY:
            continue
        last[f] = api.t
        try:
            api.cmd("offer %s pact 240" % f)
        except Exception:
            pass


def _recruit(api, counts, total):
    budget = api.res - RES_RESERVE
    mp = api.mp
    stock = api.stock
    done = 0
    cap = 6 if (api.neutral_border and api.t < 2400) else 4
    while done < cap:
        best = None
        bd = -1e9
        tot = total + done + 1
        for ty, w in W.items():
            uc = api.unit_costs.get(ty)
            if not uc:
                continue
            if uc.get("res", 0) > budget or uc.get("mp", 0) > mp:
                continue
            if (uc.get("steel", 0) > (stock.get("steel", 0) or 0) or
                    uc.get("oil", 0) > (stock.get("oil", 0) or 0) or
                    uc.get("rare", 0) > (stock.get("rare", 0) or 0)):
                continue
            d = w * tot - counts.get(ty, 0)
            if d > bd:
                bd = d
                best = ty
        if best is None:
            break
        r = api.cmd("recruit %s 1 P%d" % (best, api.capital))
        if not str(r).startswith("ok"):
            break
        uc = api.unit_costs[best]
        counts[best] = counts.get(best, 0) + 1
        budget -= uc.get("res", 0)
        mp -= uc.get("mp", 0)
        done += 1


def _terrain_dfn(p):
    s = str(p.get("terrain") or "")
    if "mountain" in s or s.startswith("mtn"):
        return 2.0
    if "hill" in s:
        return 1.5
    if "forest" in s:
        return 1.25
    return 1.0


def _p_take(api, a, d, fort, tdfn, rdy, heavy_share, climb):
    a_eff = a / (1.0 + 0.15 * climb)
    model = api.model or {}
    if not model or "features" not in model:
        z = (a_eff - (d * (1.6 + 0.3 * fort) + 40)) / 40.0
        z = max(-20.0, min(20.0, z))
        return 1.0 / (1.0 + math.exp(-z))
    vals = {
        "log_ratio": math.log((a_eff + 1.0) / (d + 1.0)),
        "terrain_dfn": tdfn,
        "fort": fort,
        "city": 0.0,
        "bonus": 0.0,
        "att_rdy": rdy / 100.0,
        "heavy_share": heavy_share,
        "dirs": 1.0,
    }
    z = model.get("b", 0.0)
    feats = model["features"]
    w = model["w"]
    mean = model["mean"]
    std = model["std"]
    for i, f in enumerate(feats):
        x = vals.get(f, 0.0)
        s = std[i] if std[i] else 1.0
        z += w[i] * (x - mean[i]) / s
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _launch_ok(api, tgt, ids, alive, owner_name):
    tp = api.provs.get(tgt)
    if not tp or tp.get("owner") != "enemy":
        return False
    en = api.enemy.get(tgt)
    if not en or not en.get("exact"):
        return False
    live = [alive[i] for i in ids if i in alive]
    if len(live) < MIN_ATTACKERS:
        return False
    avg_rdy = sum(u.get("rdy", 0) for u in live) / float(len(live))
    if avg_rdy < LAUNCH_MIN_RDY:
        return False
    total = sum(u["str"] for u in live)
    fort = tp.get("fort") or 0
    climb = max(0, (tp.get("elev") or 0) - (api.provs.get(live[0]["prov"], {}).get("elev") or 0))
    need = (en["str"] * (1.6 + 0.3 * fort) + 40) * (1.0 + 0.15 * climb)
    return total >= need * 2.0


def _attack(api, m, t, units, provs):
    preps = m.setdefault("prep", {})
    alive = {u["id"]: u for u in units}
    pacts = api.pacts or {}
    owner_name = api.owner_name or {}

    for key in list(preps.keys()):
        pr = preps[key]
        src, tgt = pr["src"], pr["tgt"]
        ids = [i for i in pr["ids"] if i in alive and alive[i]["prov"] == src]
        if not ids or t - pr["t"] > 72:
            del preps[key]
            continue
        if t - pr["t"] >= PREP_WAIT:
            if _launch_ok(api, tgt, ids, alive, owner_name):
                api.cmd("move %s P%d" % (_idlist(ids), tgt))
            else:
                api.cmd("hold %s" % _idlist(ids))
            del preps[key]

    by_prov = {}
    for u in units:
        if u.get("state") in ("routing", "refitting", "pinned"):
            continue
        by_prov.setdefault(u["prov"], []).append(u)

    busy_src = set(pr["src"] for pr in preps.values())
    for src, lst in by_prov.items():
        p = provs.get(src)
        if not p or p.get("owner") != "me" or src in busy_src:
            continue
        if (p.get("stock") or 0) < 60:
            continue
        avail = [u for u in lst if u.get("state") in ("ready", "defending")
                 and u.get("rdy", 100) >= MIN_READY and not u.get("dry")]
        if len(avail) < MIN_ATTACKERS:
            continue
        avail.sort(key=lambda u: -u["str"])
        total_str = sum(u["str"] for u in avail)
        best = None
        for tgt in _nbs(p):
            tp = provs.get(tgt)
            if not tp or tp.get("owner") != "enemy":
                continue
            if owner_name.get(tgt) in pacts:
                continue
            en = api.enemy.get(tgt)
            if not en or not en.get("exact"):
                continue
            estr = en["str"]
            fort = tp.get("fort") or 0
            if fort > MAX_ATTACK_FORT:
                continue
            climb = max(0, (tp.get("elev") or 0) - (p.get("elev") or 0))
            need = (estr * (1.6 + 0.3 * fort) + 40) * (1.0 + 0.15 * climb)
            want = need * NEED_MULT
            if total_str < want:
                continue
            picked = []
            acc = 0.0
            for u in avail:
                if acc >= want:
                    break
                picked.append(u)
                acc += u["str"]
            if len(picked) < MIN_ATTACKERS or len(picked) >= len(avail):
                continue
            heavy = sum(1 for u in picked if u["type"] in ("art", "eng", "arm"))
            hs = heavy / float(len(picked))
            avg_rdy = sum(u.get("rdy", 100) for u in picked) / float(len(picked))
            p_take = _p_take(api, acc, estr, fort, _terrain_dfn(tp),
                             avg_rdy, hs, climb)
            if p_take < P_GATE:
                continue
            score = p_take - 0.05 * fort
            if best is None or score > best[0]:
                best = (score, tgt, picked)
        if best is not None:
            _, tgt, picked = best
            api.cmd("prepare %s P%d" % (_ids(picked), tgt))
            preps[str(src) + "_" + str(tgt)] = {
                "src": src, "tgt": tgt, "t": t,
                "ids": [u["id"] for u in picked]}
            busy_src.add(src)


def _release_rest(rest, by_id):
    for uid in list(rest.keys()):
        u = by_id.get(uid)
        if u is None or u.get("rdy", 0) >= REST_UNTIL:
            del rest[uid]


def _send_rest(api, units, rest, border, provs):
    tired = [u for u in units if u["type"] != "rec" and u["prov"] in border
             and u.get("rdy", 100) < REST_BELOW
             and u.get("state") in ("ready", "defending")
             and not u.get("path") and u["id"] not in rest]
    if not tired:
        return
    groups = {}
    for u in tired:
        groups.setdefault(u["prov"], []).append(u)

    def own(p):
        pr = provs.get(p) or {}
        return pr.get("owner") == "me"

    for prov, lst in groups.items():
        cands = _bfs(provs, prov, 3,
                     lambda p: own(p) and p not in border and bool((provs.get(p) or {}).get("supplied")),
                     own)
        if not cands:
            continue
        cands.sort(key=lambda x: x[0])
        dest = cands[0][1]
        ids = [u["id"] for u in lst[:200]]
        if str(api.cmd("move %s P%d" % (_idlist(ids), dest))).startswith("ok"):
            for i in ids:
                rest[i] = api.t


def _depots(api):
    m = api.mem
    if api.res < DEPOT_RES or api.t - m.get("dep_t", -10 ** 9) < DEPOT_GAP:
        return
    deps = api.depots or {}
    if not deps:
        return
    worst = None
    wr = 0.0
    for k, d in deps.items():
        cap = d.get("capacity") or 1
        r = (d.get("load") or 0) / float(cap)
        if r > wr:
            wr = r
            worst = int(k)
    if worst is None or wr < DEPOT_LOAD:
        return
    mine = set(int(k) for k in deps)
    provs = api.provs
    border = api.border

    def own(p):
        return (provs.get(p) or {}).get("owner") == "me"

    def good(p):
        pr = provs.get(p) or {}
        return (own(p) and p not in mine and p not in border
                and bool(pr.get("supplied")) and not pr.get("harsh"))

    cands = _bfs(provs, worst, DEPOT_SEARCH, good, own)
    if not cands:
        return
    cands.sort(key=lambda x: -x[0])
    dest = cands[0][1]
    if str(api.cmd("depot P%d" % dest)).startswith("ok"):
        m["dep_t"] = api.t


def _economy(api):
    # Spend surplus res on development and roads in the richest own provinces.
    m = api.mem
    if api.t - m.get("econ_t", -10 ** 9) < ECON_GAP:
        return
    if api.res < ECON_FLOOR:
        return
    econ = api.economy or {}
    works = econ.get("works") or []
    if len(works) >= ECON_MAX_WORKS:
        return
    busy = set()
    for w in works:
        try:
            busy.add(int(w[1]))
        except Exception:
            pass
    rows = econ.get("provs") or []
    stock = api.stock
    for pr in rows:  # richest first
        try:
            p = int(pr.get("prov"))
        except Exception:
            continue
        if p in busy:
            continue
        dev = pr.get("dev") or 0
        infra = pr.get("infra") or 0
        if dev < 4 and (stock.get("coal", 0) or 0) >= 8 * (dev + 1) and infra >= 1:
            r = api.cmd("develop P%d" % p)
        elif infra < 2 and dev >= 2 and (stock.get("steel", 0) or 0) >= 6 * (infra + 1):
            r = api.cmd("build P%d" % p)
        else:
            continue
        if str(r).startswith("ok"):
            m["econ_t"] = api.t
            return


def _refit(api, units, rest):
    if api.res < REFIT_RES_FLOOR:
        return
    border = api.border
    cands = [u for u in units if u.get("old") and u.get("state") == "ready"
             and u.get("supplied") and u["prov"] not in border and u["id"] not in rest]
    if not cands:
        return
    rc = api.refit_cost or {}
    budget = api.res - REFIT_RES_FLOOR
    pick = []
    for u in cands:
        c = (rc.get(u["type"]) or {}).get("res", 0)
        if c <= 0 or c > budget:
            continue
        budget -= c
        pick.append(u)
        if len(pick) >= 20:
            break
    if pick:
        api.cmd("refit " + _ids(pick))


def _research(api):
    if len(api.research) >= 2:
        return
    busy = set(r[0] for r in api.research)
    stock = api.stock
    for line in RESEARCH:
        if line in busy:
            continue
        tc = api.tech.get(line)
        if not tc or tc.get("status") != "open":
            continue
        cost = tc.get("cost") or {}
        ok = True
        for k, v in cost.items():
            have = stock.get(k, 0) or 0
            reserve = RES_RESERVE if k == "res" else 0
            if have - v < reserve:
                ok = False
                break
        if not ok:
            continue
        if str(api.cmd("research " + line)).startswith("ok"):
            return


def _tick(api):
    m = api.mem
    t = api.t
    units = api.units
    provs = api.provs
    border = api.border

    try:
        _diplomacy(api)
    except Exception:
        pass

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1

    try:
        _recruit(api, counts, len(units))
    except Exception:
        pass

    by_id = {u["id"]: u for u in units}
    rest = m.setdefault("rest", {})
    try:
        _release_rest(rest, by_id)
    except Exception:
        pass
    try:
        _send_rest(api, units, rest, border, provs)
    except Exception:
        pass

    try:
        scouts = [u for u in units if u["type"] == "rec" and not u.get("explore")]
        if scouts:
            api.cmd("explore " + _ids(scouts))
    except Exception:
        pass

    try:
        idle = [u for u in units if u["type"] != "rec" and not u.get("path")
                and not u.get("front") and not u.get("expand")
                and not u.get("explore") and u.get("state") == "ready"
                and u["id"] not in rest]
        on_border = [u for u in idle if u["prov"] in border]
        inland = [u for u in idle if u["prov"] not in border]
        if on_border:
            api.cmd("front " + _ids(on_border))
        if inland:
            if api.neutral_border:
                api.cmd("expand " + _ids(inland))
            else:
                api.cmd("front " + _ids(inland))
    except Exception:
        pass

    try:
        _attack(api, m, t, units, provs)
    except Exception:
        pass

    try:
        _refit(api, units, rest)
    except Exception:
        pass

    try:
        _depots(api)
    except Exception:
        pass

    try:
        _economy(api)
    except Exception:
        pass

    try:
        _research(api)
    except Exception:
        pass


def tick(api):
    try:
        _tick(api)
    except Exception:
        pass
