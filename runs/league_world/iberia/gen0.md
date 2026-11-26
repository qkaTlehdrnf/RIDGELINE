**Reasoning (Iberia):** Iberia gets +10% attack and pays 5% more for units, so the policy leans on attacks that are prepared and concentrated, not on a static line. Each tick it does four things, each in its own try block so one failure doesn't drop the others:

1. **Research:** keeps two projects running, preferring economy (farming, conscription) and then unit protection and weapons. It holds a 150 res reserve.
2. **Recruit:** one order per tick from the capital. Infantry is the base. Scouts, artillery, armour and anti-tank guns are added as the army grows and steel and oil allow. It respects upkeep and manpower.
3. **Orders:** idle units expand into neutral land, or join the front when no land is reachable. Armour and artillery go straight to the front. Scouts explore. Weak units fall back to the capital to refit.
4. **Attacks:** only against known enemy provinces next to my own, and only when my ready strength is at least twice the estimate (more if the estimate is uncertain). Units prepare, then advance once the plan bonus reaches 25% or after 18 hours. Each advance is grouped for formation experience.

Nothing here has been run against the engine, so the parameters are guesses to tune after the first trials.

```python
PREF_TECH = [
    "farming", "conscription", "inf.protection", "inf.weapons",
    "arm.weapons", "mining", "logistics", "medicine", "drill",
    "mot.mobility", "discipline", "art.weapons", "industry",
    "arm.protection", "mil.protection", "refining", "drilling",
    "fieldworks", "staffwork",
]


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
            reserve = 150 if k == "res" else 0
            have = api.stock.get(k, 0) - spent.get(k, 0)
            if have < v + reserve:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research " + line)
        if str(r).startswith("ok"):
            slots -= 1
            for k, v in cost.items():
                spent[k] = spent.get(k, 0) + v


def _recruit(api, mem):
    units = api.units
    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    total = len(units)
    if api.income < 0 and total > 12:
        return
    steel_ok = api.stock.get("steel", 0) >= 30 and api.income_by.get("steel", 0) > 0
    oil_ok = api.stock.get("oil", 0) >= 10 and api.income_by.get("oil", 0) > 0

    pick = "inf"
    if cnt.get("rec", 0) < 2 and total >= 4:
        pick = "rec"
    elif total >= 10 and cnt.get("art", 0) < total * 0.12 and steel_ok:
        pick = "art"
    elif total >= 10 and cnt.get("arm", 0) < total * 0.15 and steel_ok and oil_ok:
        pick = "arm"
    elif total >= 8 and cnt.get("atg", 0) < total * 0.06 and steel_ok:
        pick = "atg"

    uc = api.unit_costs.get(pick)
    if not uc:
        return
    n = 2 if api.res > 400 else 1
    if api.res < uc.get("res", 0) * n + 80:
        return
    if api.mp < uc.get("mp", 0) * n:
        return
    for k in ("steel", "oil", "rare"):
        if api.stock.get(k, 0) < uc.get(k, 0) * n:
            return
    api.cmd("recruit %s %d P%d" % (pick, n, api.capital))


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
        if t != "rec" and u.get("str", 100) < 35:
            if u.get("prov") != api.capital:
                api.cmd("move %d P%d" % (uid, api.capital))
            continue
        if t == "rec":
            api.cmd("explore %d" % uid)
            continue
        if t in ("arm", "hvt", "art", "rkt", "atg") or not neutral:
            api.cmd("front %d" % uid)
            continue
        r = api.cmd("expand %d" % uid)
        if not str(r).startswith("ok"):
            api.cmd("front %d" % uid)


def _attack(api, mem):
    my = {}
    for u in api.units:
        if u.get("state") in ("routing", "shaken"):
            continue
        my.setdefault(u["prov"], []).append(u)
    pend = mem.setdefault("pend", {})

    for pid, us in my.items():
        pr = api.provs.get(pid)
        if not pr or pr.get("owner") != "me":
            continue
        ready = [u for u in us
                 if u.get("str", 0) >= 50 and u.get("rdy", 0) >= 50
                 and not u.get("path") and not u.get("dry")]
        if not ready:
            continue
        strength = sum(u.get("str", 0) for u in ready)

        for tg in _nb(pr):
            tp = api.provs.get(tg)
            if not tp or tp.get("owner") != "enemy":
                continue
            es = api.enemy.get(tg)
            if not es:
                continue
            ehp = es.get("str", 0)
            margin = 2.0 if es.get("exact", False) else 2.6
            if strength < max(150, margin * ehp):
                continue
            key = "%d_%d" % (pid, tg)
            prepared = [u for u in ready if u.get("plan") == tg]
            if not prepared:
                api.cmd("prepare @P%d P%d" % (pid, tg))
                pend[key] = api.t
                break
            bonus = max(u.get("bonus", 0) for u in prepared)
            waited = api.t - pend.get(key, api.t)
            if bonus >= 25 or waited >= 18:
                ids = [u["id"] for u in prepared]
                sel = ",".join(str(i) for i in ids)
                api.cmd("group a%d %s" % (api.t, sel))
                api.cmd("move %s P%d" % (sel, tg))
                pend.pop(key, None)
                return


def tick(api):
    mem = api.mem
    mem["calls"] = mem.get("calls", 0) + 1
    for f in (_research, _recruit, _orders, _attack):
        try:
            f(api, mem)
        except Exception:
            pass
```