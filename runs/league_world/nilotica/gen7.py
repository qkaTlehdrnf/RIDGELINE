INF = ("inf", "mil", "mtn", "mot", "cav")
ARMOURED = ("arm", "hvt", "mec")
LINES = [
    "farming", "conscription", "industry", "inf.protection", "fieldworks",
    "logistics", "art.weapons", "mining", "medicine", "drill", "discipline",
    "inf.weapons", "arm.protection", "arm.weapons", "atg.weapons",
    "mtn.protection", "mot.mobility", "mot.weapons", "hvt.protection",
    "hvt.weapons", "mec.protection", "staffwork",
]
TERRAIN_DFN = {"forest": 1.25, "hill": 1.5, "mountain": 2.0}


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def _bon(u):
    b = u.get("bonus", 0) or 0
    return b * 100 if b <= 1 else b


def _ok(api, t, n=1):
    c = api.costs.get(t, (0, 0))
    uc = api.unit_costs.get(t, {}) or {}
    if api.res < c[0] * n + 40 or api.mp < c[1] * n:
        return False
    st = api.stock
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < uc.get(k, 0) * n:
            return False
    return True


def _pick(api, counts, total, armour):
    oil = api.stock.get("oil", 0)
    steel = api.stock.get("steel", 0)
    rich = oil >= 800 and steel >= 400
    prio = []
    rec_target = 6 if api.t < 400 else 2
    if counts.get("rec", 0) < rec_target and total >= 4:
        prio.append("rec")
    if counts.get("art", 0) < 0.18 * total:
        prio.append("art")
    if armour and counts.get("atg", 0) < 0.10 * total:
        prio.append("atg")
    arm_share = 0.22 if rich else (0.12 if oil >= 200 else 0.0)
    mot_share = 0.20 if rich else (0.12 if oil >= 150 else 0.0)
    hvt_share = 0.08 if (rich and total >= 60) else 0.0
    if total >= 30 and counts.get("arm", 0) < arm_share * total:
        prio.append("arm")
    if total >= 30 and counts.get("mot", 0) < mot_share * total:
        prio.append("mot")
    if hvt_share and counts.get("hvt", 0) < hvt_share * total:
        prio.append("hvt")
    if total >= 60 and counts.get("eng", 0) < 0.05 * total:
        prio.append("eng")
    prio.append("inf")
    for t in prio:
        if _ok(api, t):
            return t
    return None


def _refit(api):
    try:
        if (api.old_units or 0) <= 0:
            return
        border = api.border or {}
        rc = api.refit_cost or {}
        cands = [u for u in api.units
                 if u.get("old") and u.get("state") == "ready"
                 and u.get("supplied") and u["prov"] not in border]
        ids = []
        res_used = 0
        st_used = {"steel": 0, "oil": 0, "rare": 0}
        for u in cands[:40]:
            c = rc.get(u["type"], {}) or {}
            if api.res - res_used - c.get("res", 0) < 400:
                break
            short = False
            for k in ("steel", "oil", "rare"):
                if api.stock.get(k, 0) - st_used[k] < c.get(k, 0):
                    short = True
            if short:
                continue
            res_used += c.get("res", 0)
            for k in ("steel", "oil", "rare"):
                st_used[k] += c.get(k, 0)
            ids.append(u)
        if ids:
            api.cmd("refit " + _ids(ids))
    except Exception:
        pass


def _dig(api):
    # Fortify settled front units on border provinces: a holding line
    # instead of constant reshuffling. Every 24 h, only if enough units.
    try:
        if api.t % 24 != 0:
            return
        border = api.border or {}
        cands = []
        for u in api.units:
            if u["type"] == "rec" or u.get("state") != "ready":
                continue
            if u.get("path") or u.get("plan", -1) not in (-1, None):
                continue
            if u["prov"] not in border or not u.get("front"):
                continue
            pr = api.provs.get(u["prov"]) or {}
            if (pr.get("fort") or 0) >= 2:
                continue
            if u.get("rdy", 0) < 60:
                continue
            cands.append(u)
        if len(cands) >= 6:
            api.cmd("fortify " + _ids(cands[:60]))
    except Exception:
        pass


