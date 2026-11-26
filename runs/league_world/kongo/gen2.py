W_EARLY = {"inf": 0.40, "mil": 0.10, "mtn": 0.10, "mot": 0.10, "eng": 0.08, "rec": 0.02}
W_LATE = {"inf": 0.16, "mtn": 0.06, "mot": 0.07, "mec": 0.07, "arm": 0.18,
          "hvt": 0.08, "art": 0.14, "grn": 0.07, "atg": 0.05, "eng": 0.04,
          "rkt": 0.05, "cav": 0.01, "mil": 0.01}
RESEARCH = ["mining", "logistics", "industry", "conscription", "arm.weapons",
            "farming", "inf.protection", "mot.mobility", "arm.protection",
            "art.weapons", "refining", "drilling", "staffwork", "inf.weapons",
            "hvt.weapons", "mec.protection", "fieldworks", "medicine", "drill",
            "discipline", "grn.weapons", "atg.weapons"]
TDEF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
EXCLUDE_ATTACK = ("rec", "eng")
MIN_RATIO = 1.8
MIN_PROB = 0.6


def _nbs(pr):
    out = []
    for x in pr.get("nbrs", []) or []:
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, dict):
            if isinstance(x.get("id"), int):
                out.append(x["id"])
        else:
            digits = "".join(c for c in str(x) if c.isdigit())
            if digits:
                out.append(int(digits))
    return out


def _csv(ids):
    return ",".join(str(i) for i in ids)


def _fits(api, t, res_left, mp_left, stock, keep):
    c = api.unit_costs.get(t)
    if not c:
        return False
    if res_left - c.get("res", 0) < keep:
        return False
    if mp_left < c.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if stock.get(k, 0) < c.get(k, 0):
            return False
    return True


def _recruit_city(api):
    best = None
    for p, pr in api.provs.items():
        if pr.get("owner") == "me" and pr.get("city") and p in api.border:
            best = p
            break
    return best if best is not None else api.capital


def _recruit(api):
    if api.income < -10 and api.res < 400:
        return
    weights = W_EARLY if api.t < 96 else W_LATE
    mp_keep = 0 if api.t < 72 else 60
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    res_left = api.res
    mp_left = api.mp
    stock = dict(api.stock)
    keep = 80 + 1.0 * len(api.units)
    city = _recruit_city(api)
    for _ in range(12):
        best = None
        bv = 1e18
        for t, w in weights.items():
            if t == "rec" and counts.get("rec", 0) >= 2:
                continue
            if not _fits(api, t, res_left, mp_left - mp_keep, stock, keep):
                continue
            v = (counts.get(t, 0) + 1) / w
            if v < bv:
                bv = v
                best = t
        if best is None:
            break
        r = api.cmd("recruit %s P%d" % (best, city))
        if not str(r).startswith("ok"):
            break
        c = api.unit_costs[best]
        res_left -= c.get("res", 0)
        mp_left -= c.get("mp", 0)
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - c.get(k, 0)
        counts[best] = counts.get(best, 0) + 1


def _research(api):
    if len(api.research) >= 2 or api.res < 200:
        return
    busy = set(r[0] for r in api.research)
    names = [n for n in RESEARCH if n in api.tech]
    names += sorted(n for n in api.tech if n not in names)
    for line in names:
        if len(api.research) + 1 >= 3:
            return
        if line in busy:
            continue
        st = api.tech.get(line)
        if not st or st.get("status") in ("dead end", "complete", "researching"):
            continue
        cost = st.get("cost") or {}
        good = True
        for k, v in cost.items():
            if k == "res":
                if api.res - v < 120:
                    good = False
            elif api.stock.get(k, 0) < v:
                good = False
        if good:
            api.cmd("research %s" % line)
            return


def _orders(api):
    n = 0
    for u in api.units:
        if n >= 40:
            break
        if u.get("path") or u.get("plan", -1) != -1:
            continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("fighting"):
            continue
        if u.get("state") not in ("ready", "digging", "refitting"):
            continue
        if u["type"] == "rec":
            api.cmd("explore %d" % u["id"])
        else:
            api.cmd("expand %d" % u["id"])
        n += 1


def _refit(api):
    if api.old_units <= 0 or api.res < 300:
        return
    st = dict(api.stock)
    ids = []
    for u in api.units:
        if len(ids) >= 20:
            break
        if not u.get("old") or u.get("fighting") or u.get("path"):
            continue
        if u.get("state") != "ready" or not u.get("supplied"):
            continue
        if u["prov"] in api.border:
            continue
        rc = api.refit_cost.get(u["type"]) or {}
        ok = True
        for k in ("res", "steel", "oil", "rare"):
            if st.get(k, 0) - rc.get(k, 0) < (250 if k == "res" else 0):
                ok = False
        if not ok:
            continue
        for k in ("res", "steel", "oil", "rare"):
            st[k] = st.get(k, 0) - rc.get(k, 0)
        ids.append(u["id"])
    if ids:
        api.cmd("refit %s" % _csv(ids))


