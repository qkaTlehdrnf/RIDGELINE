**Review of war 1 (12th of 30, 106 provinces):**

- **Unprepared assaults almost always fail** (0/249 with no plan bonus). Prepared assaults with bonus 1-30% won 10/10. The fix is to attack only from a prepared bonus.
- **Strength ratio and forts matter.** Wins came at ratio 2-5 and against forts ≤3. Forts at level 3-4 were nearly impassable (4/123), so I skip those targets unless artillery is present.
- **Resources sat idle.** The bank ended at 1827 res, 1661 steel and 3420 oil. Recruitment was one type per tick and too conservative, so I now recruit up to 4 units per tick against a target mix, keeping a smaller reserve.
- **Research:** I prioritise attack and protection lines for the armour and infantry that did best, and I keep the 2-project cap. Dead-end lines are skipped automatically through their status.
- **Orders** are kept close to the working version: scouts explore, idle units expand into neutral land, and the rest hold the front.

```python
PREF_TECH = [
    "farming", "conscription", "inf.weapons", "arm.weapons",
    "arm.protection", "inf.protection", "mining", "logistics",
    "medicine", "mot.mobility", "art.weapons", "drill",
    "discipline", "mot.weapons", "mot.protection", "industry",
    "mil.protection", "refining", "drilling", "fieldworks", "staffwork",
]

# target share of army by kind (rec handled separately)
MIX = {"inf": 0.45, "art": 0.12, "arm": 0.15, "mot": 0.08,
       "atg": 0.06, "eng": 0.03}


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
            reserve = 100 if k == "res" else 0
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


def _affordable(api, uc, spent):
    if api.res - spent.get("res", 0) < uc.get("res", 0) + 80:
        return False
    if api.mp - spent.get("mp", 0) < uc.get("mp", 0):
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
    if api.income < 0 and total > 15:
        return

    spent = {}
    picks = 4 if api.res > 500 else 2

    # two scouts early for exploration
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
            if not uc:
                continue
            if t in ("art", "arm", "atg", "mot") and api.stock.get("steel", 0) < 30 and t != "inf":
                continue
            if not _affordable(api, uc, spent):
                continue
            deficit = w * (total + 1) - cnt.get(t, 0)
            if deficit > best_def:
                best_def = deficit
                best = (t, uc)
        if best is None:
            break
        t, uc = best
        r = api.cmd("recruit %s 1 P%d" % (t, api.capital))
        if not str(r).startswith("ok"):
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
        has_art = any(u.get("type") in ("art", "rkt") for u in ready)

        for tg in _nb(pr):
            tp = api.provs.get(tg)
            if not tp or tp.get("owner") != "enemy":
                continue
            es = api.enemy.get(tg)
            if not es:
                continue
            # forts 3+ almost never fall to assault without artillery
            fort = tp.get("fort", 0) or 0
            if fort >= 3 and not has_art:
                continue
            ehp = es.get("str", 0)
            margin = 2.2 if es.get("exact", False) else 2.8
            if strength < max(200, margin * ehp):
                continue
            key = "%d_%d" % (pid, tg)
            prepared = [u for u in ready if u.get("plan") == tg]
            if not prepared:
                api.cmd("prepare @P%d P%d" % (pid, tg))
                pend[key] = api.t
                break
            bonus = max(u.get("bonus", 0) for u in prepared)
            waited = api.t - pend.get(key, api.t)
            # unprepared assaults failed every time; launch only with a bonus
            if bonus >= 20 or waited >= 12:
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