MIX = {"inf": 0.45, "atg": 0.12, "art": 0.10, "mtn": 0.08,
       "eng": 0.05, "arm": 0.05, "mot": 0.05, "cav": 0.05}
PREF_RES = ["farming", "inf.protection", "inf.weapons", "conscription",
            "medicine", "discipline", "drill", "atg.weapons", "art.weapons",
            "fieldworks", "logistics", "inf.mobility", "industry",
            "mining", "drilling", "refining", "staffwork"]
EXPAND_TYPES = ("inf", "mil", "mtn", "mot", "cav")
CORE_TYPES = ("inf", "mtn", "mil", "atg")


def _afford(api, t):
    uc = api.unit_costs.get(t)
    if not uc:
        return False
    if api.res < uc.get("res", 0) + 40:
        return False
    if api.mp < uc.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) < uc.get(k, 0):
            return False
    return True


def tick(api):
    m = api.mem
    m["n"] = m.get("n", 0) + 1
    n = m["n"]
    units = api.units

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)

    # 1. Recruit: two scouts, then fill the mix by deficit (max 2 per tick).
    try:
        if counts.get("rec", 0) < 2 and "rec" in api.unit_costs and _afford(api, "rec"):
            r = api.cmd("recruit rec P%d" % api.capital)
            if r.startswith("ok"):
                counts["rec"] = counts.get("rec", 0) + 1
                total += 1
        for _ in range(2):
            pick = None
            best = -1e9
            tot = total + 1
            for t, w in MIX.items():
                if t not in api.unit_costs or not _afford(api, t):
                    continue
                d = w * tot - counts.get(t, 0)
                if d > best:
                    best = d
                    pick = t
            if pick is None:
                break
            r = api.cmd("recruit %s P%d" % (pick, api.capital))
            if not r.startswith("ok"):
                break
            counts[pick] = counts.get(pick, 0) + 1
            total += 1
    except Exception:
        pass

    # 2. Research: one new project per tick if affordable and a slot is free.
    try:
        if len(api.research) < 2:
            busy = set(r[0] for r in api.research)
            for line in PREF_RES:
                if line in busy:
                    continue
                t = api.tech.get(line)
                if not t or t.get("status") != "open":
                    continue
                cost = t.get("cost") or {}
                ok = api.res >= cost.get("res", 0) + 60
                for k, v in cost.items():
                    if k != "res" and api.stock.get(k, 0) < v:
                        ok = False
                if ok:
                    api.cmd("research %s" % line)
                    break
    except Exception:
        pass

    # 3. Scouting and land grabs.
    used = set()
    try:
        if api.unexplored:
            explorers = [u for u in units if u["type"] == "rec" and u["state"] == "ready"
                         and not u["path"] and not u["explore"]]
            if explorers:
                ids = [str(u["id"]) for u in explorers[:2]]
                api.cmd("explore " + ",".join(ids))
                used.update(u["id"] for u in explorers[:2])
    except Exception:
        pass

    idle = [u for u in units if u["state"] == "ready" and not u["path"]
            and not u["front"] and not u["expand"] and not u["explore"]
            and u["type"] != "rec" and u["id"] not in used]

    try:
        expanders = sum(1 for u in units if u["expand"])
        if api.neutral_border and expanders < 4:
            pick = [u for u in idle if u["type"] in EXPAND_TYPES][:2]
            for u in pick:
                r = api.cmd("expand %d" % u["id"])
                if r.startswith("ok"):
                    used.add(u["id"])
    except Exception:
        pass

    # 4. Everything else idle goes on the front, batched.
    try:
        rest = [str(u["id"]) for u in idle if u["id"] not in used]
        if rest:
            api.cmd("front " + ",".join(rest))
    except Exception:
        pass

    # 5. Core front units join one formation, to build formation experience.
    try:
        if n % 12 == 0:
            new = [str(u["id"]) for u in units if u["front"] and not u["group"]
                   and u["type"] in CORE_TYPES]
            if new:
                if not m.get("grp"):
                    api.cmd("group line " + ",".join(new))
                    m["grp"] = True
                else:
                    api.cmd("group line + " + ",".join(new))
    except Exception:
        pass

    m["calls"] = n
