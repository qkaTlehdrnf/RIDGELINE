**Review:** The policy holds 3rd to 5th place in every war, with 234 to 242 provinces. The weak spot is assaults: 0 of 16 succeeded, and 0 of 8 of my provinces fell to attack. Every failure came with readiness under 34, so units were launching while worn down. The launch step also never rechecked the target, readiness, or the enemy estimate after the 12-hour wait. I'm keeping the economy, research order, diplomacy, and refit logic. I'm changing the attack pipeline: a 24-hour prep wait, a relaunch check (enemy still there, exact count, readiness at least 60, else hold), a stricter strength margin, and a tighter fort cap. I'm also adding a small late-game push to recruit when neutral land remains. Expect modest gains; the attack changes are untested.

```python
W = {"inf": 0.14, "mot": 0.10, "arm": 0.20, "mec": 0.10, "art": 0.20,
     "atg": 0.08, "mtn": 0.06, "eng": 0.06, "rec": 0.02}

RESEARCH = ["art.weapons", "arm.weapons", "mining", "drilling", "logistics",
            "industry", "conscription", "drill", "medicine", "discipline",
            "fieldworks", "staffwork", "farming", "refining",
            "mot.mobility", "inf.weapons", "inf.protection", "arm.protection"]

RES_RESERVE = 150
P_GATE = 0.80
NEED_MULT = 4.0
MIN_ATTACKERS = 10
MAX_ATTACK_FORT = 1
PREP_WAIT = 24
LAUNCH_MIN_RDY = 60
MIN_READY = 80
REFIT_RES_FLOOR = 900
PACT_EVERY = 96


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
    # late-game push: more units while neutral land still exists
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
    # re-check at launch: target still enemy, seen exactly, our units fresh enough
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
    return total >= need * 2.5


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
                api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tgt))
            else:
                api.cmd("hold %s" % ",".join(str(i) for i in ids))
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
                continue  # never attack blind
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


def _refit(api, units):
    if api.res < REFIT_RES_FLOOR:
        return
    border = api.border
    cands = [u for u in units if u.get("old") and u.get("state") == "ready"
             and u.get("supplied") and u["prov"] not in border]
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
        if len(pick) >= 12:
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
        _refit(api, units)
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
```

```letters
to nusantara: Oceania keeps the pact and will renew it. We take neutral land only and will not cross your seas uninvited; if you respect the same line, the sea lane stays quiet.
```