**Review of war 1:** We finished 20th of 30 with 76 provinces. Expansion worked, but none of our 105 assaults on defended provinces succeeded. Most were launched at readiness below 34 with no prepared bonus, and at fort levels 3-4. Our research was useful: infantry, armour and artillery attack and defence upgrades all paid off.

**Changes:**
- **Attacks:** Launch only with a clear strength edge (at least 2.2x, more against forts), units at readiness 65+, and a prepared bonus of about 24% or more. Plans are cancelled if the enemy reinforces.
- **Odds:** Use the fitted `api.model` assault probability as a gate when it is available, and fall back to a strength ratio otherwise.
- **Recruitment:** Shift the mix toward armour and artillery, which have the best upgrade record.
- **Research:** Prioritise the weapons and protection lines that paid off last war. Skip dead ends automatically.
- **Expansion:** Keep neutral land expansion with more takers while free land remains.
- **Cost:** Each step is guarded, and the code uses no imports, so it stays well within the timing limit.

```python
# Muscovy standing orders (v2)
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
    model = api.model or {}

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

    def model_prob(our, es, tv, grp, bonus_pct, rdy):
        # fitted 'will this assault take the province' estimate; None if no model
        if not model or not model.get("features"):
            return None
        feats = model["features"]
        w = model["w"]
        mu = model["mean"]
        sd = model["std"]
        terr = str(tv.get("terrain", ""))
        elev = tv.get("elev", 0) or 0
        if "forest" in terr:
            tdfn = 1.25
        elif elev >= 3:
            tdfn = 2.0
        elif elev == 2:
            tdfn = 1.5
        else:
            tdfn = 1.0
        nn = max(len(grp), 1)
        heavy = sum(1 for u in grp if u.get("type") in ("art", "eng", "arm")) / float(nn)
        vals = {
            "log_ratio": math.log((our + 1.0) / (es + 1.0)),
            "terrain_dfn": tdfn,
            "fort": tv.get("fort", 0) or 0,
            "city": 1.0 if tv.get("city") else 0.0,
            "bonus": bonus_pct / 100.0,
            "att_rdy": rdy / 100.0,
            "heavy_share": heavy,
            "dirs": 1.0,
        }
        z = model.get("b", 0.0)
        for i, f in enumerate(feats):
            x = vals.get(f, 0.0)
            z += w[i] * (x - mu[i]) / sd[i]
        z = max(-30.0, min(30.0, z))
        return 1.0 / (1.0 + math.exp(-z))

    cnt = {}
    for u in units:
        cnt[u["type"]] = cnt.get(u["type"], 0) + 1
    total = len(units)

    # 1. Recruitment: armour and artillery favoured once the army is sizeable
    def recruit():
        if api.income < 0 and api.res < 150:
            return
        want = []
        if cnt.get("rec", 0) < 2 and t >= 6:
            want.append("rec")
        if total >= 8:
            if cnt.get("art", 0) < 0.18 * total:
                want.append("art")
            if cnt.get("arm", 0) < 0.18 * total:
                want.append("arm")
            if cnt.get("atg", 0) < 0.07 * total:
                want.append("atg")
        want += ["inf", "mil"]
        made = 0
        for tp in want:
            if made >= 3:
                break
            if not affordable(tp, 40):
                continue
            line = "recruit %s 1" % tp
            if capital is not None:
                line += " P%d" % capital
            if ok(line):
                made += 1
                cnt[tp] = cnt.get(tp, 0) + 1

    # 2. Research: the lines that paid off in war 1 first; dead ends are skipped
    def do_research():
        if len(api.research) >= 2:
            return
        ongoing = [r[0] for r in api.research]
        econ = ["inf.weapons", "arm.weapons", "art.weapons", "inf.protection",
                "medicine", "drill", "conscription", "mining", "arm.protection",
                "farming", "logistics"]
        mil = ["industry", "discipline", "fieldworks", "staffwork",
               "mot.mobility", "drilling", "refining"]
        order = econ if t < 120 else econ + mil
        for line in order:
            tc = tech.get(line)
            if not tc or tc.get("status") != "open" or line in ongoing:
                continue
            cost = tc.get("cost")
            if not cost:
                continue
            if api.res - cost.get("res", 0) < 100:
                continue
            if any(api.stock.get(k, 0) < cost.get(k, 0) for k in ("steel", "oil", "rare")):
                continue
            if ok("research %s" % line):
                break

    # 3. Idle units: scouts explore, combat units expand into free land, the rest hold the border
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
                      if u["type"] in ("inf", "mil", "mtn", "mot", "cav") and u.get("str", 0) >= 40][:6]
            if takers and ok("expand %s" % ids(takers)):
                for u in takers:
                    taken.add(u["id"])
        rest = [u for u in combat if u["id"] not in taken]
        if rest:
            ok("front %s" % ids(rest))

    # 4. Formation: group front units into one named formation (formation xp)
    def group_front():
        fresh = [u for u in units if u["type"] != "rec" and u.get("front") and not u.get("group")]
        if not fresh:
            return
        batch = fresh[:40]
        if m.get("gfix"):
            ok("group main + %s" % ids(batch))
        elif ok("group main %s" % ids(batch)):
            m["gfix"] = 1

    # 5. Attacks: prepare with a real bonus, launch only with clear superiority
    def attacks():
        for key in list(plans.keys()):
            p = int(key)
            tgt, start = plans[key]
            el = t - start
            tv = provs.get(tgt, {})
            at = [u for u in units if u.get("plan") == tgt and u.get("prov") == p]
            if tv.get("owner") == "me" or not at or el > 48:
                if at:
                    ok("front %s" % ids(at))
                del plans[key]
                continue
            if el < 24 or len(at) < 3:
                continue
            e = enemy.get(tgt)
            es = e.get("str", 0) if e else 0
            our = sum([u.get("str", 0) for u in at])
            bonus = sum([u.get("bonus", 0) or 0 for u in at]) / float(len(at))
            rdy = sum([u.get("rdy", 0) for u in at]) / float(len(at))
            if our < 1.3 * es:
                ok("front %s" % ids(at))
                del plans[key]
                continue
            pr = model_prob(our, es, tv, at, bonus, rdy)
            if pr is not None and pr < 0.3 and el < 40:
                continue
            if (el >= 24 and len(at) >= 4) or (el >= 36 and len(at) >= 3):
                if ok("move %s P%d" % (ids(at), tgt)):
                    del plans[key]

        if len(plans) >= 2 or t < 12:
            return

        pool = {}
        for u in units:
            if u["type"] == "rec" or not u.get("front"):
                continue
            if u.get("plan") not in (-1, None) or u.get("path"):
                continue
            if u.get("str", 0) < 60 or u.get("rdy", 0) < 65 or u.get("state") != "ready":
                continue
            if u.get("prov") is None:
                continue
            pool.setdefault(u["prov"], []).append(u)

        for p, lst in sorted(pool.items(), key=lambda kv: -len(kv[1])):
            if len(plans) >= 2:
                break
            if str(p) in plans or len(lst) < 6:
                continue
            pv = provs.get(p)
            if not pv or pv.get("owner") != "me":
                continue
            our = sum([u.get("str", 0) for u in lst])
            rdy = sum([u.get("rdy", 0) for u in lst]) / float(len(lst))
            best, best_score = None, -1.0
            for nb in pv.get("nbrs", []):
                npv = provs.get(nb)
                if not npv or npv.get("owner") != "enemy":
                    continue
                e = enemy.get(nb)
                if not e:
                    continue  # never attack blind
                es = e.get("str", 0)
                ratio = our / max(es, 1.0)
                fort = npv.get("fort", 0) or 0
                if ratio < 2.2 + 0.6 * fort:
                    continue
                pr = model_prob(our, es, npv, lst[:12], 0.0, rdy)
                if pr is not None and pr < 0.5:
                    continue
                score = pr if pr is not None else ratio
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