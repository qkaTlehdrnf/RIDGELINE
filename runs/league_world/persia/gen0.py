RES_RESERVE = 40
ATTACK_RATIO = 2.0
PREP_TICKS = 12
MIX = [("inf", 0.30), ("mil", 0.05), ("mtn", 0.07), ("grn", 0.08), ("mot", 0.10),
       ("arm", 0.10), ("mec", 0.05), ("atg", 0.08), ("art", 0.08), ("eng", 0.05),
       ("rkt", 0.02), ("hvt", 0.02)]
LINES = ["inf.weapons", "inf.protection", "arm.weapons", "arm.protection",
         "farming", "conscription", "mining", "drill", "discipline", "medicine",
         "industry", "logistics", "staffwork", "fieldworks", "drilling", "refining",
         "mot.mobility", "mtn.weapons", "grn.weapons"]


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def _affordable(api, typ):
    uc = api.unit_costs.get(typ)
    if not uc:
        return False
    st = api.stock
    if st.get("res", 0) < uc.get("res", 0) + RES_RESERVE:
        return False
    if api.mp < uc.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < uc.get(k, 0):
            return False
    return True


def _research(api):
    running = [r[0] for r in api.research]
    slots = 2 - len(running)
    if slots <= 0:
        return
    for line in LINES:
        if slots <= 0:
            break
        if line in running:
            continue
        info = api.tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost")
        if not cost:
            continue
        ok = True
        for k, v in cost.items():
            need = v + (RES_RESERVE if k == "res" else 0)
            if api.stock.get(k, 0) < need:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            slots -= 1


def _recruit(api, cnt, total):
    if api.res < RES_RESERVE:
        return
    if api.income < 0 and api.res < 150:
        return
    if cnt.get("rec", 0) < 2 and _affordable(api, "rec"):
        r = api.cmd("recruit rec P%d" % api.capital)
        if r.startswith("ok"):
            cnt["rec"] = cnt.get("rec", 0) + 1
            total += 1
    sum_w = sum(w for _, w in MIX)
    for _ in range(2):
        best, bd = None, -1e9
        size = total + 1
        for typ, w in MIX:
            if not _affordable(api, typ):
                continue
            d = w / sum_w * size - cnt.get(typ, 0)
            if d > bd:
                best, bd = typ, d
        if best is None:
            break
        r = api.cmd("recruit %s P%d" % (best, api.capital))
        if not r.startswith("ok"):
            break
        cnt[best] = cnt.get(best, 0) + 1
        total += 1


def _assign(api):
    units = api.units
    total = len(units)
    n_exp = sum(1 for u in units if u.get("expand"))
    idle = []
    for u in units:
        if u.get("path"):
            continue
        if u.get("state") not in ("ready", "refitting"):
            continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("group"):
            continue
        idle.append(u)
    scouts, exp, fr = [], [], []
    for u in idle:
        if u["type"] == "rec":
            if api.unexplored:
                scouts.append(u)
        elif (u["type"] in ("art", "atg", "eng") or not api.neutral_border
              or n_exp >= 0.5 * total):
            fr.append(u)
        else:
            exp.append(u)
            n_exp += 1
    if scouts:
        api.cmd("explore " + _ids(scouts))
    if exp:
        api.cmd("expand " + _ids(exp))
    if fr:
        api.cmd("front " + _ids(fr))


def _attack(api):
    mem = api.mem
    prep = mem.setdefault("prep", {})
    t = api.t
    for q in list(prep.keys()):
        if t - prep[q] > 60:
            del prep[q]
    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    by_prov = {}
    for u in api.units:
        if u.get("path"):
            continue
        if u.get("prov") in mine:
            by_prov.setdefault(u["prov"], []).append(u)
    cands = {}
    for p in by_prov:
        for q in api.provs[p].get("nbrs", []):
            if q in api.enemy and api.provs.get(q, {}).get("owner") != "me":
                cands.setdefault(q, []).append(p)
    used = set()
    for q, srcs in cands.items():
        if q in used:
            continue
        en = api.enemy[q]
        sd = en.get("str", 0) * 1.3
        att = []
        for p in srcs:
            for u in by_prov.get(p, []):
                if u["id"] in used or u["type"] == "rec":
                    continue
                if u.get("rdy", 0) >= 60 and u.get("str", 0) >= 50 and \
                   u.get("state") in ("ready", "preparing"):
                    att.append(u)
        if len(att) < 3:
            continue
        sa = sum(u["str"] * u.get("rdy", 50) / 100.0 for u in att)
        if sa < ATTACK_RATIO * sd:
            continue
        if q not in prep:
            api.cmd("prepare %s P%d" % (_ids(att), q))
            prep[q] = t
            used.update(u["id"] for u in att)
        elif t - prep[q] >= PREP_TICKS:
            api.cmd("move %s P%d" % (_ids(att), q))
            del prep[q]
            used.update(u["id"] for u in att)
            break


def tick(api):
    api.mem["n"] = api.mem.get("n", 0) + 1
    cnt = {}
    for u in api.units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    total = len(api.units)
    try:
        _research(api)
    except Exception:
        pass
    try:
        _recruit(api, cnt, total)
    except Exception:
        pass
    try:
        _assign(api)
    except Exception:
        pass
    try:
        _attack(api)
    except Exception:
        pass