def _forward_depot(api):
    # At most two extra depots, opened far from the capital so supply
    # reaches the front sooner. Only with a large treasury.
    try:
        if api.t % 48 != 0 or api.res < 900:
            return
        dep = api.depots or {}
        if len(dep) >= 3:
            return
        if any((v.get("opens_in") or 0) > 0 for v in dep.values()):
            return
        border = api.border or {}
        cap = api.capital
        best, best_len = None, 0
        tried = 0
        for p in border:
            if p in dep or tried >= 15:
                break
            pr = api.provs.get(p)
            if not pr or pr.get("harsh") or not pr.get("supplied", True):
                continue
            tried += 1
            path = api.path(cap, p)
            if not path:
                continue
            L = len(path)
            if 3 <= L <= 7 and L > best_len:
                best, best_len = p, L
        if best is not None:
            api.cmd("depot P%d" % best)
    except Exception:
        pass


def _p_take(api, n, lst, nd, ours, es):
    md = api.model or {}
    if not md or not md.get("w"):
        return None
    try:
        feats = md.get("features", [])
        mean = md.get("mean", [])
        std = md.get("std", [])
        w = md.get("w", [])
        terr = str(nd.get("terrain", ""))
        tdfn = 1.0
        for k, v in TERRAIN_DFN.items():
            if k in terr:
                tdfn = v
        fort = nd.get("fort", 0) or 0
        heavy = sum(1 for u in lst if u["type"] in ("art", "eng", "arm")) / float(len(lst))
        rdy = sum(u.get("rdy", 0) for u in lst) / float(len(lst)) / 100.0
        bon = max(_bon(u) for u in lst) / 100.0
        dirs = 0
        for k in nd.get("nbrs", []):
            if api.provs.get(k, {}).get("who") == api.me_id_hint():
                dirs += 1
        vals = {
            "log_ratio": math.log((ours + 1.0) / (es + 1.0)),
            "terrain_dfn": tdfn,
            "fort": fort,
            "city": 1.0 if nd.get("city") else 0.0,
            "bonus": bon,
            "att_rdy": rdy,
            "heavy_share": heavy,
            "dirs": dirs,
        }
        s = md.get("b", 0.0)
        for i, f in enumerate(feats):
            if f in vals and i < len(w) and i < len(mean) and i < len(std):
                s += w[i] * (vals[f] - mean[i]) / (std[i] or 1.0)
        s = max(-40.0, min(40.0, s))
        return 1.0 / (1.0 + math.exp(-s))
    except Exception:
        return None


def _border_factions(api):
    out = set()
    try:
        for p in (api.border or {}):
            pr = api.provs.get(p)
            if not pr:
                continue
            for n in pr.get("nbrs", []):
                f = (api.owner_name or {}).get(n)
                if f:
                    out.add(f)
    except Exception:
        pass
    return out


def _accept_pacts(api):
    try:
        border = _border_factions(api)
        for o in (api.offers_in or []):
            if o.get("kind") != "pact":
                continue
            frm = o.get("frm")
            dated = o.get("hours") is not None
            if dated or frm not in border:
                api.cmd("accept %s" % o.get("id"))
    except Exception:
        pass


def _pacts(api):
    try:
        m = api.mem
        pt = m.setdefault("pact_try", {})
        pending = set(o.get("to") for o in (api.offers_out or []))
        for f in api.met or []:
            if f in (api.pacts or {}) or f in pending:
                continue
            if api.t < 72:
                continue
            if api.t - pt.get(f, -10**9) < 96:
                continue
            pt[f] = api.t
            api.cmd("offer %s pact" % f)
    except Exception:
        pass


