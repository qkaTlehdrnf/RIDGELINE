**Reasoning:** Oceania is a cheap-unit, fast faction with weaker defence, so the policy favours mass and tempo over static holding. It keeps recruitment balanced by a weighted deficit across unit types and respects resource reserves. Two scouts explore continuously. Idle units go to `expand` while neutral land is reachable and otherwise to `front` along the border. Attacks happen only when visible enemy strength is clearly outmatched, with an estimate margin for unseen units and extra requirements for fortified or uphill targets. Attackers are prepared for about 12 hours to build the bonus, and a garrison is always left behind. Research picks the first open line on a priority list that the stockpiles can afford, keeping a 60-resource reserve and at most two projects. Each section is wrapped so one failure does not stop the others.

```python
W = {"inf": 0.30, "mtn": 0.08, "mot": 0.10, "art": 0.10, "atg": 0.07,
     "eng": 0.04, "arm": 0.10, "mec": 0.08, "cav": 0.03, "rec": 0.03}

RESEARCH = ["farming", "mining", "drilling", "conscription", "industry",
            "inf.weapons", "inf.protection", "art.weapons", "arm.weapons",
            "mot.mobility", "arm.protection", "drill", "logistics",
            "medicine", "fieldworks", "discipline", "staffwork", "refining"]

RES_RESERVE = 60


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
    while done < 2:
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


def _attack(api, m, t, units, provs):
    preps = m.setdefault("prep", {})
    alive = {u["id"]: u for u in units}

    # launch pending preparations once the bonus has built up
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
                 and u.get("rdy", 100) >= 55 and not u.get("dry")]
        if len(avail) < 2:
            continue
        avail.sort(key=lambda u: -u["str"])
        total_str = sum(u["str"] for u in avail)
        for tgt in _nbs(p):
            tp = provs.get(tgt)
            if not tp or tp.get("owner") != "enemy":
                continue
            en = api.enemy.get(tgt)
            estr = en["str"] if en else 0.0
            if en and not en.get("exact"):
                estr *= 1.4
            fort = tp.get("fort") or 0
            climb = max(0, (tp.get("elev") or 0) - (p.get("elev") or 0))
            need = (estr * (1.8 + 0.3 * fort) + 40) * (1.0 + 0.15 * climb)
            if total_str < need:
                continue
            want = need * 1.15
            picked = []
            acc = 0
            for u in avail:
                if acc >= want:
                    break
                picked.append(u)
                acc += u["str"]
            if acc < need or len(picked) >= len(avail):
                continue  # leave a garrison at home
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
```