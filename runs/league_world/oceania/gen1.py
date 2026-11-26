W = {"inf": 0.22, "mot": 0.12, "arm": 0.14, "mec": 0.12, "art": 0.12,
     "atg": 0.08, "mtn": 0.06, "eng": 0.06, "rec": 0.02}

RESEARCH = ["mining", "drilling", "conscription", "industry", "logistics",
            "art.weapons", "arm.weapons", "drill", "medicine", "discipline",
            "mot.mobility", "inf.weapons", "inf.protection", "arm.protection",
            "farming", "fieldworks", "staffwork", "refining"]

RES_RESERVE = 120
P_GATE = 0.6


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


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


def _recruit(api, counts, total):
    budget = api.res - RES_RESERVE
    mp = api.mp
    stock = api.stock
    done = 0
    while done < 4:
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
        # fallback when no fitted model is loaded
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


def _attack(api, m, t, units, provs):
    preps = m.setdefault("prep", {})
    alive = {u["id"]: u for u in units}

    for key in list(preps.keys()):
        pr = preps[key]
        src, tgt = pr["src"], pr["tgt"]
        ids = [i for i in pr["ids"] if i in alive and alive[i]["prov"] == src]
        if not ids or t - pr["t"] > 60:
            del preps[key]
            continue
        if t - pr["t"] >= 12:
            api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgt))
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
        if (p.get("stock") or 0) < 25:
            continue
        avail = [u for u in lst if u.get("state") in ("ready", "defending")
                 and u.get("rdy", 100) >= 60 and not u.get("dry")]
        if len(avail) < 3:
            continue
        avail.sort(key=lambda u: -u["str"])
        total_str = sum(u["str"] for u in avail)
        for tgt in _nbs(p):
            tp = provs.get(tgt)
            if not tp or tp.get("owner") != "enemy":
                continue
            en = api.enemy.get(tgt)
            estr = en["str"] if en else 30.0
            if en and not en.get("exact"):
                estr *= 1.4
            fort = tp.get("fort") or 0
            climb = max(0, (tp.get("elev") or 0) - (p.get("elev") or 0))
            need = (estr * (1.6 + 0.3 * fort) + 40) * (1.0 + 0.15 * climb)
            if total_str < need * 1.2:
                continue
            want = need * 1.2
            picked = []
            acc = 0.0
            for u in avail:
                if acc >= want:
                    break
                picked.append(u)
                acc += u["str"]
            if acc < need or len(picked) >= len(avail):
                continue  # leave a garrison at home
            heavy = sum(1 for u in picked if u["type"] in ("art", "eng", "arm"))
            hs = heavy / float(len(picked))
            avg_rdy = sum(u.get("rdy", 100) for u in picked) / float(len(picked))
            p_take = _p_take(api, acc, estr, fort, _terrain_dfn(tp),
                             avg_rdy, hs, climb)
            if p_take < P_GATE:
                continue
            api.cmd("prepare %s P%d" % (_ids(picked), tgt))
            preps[str(src) + "_" + str(tgt)] = {
                "src": src, "tgt": tgt, "t": t,
                "ids": [u["id"] for u in picked]}
            busy_src.add(src)
            break


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

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1

    try:
        _recruit(api, counts, len(units))
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
                and not u.get("explore") and u.get("state") == "ready"]
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
        _research(api)
    except Exception:
        pass


def tick(api):
    try:
        _tick(api)
    except Exception:
        pass