def tick(api):
    m = api.mem
    me = api.me
    units = api.units or []

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)

    armour = False
    for v in (api.enemy or {}).values():
        ty = str(v.get("types", ""))
        if any(a in ty for a in ARMOURED):
            armour = True

    # 0. Refit old models out of combat, only when rich enough
    _refit(api)

    # 0b. Forward depots and a dug-in front line
    _forward_depot(api)
    _dig(api)

    # 1. Recruit (up to 3 per tick)
    try:
        if api.income > 0 or total < 20:
            for _ in range(3):
                pick = _pick(api, counts, total, armour)
                if not pick:
                    break
                r = api.cmd("recruit %s P%d" % (pick, api.capital))
                if not str(r).startswith("ok"):
                    break
                counts[pick] = counts.get(pick, 0) + 1
                total += 1
    except Exception:
        pass

    # 2. Assign idle units: scouts explore, the rest take free land while it lasts
    try:
        idle = [u for u in units
                if u.get("state") == "ready" and not u.get("path")
                and not (u.get("front") or u.get("expand") or u.get("explore"))]
        scouts = [u for u in idle if u["type"] == "rec"]
        inf = [u for u in idle if u["type"] in INF]
        heavy = [u for u in idle if u["type"] not in INF and u["type"] != "rec"]
        free_land = bool(api.neutral_border) and api.t < 600
        if scouts:
            api.cmd("explore " + _ids(scouts))
        if inf:
            api.cmd("expand " + _ids(inf))
        if heavy:
            if free_land:
                api.cmd("expand " + _ids(heavy))
            else:
                api.cmd("front " + _ids(heavy))
    except Exception:
        pass

    # 3. Attacks: only with a fitted chance to take the province
    try:
        if api.stock.get("res", 0) >= 80:
            by_prov = {}
            for u in units:
                if (u.get("state") in ("ready", "preparing") and u.get("str", 0) >= 60
                        and u.get("rdy", 0) >= 60 and not u.get("path")
                        and not u.get("expand") and not u.get("explore")
                        and u["type"] != "rec"):
                    by_prov.setdefault(u["prov"], []).append(u)
            pacts = api.pacts or {}
            owners = api.owner_name or {}
            done = False
            for p, lst in by_prov.items():
                if done:
                    break
                pr = api.provs.get(p)
                if not pr:
                    continue
                for n in pr.get("nbrs", []):
                    nd = api.provs.get(n)
                    if not nd or nd.get("who", -1) in (-1, me):
                        continue
                    if owners.get(n) in pacts:
                        continue
                    e = (api.enemy or {}).get(n)
                    if e is None:
                        continue
                    es = e.get("str", 0)
                    ours = sum(u.get("str", 0) for u in lst)
                    fort = nd.get("fort", 0) or 0
                    n_art = sum(1 for u in lst if u["type"] == "art")
                    if fort >= 4:
                        continue
                    if fort >= 2 and n_art < 2:
                        continue
                    if fort >= 3 and n_art < 3:
                        continue
                    p_take = _p_take(api, n, lst, nd, ours, es)
                    thresh = 0.45 if fort <= 1 else 0.60
                    if p_take is not None:
                        if p_take < thresh:
                            continue
                    else:
                        need = 3.0 * es + 80 if fort < 2 else 5.0 * es + 150
                        if ours < need:
                            continue
                    planned = [u for u in lst if u.get("plan") == n]
                    if planned:
                        avg = sum(_bon(u) for u in planned) / len(planned)
                        if avg >= 30:
                            api.cmd("move %s P%d" % (_ids(planned), n))
                            done = True
                            break
                        continue
                    free = [u for u in lst if u.get("plan", -1) in (-1, None)]
                    if free:
                        api.cmd("prepare %s P%d" % (_ids(free), n))
                        done = True
                        break
    except Exception:
        pass

    # 4. Research (blind; two projects at once, keep a smaller reserve)
    try:
        active = set(r[0] for r in (api.research or []))
        if len(active) < 2 and api.res > 150:
            for line in LINES:
                if len(active) >= 2:
                    break
                if line in active:
                    continue
                if "." in line and line.split(".")[0] not in counts:
                    continue
                info = (api.tech or {}).get(line)
                if not info or info.get("status") != "open":
                    continue
                c = info.get("cost") or {}
                if api.res < c.get("res", 0) + 100:
                    continue
                if any(api.stock.get(k, 0) < c.get(k, 0) for k in ("steel", "oil", "rare")):
                    continue
                api.cmd("research %s" % line)
                active.add(line)
    except Exception:
        pass

    # 5. Diplomacy: answer incoming pacts, offer ours from day 3
    _accept_pacts(api)
    _pacts(api)

    m["calls"] = m.get("calls", 0) + 1