def _p_take(api, S, D, fort, tdef, rdy, hs, city):
    mdl = api.model or {}
    lr = math.log((S + 1.0) / (D + 1.0))
    if not mdl or "w" not in mdl:
        z = lr * 1.5 - 0.3
    else:
        vals = {"log_ratio": lr, "terrain_dfn": tdef, "fort": fort,
                "city": city, "bonus": 0.0, "att_rdy": rdy / 100.0,
                "heavy_share": hs, "dirs": 1.0}
        z = mdl["b"]
        for i, f in enumerate(mdl["features"]):
            z += mdl["w"][i] * (vals.get(f, 0.0) - mdl["mean"][i]) / mdl["std"][i]
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _attack(api):
    prep = api.mem.setdefault("prep", {})
    alive = set(u["id"] for u in api.units)
    for k in list(prep.keys()):
        w = prep[k]
        ids = [i for i in w["ids"] if i in alive]
        if not ids or api.t - w["t0"] > 60:
            del prep[k]
            continue
        w["ids"] = ids
        if api.t - w["t0"] >= 8:
            api.cmd("move %s P%d" % (_csv(ids), w["tgt"]))
            del prep[k]
    if len(prep) >= 3 or api.res < 100:
        return

    busy = set()
    for w in prep.values():
        busy |= set(w["ids"])

    by_prov = {}
    for u in api.units:
        by_prov.setdefault(u["prov"], []).append(u)

    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    adj = {}
    for p in mine:
        for nb in _nbs(api.provs[p]):
            if nb in mine:
                continue
            pr2 = api.provs.get(nb)
            if pr2 and pr2.get("owner") == "enemy":
                adj.setdefault(nb, []).append(p)

    best = None
    bkey = None
    for nb, ps in adj.items():
        cand = []
        for p in ps:
            for u in by_prov.get(p, []):
                if u["id"] in busy or u["type"] in EXCLUDE_ATTACK:
                    continue
                if u.get("path") or u.get("plan", -1) != -1:
                    continue
                if u.get("state") not in ("ready", "defending", "digging", "refitting"):
                    continue
                cand.append(u)
        if not cand:
            continue
        S = sum(u.get("str", 0) * (0.4 + 0.6 * u.get("rdy", 50) / 100.0) for u in cand)
        rdy = sum(u.get("rdy", 50) for u in cand) / len(cand)
        hs = sum(1 for u in cand if u["type"] in ("arm", "art", "eng", "hvt", "rkt")) / float(len(cand))
        pr2 = api.provs[nb]
        e = (api.enemy.get(nb, {}) or {}).get("str", 0) or 60.0
        fort = pr2.get("fort") or 0
        tdef = TDEF.get(pr2.get("terrain"), 1.0)
        city = 1 if pr2.get("city") else 0
        D = e * tdef * (1.25 ** fort)
        if S < MIN_RATIO * D:
            continue
        prob = _p_take(api, S, D, fort, tdef, rdy, hs, city)
        if prob < MIN_PROB:
            continue
        key = (prob, S)
        if bkey is None or key > bkey:
            bkey = key
            best = (nb, cand)

    if best:
        nb, cand = best
        cand = cand[:40]
        ids = [u["id"] for u in cand]
        k = api.mem.get("wave_n", 0) + 1
        api.mem["wave_n"] = k
        api.cmd("group w%d %s" % (k, _csv(ids)))
        api.cmd("hold %s" % _csv(ids))
        api.cmd("prepare %s P%d" % (_csv(ids), nb))
        prep[k] = {"tgt": nb, "t0": api.t, "ids": ids}


def _engineers(api):
    n = 0
    for u in api.units:
        if n >= 10:
            break
        if u["type"] != "eng" or u.get("path") or u.get("fighting") or u.get("state") == "digging":
            continue
        p = u["prov"]
        if p in api.border and (api.provs.get(p, {}).get("fort") or 0) < 3:
            api.cmd("fortify %d" % u["id"])
            n += 1


def _diplomacy(api):
    for o in list(api.offers_in or []):
        oid = o.get("id")
        if o.get("kind") == "pact":
            api.cmd("accept %s" % oid)
            continue
        gy = o.get("you_give", {}) or {}
        if set(gy.keys()) <= {"res"} and gy.get("res", 0) <= 0.3 * api.res:
            api.cmd("accept %s" % oid)
        else:
            api.cmd("reject %s" % oid)
    sent = api.mem.setdefault("sent", {})
    pending = set(o.get("to") for o in (api.offers_out or []))
    for f in api.met:
        if f in api.pacts or f in pending:
            continue
        if api.t - sent.get(f + "_pact", -9999) < 120:
            continue
        api.cmd("offer %s pact" % f)
        sent[f + "_pact"] = api.t
        if api.t - sent.get(f + "_say", -9999) >= 240:
            api.cmd("say %s Kongo proposes peace: keep fire off each other, we seek no war with you." % f)
            sent[f + "_say"] = api.t


def tick(api):
    for f in (_diplomacy, _research, _recruit, _orders, _attack, _engineers, _refit):
        try:
            f(api)
        except Exception:
            pass
