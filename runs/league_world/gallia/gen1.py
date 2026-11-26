def tick(api):
    for part in (_economy, _recruit, _scouts, _research, _assign, _attack):
        try:
            part(api)
        except Exception:
            pass


WEIGHTS = {
    "inf": 0.26, "mtn": 0.08, "eng": 0.05, "art": 0.14, "atg": 0.10,
    "arm": 0.12, "mec": 0.10, "grn": 0.07, "cav": 0.04, "mot": 0.04,
}
RESEARCH_ORDER = [
    "farming", "conscription", "medicine", "mining", "drilling", "logistics",
    "inf.weapons", "atg.weapons", "inf.protection", "arm.weapons",
    "arm.protection", "art.weapons", "mec.protection", "drill",
    "discipline", "industry", "fieldworks", "staffwork", "refining",
    "mot.mobility", "mtn.protection",
]


def _economy(api):
    # Keep the army within what the economy can carry (upkeep).
    api.mem["net_res"] = api.income_by.get("res", 0)


def _counts(api):
    c = {}
    for u in api.units:
        c[u["type"]] = c.get(u["type"], 0) + 1
    return c


def _afford(api, c, reserve=0):
    if not c:
        return False
    st = api.stock
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0):
            return False
    if st.get("res", 0) < c.get("res", 0) + reserve:
        return False
    return api.mp >= c.get("mp", 0)


def _recruit(api):
    if api.t % 3 != 0 or api.income_by.get("res", 0) < 10:
        return
    counts = _counts(api)
    total = len(api.units)
    ranked = []
    for typ, w in WEIGHTS.items():
        if typ == "mot" and api.t < 48:
            continue
        deficit = w * (total + 1) - counts.get(typ, 0)
        ranked.append((deficit, typ))
    ranked.sort(reverse=True)
    for _, typ in ranked:
        if _afford(api, api.unit_costs.get(typ), reserve=60):
            r = api.cmd("recruit %s P%d" % (typ, api.capital))
            if r.startswith("ok"):
                break


def _scouts(api):
    if api.t % 12 != 0 or not api.unexplored:
        return
    if _counts(api).get("rec", 0) >= 2:
        return
    if _afford(api, api.unit_costs.get("rec"), reserve=20):
        api.cmd("recruit rec P%d" % api.capital)


def _research(api):
    if api.t % 12 != 0 or len(api.research) >= 2:
        return
    counts = _counts(api)
    for line in RESEARCH_ORDER:
        info = api.tech.get(line)
        if not info or info.get("status") != "open":
            continue
        prefix = line.split(".")[0]
        if "." in line and prefix not in counts:
            continue
        if _afford(api, info.get("cost"), reserve=150):
            r = api.cmd("research %s" % line)
            if r.startswith("ok"):
                break


def _pools(api, held):
    pools = {}
    for u in api.units:
        if u["id"] in held or u["path"] or u["type"] == "rec":
            continue
        if u["state"] not in ("ready", "refitting"):
            continue
        if u["str"] < 60 or u["rdy"] < 50 or u["dry"]:
            continue
        pools.setdefault(u["prov"], []).append(u)
    return pools


def _assign(api):
    plan = api.mem.get("plan") or {}
    held = set(plan.get("ids", []))
    scouts, combat = [], []
    for u in api.units:
        if u["id"] in held or u["path"] or u["front"] or u["expand"] or u["explore"]:
            continue
        if u["state"] not in ("ready", "refitting"):
            continue
        (scouts if u["type"] == "rec" else combat).append(u["id"])
    if scouts and api.unexplored:
        api.cmd("explore %s" % ",".join(str(i) for i in scouts))
    for i in range(0, len(combat), 6):
        sel = ",".join(str(x) for x in combat[i:i + 6])
        if api.neutral_border:
            api.cmd("expand %s" % sel)
        else:
            api.cmd("front %s" % sel)


def _attack(api):
    t = api.t
    plan = api.mem.get("plan")

    # Continue an existing plan: wait for the bonus, then launch.
    if plan:
        alive = [u for u in api.units if u["id"] in plan["ids"]]
        tgt = plan["tgt"]
        pr = api.provs.get(tgt, {})
        if not alive or t - plan["t0"] > 30 or pr.get("owner") == "me":
            api.mem["plan"] = None
            return
        if t - plan["t0"] >= 10 and not plan.get("go"):
            avg_rdy = sum(u["rdy"] for u in alive) / len(alive)
            if avg_rdy >= 50:
                ids = ",".join(str(u["id"]) for u in alive)
                api.cmd("move %s P%d" % (ids, tgt))
                plan["go"] = True
                api.mem["plan"] = None
        return

    # Look for a new target every 6 hours, only if the economy can pay.
    if t % 6 != 0 or api.stock.get("res", 0) < 40:
        return

    pools = _pools(api, set())
    best = None
    for pid, pr in api.provs.items():
        if pr.get("owner") != "enemy":
            continue
        e = api.enemy.get(pid)
        if not e:
            continue
        es = e.get("str", 0)
        fort = pr.get("fort") or 0
        if fort >= 3:
            continue
        need = (2.5, 3.5, 5.0)[fort]
        for s in pr.get("nbrs", []):
            if s not in pools:
                continue
            ssum = sum(u["str"] for u in pools[s])
            ratio = ssum / max(1.0, es)
            if ratio < need:
                continue
            score = ratio - 2.0 * fort
            if best is None or score > best[0]:
                best = (score, pid, s)

    if best is None:
        return
    _, tgt, src = best
    us = sorted(pools[src], key=lambda u: -u["str"])
    k = min(12, max(1, len(us) - 2))
    chosen = us[:k]
    ids = ",".join(str(u["id"]) for u in chosen)
    api.cmd("group f%d %s" % (t, ids))
    r = api.cmd("prepare %s P%d" % (ids, tgt))
    if r.startswith("ok"):
        api.mem["plan"] = {
            "ids": [u["id"] for u in chosen],
            "tgt": tgt,
            "t0": t,
            "go": False,
        }
