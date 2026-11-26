PREF_TECH = [
    "conscription", "farming", "arm.weapons", "arm.protection",
    "medicine", "logistics", "mining", "art.weapons", "inf.weapons",
    "mot.mobility", "drill", "discipline", "staffwork", "industry",
    "fieldworks", "inf.protection", "mot.weapons", "mot.protection",
    "mil.protection", "refining", "drilling",
]

MIX = {"inf": 0.40, "art": 0.15, "arm": 0.18, "mot": 0.10,
       "atg": 0.07, "eng": 0.05}


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
            reserve = 120 if k == "res" else 0
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
    if api.res < 400:
        return
    border = api.border or {}
    done = 0
    spent = {}
    for u in api.units:
        if done >= 25:
            break
        if not u.get("old"):
            continue
        if u.get("path") or u.get("state") != "ready":
            continue
        if u.get("rdy", 0) < 70 or u.get("str", 0) < 50:
            continue
        if u.get("prov") in border:
            continue
        rc = api.refit_cost.get(u["type"]) or {}
        ok = api.res - spent.get("res", 0) - rc.get("res", 0) >= 150
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
    if api.res - spent.get("res", 0) < uc.get("res", 0) + 120:
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
    picks = 3 if api.res > 400 else 1

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
        if t != "rec" and u.get("str", 100) < 40:
            if u.get("prov") != api.capital:
                api.cmd("move %d P%d" % (uid, api.capital))
            continue
        if t in ("arm", "hvt", "art", "rkt", "atg", "mec") or not neutral:
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
                 if u.get("str", 0) >= 60 and u.get("rdy", 0) >= 60
                 and not u.get("path") and not u.get("dry")]
        if not ready:
            continue
        strength = sum(u.get("str", 0) for u in ready)
        n_art = sum(1 for u in ready if u.get("type") in ("art", "rkt"))

        for tg in _nb(pr):
            tp = api.provs.get(tg)
            if not tp or tp.get("owner") != "enemy":
                continue
            es = api.enemy.get(tg)
            if not es:
                continue
            fort = tp.get("fort", 0) or 0
            if fort >= 3 and n_art < 3:
                continue
            need = 2.5 if es.get("exact", False) else 3.0
            if fort >= 3:
                need = max(need, 3.5)
            ehp = es.get("str", 0)
            if strength < max(250, need * ehp):
                continue
            key = "%d_%d" % (pid, tg)
            prepared = [u for u in ready if u.get("plan") == tg]
            if not prepared:
                api.cmd("prepare @P%d P%d" % (pid, tg))
                pend[key] = api.t
                break
            bonus = max(u.get("bonus", 0) for u in prepared)
            waited = api.t - pend.get(key, api.t)
            if bonus >= 25 or waited >= 12:
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
