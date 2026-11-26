Muscovy gets a simple, robust loop. Early on it builds economy and scouts: idle infantry expand into free neutral land, and recruits go to the border on the front order. Research starts with farming, conscription and infantry upgrades, then shifts to military lines after tick 240. Artillery, armour and anti-tank guns are capped at shares of the army and only recruited when steel and oil are in stock. Attacks are sized by strength: a group of at least four front units at strength 60+ prepares against an adjacent enemy province only when its total strength clearly beats what is visible there, then launches after about 12 hours of preparation. Each section runs in its own try block, so one failing call cannot stop the others. Commands that fail are ignored, and stale plans are cancelled after 36 hours.

```python
# Muscovy standing orders
def tick(api):
    m = api.mem
    plans = m.setdefault("plans", {})   # str(origin prov) -> [target, start tick]
    m.setdefault("gfix", 0)
    t = api.t
    units = api.units
    provs = api.provs
    enemy = api.enemy
    tech = api.tech
    capital = api.capital

    def ok(line):
        try:
            return str(api.cmd(line)).startswith("ok")
        except Exception:
            return False

    def ids(lst):
        return ",".join([str(u["id"]) for u in lst])

    def affordable(tp, reserve):
        c = api.unit_costs.get(tp)
        if not c:
            return False
        if api.res - c.get("res", 0) < reserve:
            return False
        if api.mp < c.get("mp", 0):
            return False
        for k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) < c.get(k, 0):
                return False
        return True

    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    total = len(units)

    # 1. Recruitment
    def recruit():
        if api.income < 0 and api.res < 150:
            return
        want = []
        if cnt.get("rec", 0) < 2 and t >= 6:
            want.append("rec")
        if total >= 8:
            if cnt.get("art", 0) < 0.15 * total:
                want.append("art")
            if cnt.get("arm", 0) < 0.15 * total:
                want.append("arm")
            if cnt.get("atg", 0) < 0.06 * total:
                want.append("atg")
        want += ["inf", "mil"]
        made = 0
        for tp in want:
            if made >= 2:
                break
            if not affordable(tp, 40):
                continue
            line = "recruit %s 1" % tp
            if capital is not None:
                line += " P%d" % capital
            if ok(line):
                made += 1
                cnt[tp] = cnt.get(tp, 0) + 1

    # 2. Research (one start per tick, max two projects)
    def do_research():
        if len(api.research) >= 2:
            return
        ongoing = [r[0] for r in api.research]
        econ = ["farming", "conscription", "inf.weapons", "inf.protection", "mining",
                "drill", "medicine", "logistics"]
        mil = ["arm.weapons", "art.weapons", "arm.protection", "industry",
               "discipline", "mot.mobility", "fieldworks", "staffwork", "drilling", "refining"]
        order = econ if t < 240 else econ + mil
        for line in order:
            tc = tech.get(line)
            if not tc or tc.get("status") != "open" or line in ongoing:
                continue
            cost = tc.get("cost")
            if not cost:
                continue
            if api.res - cost.get("res", 0) < 120:
                continue
            if any(api.stock.get(k, 0) < cost.get(k, 0) for k in ("steel", "oil", "rare")):
                continue
            if ok("research %s" % line):
                break

    # 3. Idle units: scouts explore, infantry expand, the rest hold the border
    def orders_idle():
        idle = []
        for u in units:
            if (not u.get("path")) and (not u.get("front")) and (not u.get("expand")) \
               and (not u.get("explore")) and u.get("plan") in (-1, None) \
               and u.get("state") in ("ready", "refitting"):
                idle.append(u)
        recs = [u for u in idle if u["type"] == "rec"]
        if recs:
            ok("explore %s" % ids(recs))
        combat = [u for u in idle if u["type"] != "rec"]
        taken = set()
        if api.neutral_border and combat:
            takers = [u for u in combat
                      if u["type"] in ("inf", "mil", "mtn", "mot", "cav") and u.get("str", 0) >= 50][:3]
            if takers and ok("expand %s" % ids(takers)):
                for u in takers:
                    taken.add(u["id"])
        rest = [u for u in combat if u["id"] not in taken]
        if rest:
            ok("front %s" % ids(rest))

    # 4. Formation: group all front units into one named formation
    def group_front():
        fresh = [u for u in units if u["type"] != "rec" and u.get("front") and not u.get("group")]
        if not fresh:
            return
        batch = fresh[:40]
        if m.get("gfix"):
            ok("group main + %s" % ids(batch))
        elif ok("group main %s" % ids(batch)):
            m["gfix"] = 1

    # 5. Attacks: manage plans, then start new ones where we have clear superiority
    def attacks():
        for key in list(plans.keys()):
            p = int(key)
            tgt, start = plans[key]
            tv = provs.get(tgt, {})
            at = [u for u in units if u.get("plan") == tgt and u.get("prov") == p]
            if tv.get("owner") == "me" or not at or (t - start) > 36:
                if at:
                    ok("front %s" % ids(at))
                del plans[key]
                continue
            if t - start >= 12 and len(at) >= 3:
                ok("move %s P%d" % (ids(at), tgt))
                del plans[key]
        if len(plans) >= 2 or t < 12:
            return
        pool = {}
        for u in units:
            if u["type"] == "rec" or not u.get("front"):
                continue
            if u.get("plan") not in (-1, None) or u.get("path"):
                continue
            if u.get("str", 0) < 60 or u.get("rdy", 0) < 55 or u.get("state") != "ready":
                continue
            if u.get("prov") is None:
                continue
            pool.setdefault(u["prov"], []).append(u)
        for p, lst in sorted(pool.items(), key=lambda kv: -len(kv[1])):
            if len(plans) >= 2:
                break
            if str(p) in plans or len(lst) < 4:
                continue
            pv = provs.get(p)
            if not pv or pv.get("owner") != "me":
                continue
            our = sum([u.get("str", 0) for u in lst])
            best, best_score = None, -1.0
            for nb in pv.get("nbrs", []):
                npv = provs.get(nb)
                if not npv or npv.get("owner") != "enemy":
                    continue
                e = enemy.get(nb)
                es = e.get("str", 0) if e else 0
                if our < 1.6 * es + 120:
                    continue
                score = our - 1.6 * es
                if score > best_score:
                    best, best_score = nb, score
            if best is None:
                continue
            if ok("prepare %s P%d" % (ids(lst[:12]), best)):
                plans[str(p)] = [best, t]

    for step in (recruit, do_research, orders_idle, group_front, attacks):
        try:
            step()
        except Exception:
            pass

    m["calls"] = m.get("calls", 0) + 1
```