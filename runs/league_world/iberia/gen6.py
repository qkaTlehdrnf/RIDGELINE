PREF_TECH = [
    "farming", "mining", "industry", "arm.weapons", "mot.mobility",
    "art.weapons", "logistics", "conscription", "arm.protection",
    "inf.weapons", "drill", "medicine", "mot.protection", "mot.weapons",
    "discipline", "staffwork", "fieldworks", "drilling", "refining",
    "mil.protection",
]

# Unit mix: favours cheap-in-res strength (inf, grn, art) and uses the
# unused steel/oil stock through arm and mot.
MIX = {"inf": 0.25, "grn": 0.08, "art": 0.18, "arm": 0.22,
       "mot": 0.10, "atg": 0.06, "eng": 0.05, "mec": 0.06}

_FEAT_W = [1.1911, -0.275, -0.3529, 0.0081, 0.7296, 0.8341, -0.6001, 1.1763]
_FEAT_B = -1.2756
_FEAT_MEAN = [0.7328, 1.3633, 0.9561, 0.1624, 0.0369, 0.1156, 0.6737, 2.1411]
_FEAT_STD = [1.6387, 0.3925, 1.2109, 0.3688, 0.1131, 0.2127, 0.3452, 1.4387]


def _ints(seq):
    out = []
    for x in seq or []:
        try:
            out.append(int(x))
        except Exception:
            pass
    return out


def _terr_dfn(pr):
    t = str(pr.get("terrain", "")).lower()
    if "mount" in t or t == "m":
        return 2.0
    if "hill" in t or t == "h":
        return 1.5
    if "forest" in t or t == "f":
        return 1.25
    return 1.0


def _p_take(api, A, D, tp, prepared):
    n = len(prepared)
    if n == 0:
        return 0.0
    heavy = sum(1 for u in prepared if u.get("type") in ("art", "eng", "arm", "rkt", "hvt"))
    x = [
        math.log((A + 1.0) / (D + 1.0)),
        _terr_dfn(tp),
        float(tp.get("fort", 0) or 0),
        1.0 if tp.get("city") else 0.0,
        max(u.get("bonus", 0) for u in prepared) / 100.0,
        sum(u.get("rdy", 0) for u in prepared) / n / 100.0,
        heavy / float(n),
        1.0,
    ]
    model = api.model or {}
    w = model.get("w", _FEAT_W) if model else _FEAT_W
    b = model.get("b", _FEAT_B) if model else _FEAT_B
    mean = model.get("mean", _FEAT_MEAN) if model else _FEAT_MEAN
    std = model.get("std", _FEAT_STD) if model else _FEAT_STD
    try:
        z = b + sum(w[i] * (x[i] - mean[i]) / std[i] for i in range(len(x)))
    except Exception:
        z = _FEAT_B + sum(_FEAT_W[i] * (x[i] - _FEAT_MEAN[i]) / _FEAT_STD[i]
                          for i in range(len(x)))
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _border_factions(api):
    s = set()
    for pid, pr in api.provs.items():
        if pr.get("owner") != "me":
            continue
        for n in _ints(pr.get("nbrs", [])):
            f = api.owner_name.get(n)
            if f:
                s.add(f)
    return s


def _diplo(api, mem):
    # Accept every pact and any trade that is not a tribute demand.
    for o in list(api.offers_in or []):
        try:
            if o.get("kind") == "pact":
                api.cmd("accept %s" % o["id"])
            elif o.get("kind") == "trade":
                give = o.get("they_give", {}) or {}
                pay = o.get("you_give", {}) or {}
                if "mp" in pay:
                    continue
                if sum(give.values()) >= sum(pay.values()):
                    api.cmd("accept %s" % o["id"])
        except Exception:
            pass
    # Offer pacts only to factions we do not border, so the front stays live.
    if api.t - mem.get("last_pact", -999) < 96:
        return
    pacts = api.pacts or {}
    pending = set(o.get("to") for o in list(api.offers_out or []))
    border = _border_factions(api)
    n = 0
    for f in api.met:
        if n >= 2:
            break
        if f in pacts or f in pending or f in border:
            continue
        api.cmd("offer %s pact 120" % f)
        n += 1
    mem["last_pact"] = api.t


def _research(api, mem):
    busy = [r[0] for r in api.research]
    slots = 2 - len(busy)
    spent = {}
    for line in PREF_TECH:
        if slots <= 0:
            break
        info = api.tech.get(line)
        if not info or info.get("status") != "open":
            continue
        cost = info.get("cost") or {}
        ok = True
        for k, v in cost.items():
            reserve = 100 if k == "res" else 0
            if api.stock.get(k, 0) - spent.get(k, 0) < v + reserve:
                ok = False
                break
        if not ok:
            continue
        if str(api.cmd("research " + line)).startswith("ok"):
            slots -= 1
            for k, v in cost.items():
                spent[k] = spent.get(k, 0) + v


def _refit(api, mem):
    if api.res < 300:
        return
    done = 0
    spent = {}
    for u in api.units:
        if done >= 40:
            break
        if not u.get("old"):
            continue
        if u.get("path") or u.get("state") not in ("ready", "defending", "digging"):
            continue
        if u.get("rdy", 0) < 30 or u.get("str", 0) < 40:
            continue
        rc = api.refit_cost.get(u["type"]) or {}
        if api.res - spent.get("res", 0) - rc.get("res", 0) < 200:
            continue
        ok = True
        for k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) - spent.get(k, 0) < rc.get(k, 0):
                ok = False
        if not ok:
            continue
        if str(api.cmd("refit %d" % u["id"])).startswith("ok"):
            done += 1
            for k in ("res", "steel", "oil", "rare"):
                spent[k] = spent.get(k, 0) + rc.get(k, 0)


