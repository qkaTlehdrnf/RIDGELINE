**Reasoning (brief):** The last war ended 13th with 105 provinces, and every one of 45 assaults failed. The main problems were attacks launched on weak odds and a front that stalled once neutral land ran out. The changes below:

- **Assault gating:** Use the fitted `api.model` logistic (with hardcoded fallback weights) to estimate take probability. Attack only with at least 1.5x strength over the defender and p ≥ 0.5, or after a long wait with a lower threshold.
- **Preparation:** Wait longer for the prepared bonus (up to 72 h), and require more artillery against forts.
- **Mix:** Slightly more artillery, since it outranges and softens defenders.
- **Refit:** Refit older units sooner, to reduce the 619 outdated units seen last war.
- **Research:** Prioritise the weapon and armour lines that paid off last war.
- **Diplomacy:** Keep the pact logic, which kept neighbours quiet.

I can't verify these numbers offline, so treat the thresholds as a first guess.

```python
PREF_TECH = [
    "arm.weapons", "mot.mobility", "art.weapons", "arm.protection",
    "mining", "logistics", "conscription", "farming",
    "medicine", "inf.weapons", "drill", "discipline",
    "mot.protection", "mot.weapons", "industry", "staffwork",
    "fieldworks", "drilling", "mil.protection", "refining",
]

MIX = {"inf": 0.22, "art": 0.18, "arm": 0.27, "mot": 0.15,
       "atg": 0.06, "eng": 0.05, "mec": 0.07}

# take-probability model (fallback if api.model is empty)
_FEAT = ["log_ratio", "terrain_dfn", "fort", "city", "bonus", "att_rdy", "heavy_share", "dirs"]
_W = [1.1911, -0.275, -0.3529, 0.0081, 0.7296, 0.8341, -0.6001, 1.1763]
_B = -1.2756
_MEAN = [0.7328, 1.3633, 0.9561, 0.1624, 0.0369, 0.1156, 0.6737, 2.1411]
_STD = [1.6387, 0.3925, 1.2109, 0.3688, 0.1131, 0.2127, 0.3452, 1.4387]


def _ints(seq):
    out = []
    for x in seq:
        try:
            out.append(int(x))
        except Exception:
            pass
    return out


def _nb(pr):
    return _ints(pr.get("nbrs", []))


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
    w = model.get("w", _W) if model else _W
    b = model.get("b", _B) if model else _B
    mean = model.get("mean", _MEAN) if model else _MEAN
    std = model.get("std", _STD) if model else _STD
    try:
        z = b + sum(w[i] * (x[i] - mean[i]) / std[i] for i in range(len(x)))
    except Exception:
        z = _B + sum(_W[i] * (x[i] - _MEAN[i]) / _STD[i] for i in range(len(x)))
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _diplo(api, mem):
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
    if api.t - mem.get("last_pact", -999) < 72:
        return
    pacts = api.pacts or {}
    pending = set()
    for o in list(api.offers_out or []):
        pending.add(o.get("to"))
    n = 0
    for f in api.met:
        if n >= 3:
            break
        if f in pacts or f in pending:
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
    if api.res < 120:
        return
    done = 0
    spent = {}
    for u in api.units:
        if done >= 80:
            break
        if not u.get("old"):
            continue
        if u.get("path") or u.get("state") not in ("ready", "defending", "digging"):
            continue
        if u.get("rdy", 0) < 30 or u.get("str", 0) < 40:
            continue
        rc = api.refit_cost.get(u["type"]) or {}
        ok = api.res - spent.get("res", 0) - rc.get("res", 0) >= 60
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
    my = {}
    for u in api.units:
        if u.get("state") in ("routing", "shaken", "pinned", "digging", "refitting"):
            continue
        my.setdefault(u["prov"], []).append(u)
    pend = mem.setdefault("pend", {})

    for pid, us in my.items():
        pr = api.provs.get(pid)
        if not pr or pr.get("owner") != "me":
            continue
        ready = [u for u in us
                 if u.get("str", 0) >= 70 and u.get("rdy", 0) >= 70
                 and not u.get("path") and not u.get("dry")]
        if not ready:
            continue
        n_art = sum(1 for u in ready if u.get("type") in ("art", "rkt"))

        for tg in _nb(pr):
            tp = api.provs.get(tg)
            if not tp or tp.get("owner") != "enemy":
                continue
            es = api.enemy.get(tg)
            if not es:
                continue
            fort = tp.get("fort", 0) or 0
            if (tp.get("elev", 0) or 0) > (pr.get("elev", 0) or 0):
                continue
            if fort >= 1 and n_art < 3:
                continue
            if fort >= 2 and n_art < 6:
                continue
            if fort >= 3 and n_art < 10:
                continue
            ehp = es.get("str", 0)
            key = "%d_%d" % (pid, tg)
            prepared = [u for u in ready if u.get("plan") == tg]

            if not prepared:
                strength = sum(u.get("str", 0) for u in ready)
                if strength < max(350, 2.5 * ehp):
                    continue
                api.cmd("prepare @P%d P%d" % (pid, tg))
                pend[key] = api.t
                return

            A = float(sum(u.get("str", 0) for u in prepared))
            if A < max(300, 1.5 * ehp):
                continue
            p = _p_take(api, A, ehp, tp, prepared)
            waited = api.t - pend.get(key, api.t)
            go = (p >= 0.5) or (waited >= 36 and p >= 0.35) or (waited >= 72 and p >= 0.25)
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
```

```letters
to sahelia: Thank you for keeping our pact. Iberia will keep it too and strike none of your provinces. Let us both grow elsewhere.
```