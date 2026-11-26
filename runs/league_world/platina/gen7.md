**Reasoning**

War 7 ended 11th of 30 with 126 provinces. The review points to supply, not combat. Depot P3527 served 126 provinces at 98/60 load with output x0.61, and late-war stocks ran empty. Readiness fell from about 90 to 68 after day 70, and 75% of hvt and rkt units were short of supplies. Meanwhile rare piled up to 1406 unused because steel and oil were the bottlenecks.

Changes:
1. **Depots:** open more depots (up to 8) when any depot is overloaded or underperforming, on a 24 h cooldown, at any depth from 1 to 6. Prefer cities and provinces with many own neighbours.
2. **Rare-for-steel trades:** when rare is high and steel low, offer pact partners rare for steel, and accept similar offers.
3. Everything else is kept, since the army logic did not fail in the review.

```python
ECON = ["farming", "conscription", "medicine", "logistics", "industry", "discipline",
        "mining", "drilling", "refining", "fieldworks", "drill", "staffwork"]
MILLINES = ["mot.weapons", "arm.weapons", "mot.mobility", "art.weapons",
            "arm.protection", "mil.protection", "inf.protection", "grn.weapons",
            "atg.weapons", "inf.weapons", "eng.protection", "mtn.protection"]
DEPOSIT = {"mining": "steel", "drilling": "oil", "refining": "rare", "staffwork": None}
TARGET = {"inf": 0.18, "mil": 0.08, "mtn": 0.05, "mot": 0.14, "arm": 0.16,
          "art": 0.12, "eng": 0.04, "atg": 0.06, "grn": 0.06, "mec": 0.04,
          "cav": 0.02, "hvt": 0.04, "rkt": 0.03}
ATTACK = ("arm", "mot", "art", "grn", "atg", "hvt", "mec", "rkt")
FRONTT = ("inf", "mil", "mtn", "eng", "cav")


def terr_dfn(terr):
    s = str(terr).lower()
    if "mount" in s:
        return 2.0
    if "hill" in s:
        return 1.5
    if "forest" in s:
        return 1.25
    return 1.0


def assault_p(api, st, e, n_dirs, ds):
    model = api.model
    if not model or "w" not in model or "features" not in model:
        return None
    pr = api.provs.get(e, {})
    A = sum(u.get("str", 0) for u in st)
    lr = math.log((A + 1.0) / (ds + 1.0))
    fort = pr.get("fort", 0) or 0
    n = float(len(st)) or 1.0
    fv = {
        "log_ratio": lr,
        "terrain_dfn": terr_dfn(pr.get("terrain", "")),
        "fort": fort,
        "city": 1.0 if pr.get("city") else 0.0,
        "bonus": 0.0,
        "att_rdy": sum(u.get("rdy", 50) for u in st) / n / 100.0,
        "heavy_share": sum(1 for u in st if u["type"] in ("art", "eng", "arm")) / n,
        "dirs": float(n_dirs),
    }
    z = model.get("b", 0.0)
    w = model.get("w", [])
    mean = model.get("mean", [])
    std = model.get("std", [])
    for i, f in enumerate(model["features"]):
        if i >= len(w) or i >= len(mean) or i >= len(std) or std[i] == 0:
            continue
        x = fv.get(f, 0.0)
        z += w[i] * (x - mean[i]) / std[i]
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def tick(api):
    m = api.mem
    t = api.t
    units = api.units
    provs = api.provs
    cap = api.capital
    m["n"] = m.get("n", 0) + 1

    def cmd(s):
        try:
            return api.cmd(s)
        except Exception:
            return "err"

    def ids(lst):
        return ",".join(str(u["id"]) for u in lst)

    def nid(x):
        try:
            return int(str(x).replace("~", "").replace("P", "").strip())
        except Exception:
            return None

    def nbrs(p):
        pr = provs.get(p)
        if not pr:
            return []
        out = []
        for x in pr.get("nbrs", []):
            v = nid(x)
            if v is not None:
                out.append(v)
        return out

    def free(u):
        return (not u.get("path") and u.get("state") == "ready"
                and not u.get("front") and not u.get("expand")
                and not u.get("explore") and u.get("group") != "strike")

    pact_set = set(api.pacts.keys()) if api.pacts else set()
    owner_name = api.owner_name or {}

    def at_peace(p):
        return owner_name.get(p) in pact_set

    # ---- diplomacy ----
    try:
        for o in (api.offers_in or []):
            if o.get("id") is None:
                continue
            if o.get("kind") == "pact":
                cmd("accept %s" % o["id"])
            elif o.get("kind") == "trade":
                got = o.get("they_give", {}) or {}
                paid = o.get("you_give", {}) or {}
                useful = sum(got.get(k, 0) for k in ("oil", "steel", "rare"))
                pay_res = paid.get("res", 0)
                rr = paid.get("rare", 0)
                paid_keys = set(paid.keys())
                if useful > 0 and paid_keys <= {"res", "rare"}:
                    ok_res = pay_res <= 0.5 * useful and api.stock.get("res", 0) >= pay_res + 100
                    ok_rare = rr <= 0 or (api.stock.get("rare", 0) - rr >= 200 and useful >= 1.2 * rr)
                    if ok_res and ok_rare:
                        cmd("accept %s" % o["id"])
        pt = m.get("pact_t", {})
        for f in (api.met or []):
            if f in pact_set:
                continue
            if t - pt.get(f, -999) >= 240:
                cmd("offer %s pact" % f)
                pt[f] = t
        m["pact_t"] = pt
        # rare is plentiful but steel is short: offer rare for steel to partners
        if api.stock.get("rare", 0) > 500 and api.stock.get("steel", 0) < 300:
            ot = m.get("trade_t", {})
            for f in sorted(pact_set):
                if t - ot.get(f, -999) >= 96:
                    if cmd("offer %s trade 60 rare for 120 steel" % f).startswith("ok"):
                        ot[f] = t
                        break
            m["trade_t"] = ot
    except Exception:
        pass

    owned = [p for p, pr in provs.items() if pr.get("owner") == "me"]
    enemy_near = {}
    for p in owned:
        for n in nbrs(p):
            q = provs.get(n)
            if q and q.get("owner") == "enemy" and not at_peace(n):
                enemy_near.setdefault(n, []).append(p)
    enemy_adj = set(v for lst in enemy_near.values() for v in lst)

    # depth of each owned province behind the nearest front province
    depth = {}
    frontier = list(enemy_adj)
    for p in frontier:
        depth[p] = 0
    d = 0
    while frontier and d < 8:
        d += 1
        nxt = []
        for p in frontier:
            for n in nbrs(p):
                if n in depth or provs.get(n, {}).get("owner") != "me":
                    continue
                depth[n] = d
                nxt.append(n)
        frontier = nxt

    own_dep = {}
    for k in ("steel", "oil", "rare"):
        own_dep[k] = any(provs[p].get(k, 0) > 0 for p in owned)

    keep = 40 if api.income >= 0 else 100
    pool = {"res": api.stock.get("res", 0) - keep, "mp": api.mp,
            "steel": api.stock.get("steel", 0), "oil": api.stock.get("oil", 0),
            "rare": api.stock.get("rare", 0)}

    def pay(d_):
        if not d_:
            return False
        for k in ("res", "mp", "steel", "oil", "rare"):
            if pool.get(k, 0) < d_.get(k, 0):
                return False
        return True

    def spend(d_):
        for k in ("res", "mp", "steel", "oil", "rare"):
            pool[k] = pool.get(k, 0) - d_.get(k, 0)

    # ---- research: two projects at once ----
    try:
        types_have = set(u["type"] for u in units)
        busy = set(r[0] for r in api.research)
        slots = 2 - len(api.research)
        for line in ECON + MILLINES:
            if slots <= 0:
                break
            if line in busy:
                continue
            if "." in line and line.split(".")[0] not in types_have:
                continue
            if line in DEPOSIT:
                dep = DEPOSIT[line]
                if dep and not own_dep.get(dep):
                    continue
            tk = api.tech.get(line)
            if not tk or tk.get("status") != "open" or tk.get("level", 0) >= 3:
                continue
            cost = tk.get("cost")
            if not pay(cost):
                continue
            if cmd("research " + line).startswith("ok"):
                spend(cost)
                slots -= 1
    except Exception:
        pass

    # ---- depots: spread supply when any depot is overloaded or underperforming ----
    try:
        deps = api.depots or {}
        loads = [(dd.get("load", 0) or 0) for dd in deps.values()]
        outs = [(dd.get("output", 1) or 1) for dd in deps.values()]
        hot = (max(loads) if loads else 0) > 25 or (min(outs) if outs else 1) < 0.8
        if t - m.get("dep_t", -99) >= 24 and len(deps) < 8 and pool.get("res", 0) >= 200:
            if hot or len(deps) < 2:
                best, bkey = None, None
                for p in owned:
                    if p in deps or not provs[p].get("supplied", True):
                        continue
                    if any(provs.get(n, {}).get("owner") == "enemy" for n in nbrs(p)):
                        continue
                    dp = depth.get(p, 3)
                    if dp < 1 or dp > 6:
                        continue
                    own_nb = sum(1 for n in nbrs(p) if provs.get(n, {}).get("owner") == "me")
                    key = (1 if provs[p].get("city") else 0, own_nb, -abs(dp - 3))
                    if bkey is None or key > bkey:
                        bkey, best = key, p
                if best is not None and cmd("depot P%d 1" % best).startswith("ok"):
                    m["dep_t"] = t
                    pool["res"] = pool.get("res", 0) - 150
    except Exception:
        pass

    # ---- refit outdated units sitting safely in the rear ----
    try:
        old = [u for u in units if u.get("old") and u.get("state") == "ready"
               and not u.get("path") and u.get("prov") not in enemy_adj
               and u.get("supplied")]
        by_type = {}
        for u in old:
            by_type.setdefault(u["type"], []).append(u)
        for ty, lst in by_type.items():
            rc = api.refit_cost.get(ty)
            if not rc:
                continue
            afford = 99
            for k in ("res", "steel", "oil", "rare"):
                c = rc.get(k, 0)
                if c > 0:
                    afford = min(afford, int(max(pool.get(k, 0), 0) // c))
            n_ref = min(afford, 24, len(lst))
            if n_ref <= 0:
                continue
            batch = lst[:n_ref]
            if cmd("refit %s" % ids(batch)).startswith("ok"):
                for k in ("res", "steel", "oil", "rare"):
                    pool[k] = pool.get(k, 0) - rc.get(k, 0) * len(batch)
    except Exception:
        pass

    # ---- recruitment: spend the bank, front-weighted ----
    try:
        counts = {}
        for u in units:
            counts[u["type"]] = counts.get(u["type"], 0) + 1
        n0 = len(units)

        tgt = dict(TARGET)
        rare = pool.get("rare", 0)
        if rare > 800:
            tgt["rkt"] += 0.10
            tgt["hvt"] += 0.10
        elif rare > 300:
            tgt["rkt"] += 0.06
            tgt["hvt"] += 0.06
        elif rare > 150:
            tgt["rkt"] += 0.03
            tgt["hvt"] += 0.03
        if pool.get("oil", 0) > 200:
            tgt["arm"] += 0.05
            tgt["mot"] += 0.05
        elif pool.get("oil", 0) > 100:
            tgt["arm"] += 0.03
            tgt["mot"] += 0.03
        if pool.get("steel", 0) > 500:
            tgt["hvt"] += 0.03
            tgt["atg"] += 0.02

        front_city = cap
        for p in owned:
            if provs[p].get("city") and p in enemy_adj:
                front_city = p
                break

        if counts.get("rec", 0) < 2 and pay(api.unit_costs.get("rec")):
            if cmd("recruit rec 1 P%d" % cap).startswith("ok"):
                spend(api.unit_costs.get("rec"))
                counts["rec"] = counts.get("rec", 0) + 1

        made = 0
        while made < 12:
            best, bd = None, -1e9
            for ty, share in tgt.items():
                dc = api.unit_costs.get(ty)
                if not pay(dc):
                    continue
                deficit = share * (n0 + made + 1) - counts.get(ty, 0)
                if deficit > bd:
                    bd, best = deficit, ty
            if best is None:
                break
            if cmd("recruit %s 1 P%d" % (best, front_city)).startswith("ok"):
                spend(api.unit_costs.get(best))
                counts[best] = counts.get(best, 0) + 1
                made += 1
            else:
                break
    except Exception:
        pass

    # ---- unit roles ----
    try:
        live = set(u["id"] for u in units)
        fort_set = set(x for x in m.get("fort", []) if x in live)
        rest_t = m.get("rest_t", {})

        for u in units:
            if u["type"] == "rec" and not u.get("explore") and not u.get("path") \
                    and u.get("state") == "ready":
                cmd("explore %d" % u["id"])

        to_strike = [u for u in units if u["type"] in ATTACK and free(u)]
        if to_strike:
            verb = "group strike + %s" if "strike" in api.formations else "group strike %s"
            cmd(verb % ids(to_strike))

        # border units: weak ones refit at home, healthy ones dig in once
        border = [u for u in units if u["type"] in FRONTT and not u.get("path")
                  and u.get("state") == "ready" and u.get("prov") in enemy_adj
                  and not u.get("expand") and not u.get("explore")
                  and u.get("group") != "strike"]
        weak = [u for u in border if u.get("str", 0) < 40
                and t - rest_t.get(u["id"], -99) >= 24]
        if weak and cap is not None:
            cmd("move %s P%d" % (ids(weak), cap))
            for u in weak:
                rest_t[u["id"]] = t
        dig = [u for u in border if u["id"] not in fort_set and u.get("str", 0) >= 40]
        if dig:
            cmd("fortify %s" % ids(dig))
            fort_set.update(u["id"] for u in dig)

        # interior units: expand to neutral land first, rest join the front
        interior = [u for u in units if u["type"] in FRONTT and free(u)
                    and u.get("prov") not in enemy_adj]
        neutral = list(api.neutral_border)
        n_exp = sum(1 for u in units if u.get("expand"))
        need = 2 * len(neutral) - n_exp
        sel = []
        if need > 0 and interior:
            interior.sort(key=lambda u: 0 if u["type"] == "mil" else 1)
            sel = interior[:need]
            cmd("expand %s" % ids(sel))
        rest = [u for u in interior if u not in sel]
        if rest:
            cmd("front %s" % ids(rest))

        m["fort"] = list(fort_set)
        m["rest_t"] = {k: v for k, v in rest_t.items() if k in live}
    except Exception:
        pass

    # ---- strike group: stage at high readiness, assault only good odds ----
    try:
        st = [u for u in units if u.get("group") == "strike"]
        n_st = len(st)
        total = sum(u.get("str", 0) for u in st)
        avg_s = total / n_st if n_st else 0.0
        avg_r = sum(u.get("rdy", 0) for u in st) / n_st if n_st else 0.0
        op = m.get("op")
        if op is not None:
            e, s = op["tgt"], op["stg"]
            if provs.get(e, {}).get("owner") == "me" or n_st < 3 or t - op["t0"] > 120 \
                    or at_peace(e):
                m["op"] = None
            elif op["ph"] == "gather":
                away = [u for u in st if u["prov"] != s and not u.get("path")]
                if away:
                    cmd("move %s P%d" % (ids(away), s))
                there = [u for u in st if u["prov"] == s]
                ready_enough = avg_r >= 75 or t - op["t0"] >= 72
                if there and len(there) >= max(3, int(0.8 * n_st)) and ready_enough:
                    cmd("prepare %s P%d" % (ids(there), e))
                    op["ph"], op["tp"] = "prep", t
            elif op["ph"] == "prep":
                if t - op["tp"] >= 12:
                    cmd("move %s P%d" % (ids(st), e))
                    op["ph"], op["tg"] = "go", t
            elif op["ph"] == "go":
                if t - op["tg"] >= 30:
                    m["op"] = None
        elif n_st >= 4:
            if avg_s < 70 or avg_r < 60:
                if t - m.get("refit_t", -99) >= 24 and cap is not None:
                    cmd("move %s P%d" % (ids(st), cap))
                    m["refit_t"] = t
            else:
                caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
                best, bscore = None, -1.0
                for e, cands in enemy_near.items():
                    seen = api.enemy.get(e)
                    es = seen.get("str", 60) if seen else 60
                    if total < 3.5 * es:
                        continue
                    fort = provs.get(e, {}).get("fort", 0) or 0
                    if fort >= 3:
                        continue
                    p = assault_p(api, st, e, len(cands), es)
                    if p is None:
                        ratio = total / max(es, 1)
                        p = 0.6 if (ratio >= 3.5 and fort <= 1) else (0.3 if ratio >= 2.5 else 0.0)
                    need_p = 0.65 if fort >= 2 else 0.6
                    if p < need_p:
                        continue
                    score = p * (1.0 + 0.02 * provs[e].get("y", 0)) + (1.0 if e in caps else 0.0)
                    if score > bscore:
                        bscore, best = score, (e, cands)
                if best:
                    e, cands = best
                    stg, bl = None, 1e9
                    for s in cands[:6]:
                        pth = api.path(st[0]["prov"], s)
                        if pth is not None and len(pth) < bl:
                            bl, stg = len(pth), s
                    if stg is not None:
                        m["op"] = {"tgt": e, "stg": stg, "ph": "gather", "t0": t}
    except Exception:
        pass

    m["last_t"] = t
```

```letters
to amazonia: Platina keeps its pacts too. While we both hold, we will trade rare for steel at a fair rate; offer and accept in good faith.
```

REVIEW: full