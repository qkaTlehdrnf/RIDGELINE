def tick(api):
    for part in (_economy, _pacts, _recruit, _scouts, _research, _refit, _assign, _attack):
        try:
            part(api)
        except Exception:
            pass


WEIGHTS = {
    "inf": 0.16, "mtn": 0.04, "eng": 0.06, "art": 0.16, "atg": 0.12,
    "arm": 0.16, "mec": 0.12, "grn": 0.06, "cav": 0.02, "mot": 0.06,
}
RESEARCH_ORDER = [
    "farming", "conscription", "inf.weapons", "arm.weapons", "atg.weapons",
    "art.weapons", "inf.protection", "arm.protection", "mec.protection",
    "medicine", "mining", "drilling", "logistics", "drill",
    "discipline", "industry", "fieldworks", "staffwork", "refining",
    "mot.mobility", "mtn.protection",
]
TERR = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
MAX_FORT_TARGET = 2
MIN_RATIO = 2.0
MIN_P = 0.5
MAX_CHOSEN = 24
GROUP_SIZE = 8


def _sig(z):
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _economy(api):
    api.mem["net_res"] = api.income_by.get("res", 0)


def _border_factions(api):
    out = set()
    for pid, pr in api.provs.items():
        if pr.get("owner") != "me":
            continue
        for n in pr.get("nbrs", []):
            npr = api.provs.get(n)
            if npr and npr.get("owner") == "enemy":
                who = api.owner_name.get(n)
                if who:
                    out.add(who)
    return out


def _pacts(api):
    if api.t % 6 != 0:
        return
    # Accept every pact offered: peace on the rear is worth having.
    for o in api.offers_in:
        if o.get("kind") == "pact":
            api.cmd("accept %s" % o["id"])
    if api.t % 96 != 0:
        return
    # Offer pacts only to factions that do not share a border with us,
    # so the land next to us stays open for conquest.
    border = _border_factions(api)
    for f in api.met:
        if f in api.pacts or f in border:
            continue
        api.cmd("offer %s pact 240" % f)


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
    if api.t % 3 != 0:
        return
    if api.income_by.get("res", 0) < 8 + 0.01 * len(api.units):
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
        if _afford(api, api.unit_costs.get(typ), reserve=120):
            r = api.cmd("recruit %s P%d" % (typ, api.capital))
            if r.startswith("ok"):
                break


def _scouts(api):
    if api.t % 12 != 0 or not api.unexplored:
        return
    if _counts(api).get("rec", 0) >= 2:
        return
    if _afford(api, api.unit_costs.get("rec"), reserve=40):
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
        if _afford(api, info.get("cost"), reserve=100):
            r = api.cmd("research %s" % line)
            if r.startswith("ok"):
                break


def _refit(api):
    if api.t % 12 != 5 or api.old_units <= 0:
        return
    groups = {}
    for u in api.units:
        if not u.get("old") or u["path"] or u["fighting"]:
            continue
        if u["state"] != "ready" or not u["supplied"]:
            continue
        groups.setdefault(u["type"], []).append(u["id"])
    for typ, ids in groups.items():
        rc = api.refit_cost.get(typ) or {}
        k = len(ids)
        for what in ("res", "steel", "oil", "rare"):
            need = rc.get(what, 0)
            if need <= 0:
                continue
            avail = api.stock.get(what, 0) - (40 if what == "res" else 0)
            k = min(k, int(max(0, avail) // need))
        if k > 0:
            r = api.cmd("refit %s" % ",".join(str(i) for i in ids[:k]))
            if r.startswith("ok"):
                return


def _pools(api, held):
    pools = {}
    for u in api.units:
        if u["id"] in held or u["path"] or u["type"] == "rec":
            continue
        if u["state"] not in ("ready", "refitting"):
            continue
        if u["str"] < 50 or u["rdy"] < 50 or u["dry"]:
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
    for i in range(0, len(combat), GROUP_SIZE):
        sel = ",".join(str(x) for x in combat[i:i + GROUP_SIZE])
        if api.neutral_border:
            api.cmd("expand %s" % sel)
        else:
            api.cmd("front %s" % sel)


def _p_take(api, ssum, es, tgt_pr, chosen, ndirs):
    m = api.model or {}
    feats = m.get("features")
    if not feats:
        return 0.6 if ssum >= 3.0 * max(1.0, es) else 0.0
    heavy = sum(1 for u in chosen if u["type"] in ("art", "eng", "arm")) / float(len(chosen))
    avg_rdy = sum(u["rdy"] for u in chosen) / float(len(chosen)) / 100.0
    x = {
        "log_ratio": math.log((ssum + 1.0) / (es + 1.0)),
        "terrain_dfn": TERR.get(tgt_pr.get("terrain"), 1.0),
        "fort": float(tgt_pr.get("fort") or 0),
        "city": 1.0 if tgt_pr.get("city") else 0.0,
        "bonus": 0.0,
        "att_rdy": avg_rdy,
        "heavy_share": heavy,
        "dirs": float(ndirs),
    }
    z = m.get("b", 0.0)
    for i, f in enumerate(feats):
        sd = m["std"][i] or 1.0
        z += m["w"][i] * (x.get(f, 0.0) - m["mean"][i]) / sd
    return _sig(z)


def _attack(api):
    t = api.t
    plan = api.mem.get("plan")

    if plan:
        alive = [u for u in api.units if u["id"] in plan["ids"]]
        tgt = plan["tgt"]
        pr = api.provs.get(tgt, {})
        if not alive or t - plan["t0"] > 48 or pr.get("owner") == "me":
            api.mem["plan"] = None
            return
        if not plan.get("go"):
            avg_rdy = sum(u["rdy"] for u in alive) / len(alive)
            waited = t - plan["t0"]
            if (waited >= 12 and avg_rdy >= 70) or (waited >= 18 and avg_rdy >= 55):
                ids = ",".join(str(u["id"]) for u in alive)
                api.cmd("move %s P%d" % (ids, tgt))
                plan["go"] = True
                api.mem["plan"] = None
        return

    if t % 6 != 0 or api.stock.get("res", 0) < 80:
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
        if fort > MAX_FORT_TARGET:
            continue
        srcs = [s for s in pr.get("nbrs", []) if s in pools]
        for s in srcs:
            us = sorted(pools[s], key=lambda u: -u["str"])
            k = min(MAX_CHOSEN, max(1, len(us) - 2))
            chosen = us[:k]
            ssum = sum(u["str"] for u in chosen)
            if ssum < MIN_RATIO * max(1.0, es):
                continue
            p = _p_take(api, ssum, es, pr, chosen, len(srcs))
            if p < MIN_P:
                continue
            score = p * min(ssum / max(1.0, es), 6.0)
            if best is None or score > best[0]:
                best = (score, pid, s, chosen)

    if best is None:
        return
    _, tgt, src, chosen = best
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
