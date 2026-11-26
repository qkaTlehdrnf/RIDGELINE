def _sig(x):
    if x < -30: return 0.0
    if x > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-x))

def _pwin(api, att, dfn, prov, rdy, heavy, bonus):
    md = api.model or {}
    w = md.get("w"); mean = md.get("mean"); std = md.get("std")
    tdm = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
    x = [math.log((att + 1.0) / (dfn + 1.0)), tdm.get(prov.get("terrain"), 1.0),
         prov.get("fort", 0) or 0, 1.0 if prov.get("city") else 0.0, bonus, rdy, heavy, 1.0]
    if not w or not mean or not std:
        return _sig(1.2 * x[0] - 0.4 * x[2] - 0.5)
    s = md.get("b", 0.0)
    for i in range(min(len(w), len(x))):
        sd = std[i] if std[i] else 1.0
        s += w[i] * (x[i] - mean[i]) / sd
    return _sig(s)

def tick(api):
    m = api.mem
    t = api.t
    if "init" not in m:
        m["init"] = 1; m["strike"] = []; m["st"] = None; m["exp_t"] = {}; m["rec_s"] = None
    provs = api.provs
    units = api.units
    byid = {}
    for u in units: byid[u["id"]] = u
    contact = bool(api.enemy) or any(p.get("owner") == "enemy" for p in provs.values())
    # ---- recruiting ----
    costs = api.costs
    upk = {"inf": .3, "mil": .1, "mtn": .35, "mot": .45, "arm": .6, "art": .45, "eng": .3, "rec": .15}
    cnt = {}
    for u in units: cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    terr = {}
    for p in provs.values():
        if p.get("owner") == "me": terr[p.get("terrain")] = terr.get(p.get("terrain"), 0) + 1
    tot = sum(terr.values()) or 1
    rough = (terr.get("hill", 0) + terr.get("mountain", 0)) / float(tot)
    plain = terr.get("plain", 0) / float(tot)
    res = api.res; mp = api.mp; inc = api.income
    spent_upk = 0.0
    for k in range(12):
        n = len(units) + k
        if cnt.get("rec", 0) < (3 if t < 600 else 2):
            ty = "rec"
        elif not contact:
            ty = "inf"
        else:
            combat = max(1, n)
            if cnt.get("art", 0) < 0.15 * combat: ty = "art"
            elif rough > 0.3 and cnt.get("mtn", 0) < 0.15 * combat: ty = "mtn"
            elif plain > 0.5 and cnt.get("arm", 0) < 0.1 * combat and t > 300: ty = "arm"
            elif cnt.get("eng", 0) < 3 and t > 400: ty = "eng"
            elif cnt.get("mil", 0) < 0.25 * combat: ty = "mil"
            else: ty = "inf"
        c = costs.get(ty)
        if not c: break
        reserve = (20 if contact else 5) + 0.05 * max(0, inc)
        if res - c[0] < reserve or mp < c[1] + 10: break
        if inc - spent_upk - upk.get(ty, .3) < max(1.0, 0.08 * inc) and t > 48: break
        r = api.cmd("recruit %s" % ty)
        if not r.startswith("ok"): break
        res -= c[0]; mp -= c[1]; spent_upk += upk.get(ty, .3)
        cnt[ty] = cnt.get(ty, 0) + 1
    # ---- strike state (needed for scouts) ----
    st = m["st"]
    # ---- scouts ----
    et = m["exp_t"]
    rs = m.get("rec_s")
    if rs is not None and rs not in byid: rs = None
    for u in units:
        if u["type"] == "rec" and not u["path"]:
            if u["id"] == rs:
                continue
            if t - et.get(u["id"], -99) >= 12:
                et[u["id"]] = t
                if api.unexplored: api.cmd("explore %d" % u["id"])
                elif st and st.get("s") is not None and rs is None:
                    rs = u["id"]; api.cmd("move %d P%d" % (u["id"], st["s"]))
                else: api.cmd("front %d" % u["id"])
    m["rec_s"] = rs
    # ---- strike group maintenance ----
    strike = [i for i in m["strike"] if i in byid]
    for i in list(strike):
        if byid[i]["str"] < 35:
            strike.remove(i); api.cmd("front %d" % i)
    m["strike"] = strike
    sset = set(strike)
    combat_units = [u for u in units if u["type"] != "rec"]
    want_strike = int(0.35 * len(combat_units)) if contact else 0
    expanders = sum(1 for u in units if u.get("expand"))
    exp_cap = max(14, int(0.35 * len(combat_units)))
    neutral_ok = bool(api.neutral_border)
    for u in combat_units:
        if u["id"] in sset or u["front"] or u["path"]: continue
        if u["str"] < 60:
            api.cmd("front %d" % u["id"]); continue
        if neutral_ok and u["type"] in ("inf", "mot", "mtn", "mil") and expanders < exp_cap:
            api.cmd("expand %d" % u["id"]); expanders += 1; continue
        if contact and len(strike) < want_strike and u["type"] in ("inf", "art", "arm", "mot", "mtn", "eng"):
            strike.append(u["id"]); sset.add(u["id"])
            if st and st.get("s") is not None and st.get("ph") in ("gather", "prep"):
                api.cmd("move %d P%d" % (u["id"], st["s"]))
            continue
        api.cmd("front %d" % u["id"])
    if contact and len(strike) < want_strike // 2 and (st is None):
        for u in combat_units:
            if len(strike) >= want_strike // 2: break
            if u["id"] in sset or u.get("expand"): continue
            if u["type"] in ("inf", "art", "arm", "mtn", "mot") and u["str"] >= 80 and not u["fighting"]:
                strike.append(u["id"]); sset.add(u["id"])
    m["strike"] = strike
    if not strike:
        m["st"] = None; return
    sel = ",".join(str(i) for i in strike)
    su = [byid[i] for i in strike]
    satt = sum(u["str"] for u in su)
    srdy = sum(u["rdy"] for u in su) / (100.0 * len(su))
    sstr = satt / float(len(su))
    heavy = sum(1 for u in su if u["type"] in ("art", "eng", "arm")) / float(len(su))
    # ---- capital alarm ----
    cap = api.capital
    capp = provs.get(cap)
    if capp:
        threat = 0
        for nb in capp.get("nbrs", []) + [cap]:
            e = api.enemy.get(nb)
            if e: threat += e.get("str", 0)
        if threat > 150:
            if not st or st.get("ph") != "defend":
                api.cmd("move %s P%d" % (sel, cap))
                m["st"] = {"ph": "defend", "since": t}
            return
        if st and st.get("ph") == "defend":
            if t - st["since"] > 12:
                api.cmd("hold %s" % sel)
                m["st"] = {"ph": "rest", "since": t}
            return
    st = m["st"]
    if st and st.get("ph") == "rest":
        if (srdy >= 0.7 and sstr >= 75) or t - st["since"] > 72:
            m["st"] = None; st = None
        else:
            return
    if st and st.get("t") is not None:
        tp = provs.get(st["t"], {})
        if tp.get("owner") == "me":
            api.cmd("hold %s" % sel)
            m["st"] = {"ph": "rest", "since": t}
            return
    if st is None:
        if not contact or len(strike) < 6: return
        best = None; bs = -1.0
        ecap = set((api.enemy_capitals or {}).values())
        if api.enemy_capital is not None: ecap.add(api.enemy_capital)
        for b in api.border:
            bp = provs.get(b)
            if not bp or bp.get("owner") != "me": continue
            for nb in bp.get("nbrs", []):
                np_ = provs.get(nb)
                if not np_ or np_.get("owner") != "enemy": continue
                e = api.enemy.get(nb)
                if e: dfn = e.get("str", 0) * (1.0 if e.get("exact") else 1.3)
                else: dfn = 150 if np_.get("visible") else 220
                if (satt + 1.0) / (dfn + 1.0) < 2.5: continue
                p = _pwin(api, satt, dfn, np_, 0.75, heavy, 0.45)
                if p < 0.6: continue
                sc = p * (1.0 + (np_.get("y", 0) or 0) * 0.3)
                if nb in ecap: sc *= 4.0
                sc *= 1.0 + 0.002 * (bp.get("stock", 0) or 0)
                if bp.get("supplied"): sc *= 1.3
                else: sc *= 0.5
                if sc > bs: bs = sc; best = (nb, b)
        if best is None: return
        api.cmd("move %s P%d" % (sel, best[1]))
        m["st"] = {"t": best[0], "s": best[1], "ph": "gather", "since": t}
        return
    ph = st["ph"]; tgt = st["t"]; stg = st["s"]
    if provs.get(stg, {}).get("owner") != "me" and ph != "go":
        api.cmd("move %s P%d" % (sel, cap))
        m["st"] = {"ph": "rest", "since": t}; return
    if ph == "gather":
        there = sum(1 for u in su if u["prov"] == stg and not u["path"])
        if there >= 0.75 * len(su) or t - st["since"] > 60:
            ids = ",".join(str(u["id"]) for u in su if u["prov"] == stg)
            if ids:
                api.cmd("prepare %s P%d" % (ids, tgt))
                st["ph"] = "prep"; st["since"] = t
    elif ph == "prep":
        late = [u for u in su if u["prov"] == stg and u["plan"] != tgt and not u["path"]]
        if late:
            api.cmd("prepare %s P%d" % (",".join(str(u["id"]) for u in late), tgt))
        bon = [u.get("bonus", 0) or 0 for u in su if u["plan"] == tgt]
        avgb = (sum(bon) / float(len(bon))) if bon else 0
        e = api.enemy.get(tgt)
        dfn = e.get("str", 0) if e else 150
        ready = [u for u in su if u["plan"] == tgt]
        ratt = sum(u["str"] for u in ready) or 1
        p = _pwin(api, ratt, dfn, provs.get(tgt, {}), srdy, heavy, avgb / 100.0)
        waited = t - st["since"]
        if (avgb >= 40 and srdy >= 0.6) or waited >= 60:
            if p < 0.55:
                if waited > 96:
                    api.cmd("hold %s" % sel)
                    m["st"] = {"ph": "rest", "since": t}
                return
            ids = ",".join(str(u["id"]) for u in ready)
            if not ids: return
            api.cmd("move %s P%d" % (ids, tgt))
            st["ph"] = "go"; st["since"] = t
    elif ph == "go":
        if sstr < 40 or t - st["since"] > 48 or srdy < 0.15:
            back = stg if provs.get(stg, {}).get("owner") == "me" else cap
            api.cmd("move %s P%d" % (sel, back))
            m["st"] = {"ph": "rest", "since": t}
