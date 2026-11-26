RESEARCH_ORDER = [
    "farming", "conscription", "logistics", "inf.weapons", "inf.protection",
    "arm.weapons", "mining", "medicine", "drill", "discipline", "fieldworks",
    "arm.protection", "art.weapons", "mobility",
]

MIX = [
    ("inf", 0.42), ("mtn", 0.08), ("art", 0.12), ("arm", 0.10),
    ("atg", 0.10), ("eng", 0.06), ("mot", 0.07), ("rec", 0.02),
]


def _research(api, m):
    active = [r[0] for r in api.research]
    if len(active) >= 2:
        return
    st = api.stock
    for line in RESEARCH_ORDER:
        info = api.tech.get(line)
        if not info or info.get("status") != "open" or line in active:
            continue
        cost = info.get("cost") or {}
        ok = True
        for k, v in cost.items():
            if st.get(k, 0) < v + 40:
                ok = False
                break
        if ok:
            api.cmd("research " + line)
            return


def _recruit(api, m):
    if api.mp < 60 or api.res < 120 or api.income < 3:
        return
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    res = api.res
    mp = api.mp
    stock = dict(api.stock)
    for _ in range(3):
        total = len(api.units) + 1
        best = None
        bd = -1e9
        for typ, share in MIX:
            if typ not in api.costs:
                continue
            rc, mc = api.costs[typ]
            if rc > res - 40 or mc > mp:
                continue
            uc = api.unit_costs.get(typ, {})
            if (uc.get("steel", 0) > stock.get("steel", 0)
                    or uc.get("oil", 0) > stock.get("oil", 0)
                    or uc.get("rare", 0) > stock.get("rare", 0)):
                continue
            d = share * total - counts.get(typ, 0)
            if d > bd:
                bd = d
                best = typ
        if best is None:
            return
        r = api.cmd("recruit %s 1 P%d" % (best, api.capital))
        if not r.startswith("ok"):
            return
        rc, mc = api.costs[best]
        res -= rc
        mp -= mc
        uc = api.unit_costs.get(best, {})
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - uc.get(k, 0)
        counts[best] = counts.get(best, 0) + 1


def _ids(us):
    return ",".join(str(u["id"]) for u in us)


def _assign(api, m):
    idle = [
        u for u in api.units
        if not u["path"] and not u["front"] and not u["expand"]
        and not u["explore"] and not u["fighting"] and u["state"] == "ready"
    ]
    if not idle:
        return
    scouts = [u for u in idle if u["type"] == "rec"]
    rest = [u for u in idle if u["type"] != "rec"]
    if scouts:
        api.cmd("explore " + _ids(scouts))
    if not rest:
        return
    if api.neutral_border:
        half = rest[: max(1, len(rest) // 2)]
        api.cmd("expand " + _ids(half))
        rest = rest[len(half):]
    if rest:
        ids = _ids(rest)
        api.cmd("front " + ids)
        if m.get("line_init"):
            api.cmd("group line + " + ids)
        else:
            if api.cmd("group line " + ids).startswith("ok"):
                m["line_init"] = True


def _attack(api, m):
    prep = m.setdefault("prep", {})
    t = api.t
    by_prov = {}
    for u in api.units:
        if u["path"] or u["type"] == "rec":
            continue
        by_prov.setdefault(u["prov"], []).append(u)
    for pid, start in list(prep.items()):
        tgt, t0 = start
        if pid not in by_prov or api.provs.get(tgt, {}).get("owner") != "enemy":
            del prep[pid]
            continue
        if t - t0 >= 6:
            api.cmd("move @P%d P%d" % (pid, tgt))
            del prep[pid]
    for pid, us in by_prov.items():
        if pid in prep:
            continue
        pr = api.provs.get(pid)
        if not pr:
            continue
        ours = sum(u["str"] for u in us)
        rdy = sum(u["rdy"] for u in us) / len(us)
        if ours < 150 or rdy < 60:
            continue
        for nb in pr["nbrs"]:
            e = api.enemy.get(nb)
            if not e:
                continue
            if ours > 1.6 * e["str"]:
                api.cmd("prepare @P%d P%d" % (pid, nb))
                prep[pid] = (nb, t)
                break


def tick(api):
    m = api.mem
    for f in (_research, _recruit, _attack, _assign):
        try:
            f(api, m)
        except Exception:
            pass
