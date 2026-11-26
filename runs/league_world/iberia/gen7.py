PREF_TECH = [
    "farming", "mining", "industry", "arm.weapons", "mot.mobility",
    "art.weapons", "logistics", "conscription", "arm.protection",
    "inf.weapons", "drill", "medicine", "mot.protection", "mot.weapons",
    "discipline", "staffwork", "fieldworks", "drilling", "refining",
    "mil.protection",
]

# Unit mix. Heavier on arm/mot because idle oil and steel stock is large.
MIX = {"inf": 0.22, "grn": 0.10, "art": 0.16, "arm": 0.22,
       "mot": 0.12, "atg": 0.06, "eng": 0.06, "mec": 0.06}

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


def _attack(api, mem):
    pend = mem.setdefault("pend", {})   # target -> hour preparation began
    cool = mem.setdefault("cool", {})   # target -> hour it may be tried again

    # Units that can take part in a strike.
    elig = {}
    for u in api.units:
        if u.get("path") or u.get("dry"):
            continue
        if u.get("state") in ("routing", "shaken", "pinned", "digging",
                              "refitting", "moving", "assault"):
            continue
        if u.get("str", 0) < 60 or u.get("rdy", 0) < 60:
            continue
        elig.setdefault(u["prov"], []).append(u)

    # Enemy provinces we can see that touch our land.
    targets = {}
    for pid, pr in api.provs.items():
        if pr.get("owner") != "me":
            continue
        for tg in _ints(pr.get("nbrs", [])):
            tp = api.provs.get(tg)
            if not tp or tp.get("owner") != "enemy" or tg not in api.enemy:
                continue
            if cool.get(tg, -1) > api.t:
                continue
            targets.setdefault(tg, set()).add(pid)

    cands = []
    for tg, srcs in targets.items():
        tp = api.provs[tg]
        e = api.enemy.get(tg) or {}
        ehp = float(e.get("str", 0) or 0)
        fort = float(tp.get("fort", 0) or 0)
        need = max(250.0, 2.5 * ehp * (1.0 + 0.4 * fort) * _terr_dfn(tp))
        pool = []
        for s in srcs:
            for u in elig.get(s, []):
                if u.get("plan", -1) in (-1, None, tg):
                    pool.append(u)
        A = float(sum(u.get("str", 0) for u in pool))
        if len(pool) < 3 or A < 0.6 * need:
            continue
        cands.append((tg in pend, A / need, tg, pool, need, ehp, tp))
    cands.sort(key=lambda c: (c[0], c[1]), reverse=True)

    for inpend, ratio, tg, pool, need, ehp, tp in cands:
        prep = [u for u in pool if u.get("plan") == tg]
        A_p = float(sum(u.get("str", 0) for u in prep))
        if A_p >= need and len(prep) >= 3:
            p = _p_take(api, A_p, ehp, tp, prep)
            waited = api.t - pend.get(tg, api.t)
            sel = ",".join(str(u["id"]) for u in prep)
            if p >= 0.5 or (waited >= 12 and p >= 0.3) or waited >= 30:
                api.cmd("group a%d %s" % (api.t, sel))
                api.cmd("move %s P%d" % (sel, tg))
                pend.pop(tg, None)
                return
            if waited >= 72:
                api.cmd("hold %s" % sel)
                pend.pop(tg, None)
                cool[tg] = api.t + 48
                return
            return  # keep waiting while the bonus builds
        todo = [u for u in pool if u.get("plan") != tg]
        if todo:
            sel = ",".join(str(u["id"]) for u in todo)
            api.cmd("prepare %s P%d" % (sel, tg))
            pend.setdefault(tg, api.t)
            return
    return


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
        if neutral and t != "art":
            if str(api.cmd("expand %d" % uid)).startswith("ok"):
                continue
        api.cmd("front %d" % uid)


def tick(api):
    mem = api.mem
    mem["calls"] = mem.get("calls", 0) + 1
    for f in (_diplo, _research, _refit, _recruit, _attack, _orders):
        try:
            f(api, mem)
        except Exception:
            pass