def _affordable(api, uc, spent):
    if api.res - spent.get("res", 0) < uc.get("res", 0) + 80:
        return False
    if api.mp - spent.get("mp", 0) < uc.get("mp", 0) + 25:
        return False
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) - spent.get(k, 0) < uc.get(k, 0):
            return False
    return True


def _recruit(api, mem):
    units = api.units
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    total = len(units)
    if api.income < 0 and total > 20:
        return
    spent = {}
    picks = 5 if api.res > 300 else 1

    if cnt.get("rec", 0) < 2 and total >= 4:
        uc = api.unit_costs.get("rec")
        if uc and _affordable(api, uc, spent):
            if str(api.cmd("recruit rec 1 P%d" % api.capital)).startswith("ok"):
                for k in ("res", "mp", "steel", "oil", "rare"):
                    spent[k] = spent.get(k, 0) + uc.get(k, 0)
                cnt["rec"] = cnt.get("rec", 0) + 1

    for _ in range(picks):
        best = None
        best_def = -1e9
        for t, w in MIX.items():
            uc = api.unit_costs.get(t)
            if not uc or not _affordable(api, uc, spent):
                continue
            deficit = w * (total + 1) - cnt.get(t, 0)
            if deficit > best_def:
                best_def = deficit
                best = (t, uc)
        if best is None:
            break
        t, uc = best
        if not str(api.cmd("recruit %s 1 P%d" % (t, api.capital))).startswith("ok"):
            break
        for k in ("res", "mp", "steel", "oil", "rare"):
            spent[k] = spent.get(k, 0) + uc.get(k, 0)
        cnt[t] = cnt.get(t, 0) + 1
        total += 1


def _orders(api, mem):
    neutral = len(api.neutral_border) > 0
    for u in api.units:
        if u.get("path") or u.get("front") or u.get("expand") or u.get("explore"):
            continue
        if u.get("state") in ("moving", "assault", "routing", "pinned",
                              "digging", "refitting", "preparing"):
            continue
        if u.get("plan", -1) not in (-1, None):
            continue
        uid = u["id"]
        t = u["type"]
        if t == "rec":
            api.cmd("explore %d" % uid)
            continue
        if u.get("str", 100) < 40:
            if u.get("prov") != api.capital:
                api.cmd("move %d P%d" % (uid, api.capital))
            continue
        if t in ("arm", "hvt", "art", "rkt", "atg", "mec", "mot") or not neutral:
            api.cmd("front %d" % uid)
            continue
        r = api.cmd("expand %d" % uid)
        if not str(r).startswith("ok"):
            api.cmd("front %d" % uid)


def _attack(api, mem):
    pend = mem.setdefault("pend", {})
    rdy_by = {}
    for u in api.units:
        if u.get("path") or u.get("dry"):
            continue
        if u.get("state") in ("routing", "shaken", "pinned", "digging", "refitting"):
            continue
        if u.get("str", 0) < 70 or u.get("rdy", 0) < 70:
            continue
        rdy_by.setdefault(u["prov"], []).append(u)

    # Candidate targets: enemy provinces we can see, next to our land.
    targets = {}
    for pid, pr in api.provs.items():
        if pr.get("owner") != "me":
            continue
        for tg in _ints(pr.get("nbrs", [])):
            tp = api.provs.get(tg)
            if not tp or tp.get("owner") != "enemy" or tg not in api.enemy:
                continue
            targets.setdefault(tg, set()).add(pid)

    scored = []
    for tg, srcs in targets.items():
        tp = api.provs[tg]
        ehp = api.enemy[tg].get("str", 0)
        pool = [u for s in srcs for u in rdy_by.get(s, [])]
        if not pool:
            continue
        A = float(sum(u.get("str", 0) for u in pool))
        scored.append((A / max(1.0, ehp), tg, srcs, pool))
    scored.sort(key=lambda x: -x[0])

    for ratio, tg, srcs, pool in scored:
        tp = api.provs[tg]
        ehp = api.enemy[tg].get("str", 0)
        fort = tp.get("fort", 0) or 0
        n_art = sum(1 for u in pool if u.get("type") in ("art", "rkt"))
        if fort >= 1 and n_art < 3:
            continue
        if fort >= 2 and n_art < 6:
            continue
        if fort >= 3 and n_art < 10:
            continue
        key = str(tg)
        prepared = [u for u in pool if u.get("plan") == tg]

        if not prepared:
            A = float(sum(u.get("str", 0) for u in pool))
            if A < max(400, 3.0 * ehp):
                continue
            for s in srcs:
                api.cmd("prepare @P%d P%d" % (s, tg))
            pend[key] = api.t
            return

        A = float(sum(u.get("str", 0) for u in prepared))
        if A < max(350, 2.0 * ehp):
            continue
        p = _p_take(api, A, ehp, tp, prepared)
        waited = api.t - pend.get(key, api.t)
        go = (p >= 0.5) or (waited >= 24 and p >= 0.35) or (waited >= 60 and p >= 0.25)
        if go:
            ids = [u["id"] for u in prepared]
            sel = ",".join(str(i) for i in ids)
            api.cmd("group a%d %s" % (api.t, sel))
            api.cmd("move %s P%d" % (sel, tg))
            pend.pop(key, None)
            return


def tick(api):
    mem = api.mem
    mem["calls"] = mem.get("calls", 0) + 1
    for f in (_diplo, _research, _refit, _recruit, _orders, _attack):
        try:
            f(api, mem)
        except Exception:
            pass
