# Muscovy standing orders (v8)
def tick(api):
    m = api.mem
    plans = m.setdefault("plans", {})
    m.setdefault("gfix", 0)
    lo = m.setdefault("last_offer", {})
    t = api.t
    units = api.units
    provs = api.provs
    enemy = api.enemy
    tech = api.tech
    capital = api.capital
    model = api.model or {}
    pacts = api.pacts or {}
    onames = api.owner_name or {}
    stock = api.stock
    depots = api.depots or {}

    def ok(line):
        try:
            return str(api.cmd(line)).startswith("ok")
        except Exception:
            return False

    def ids(lst):
        return ",".join([str(u["id"]) for u in lst])

    def at_peace(prov):
        nm = onames.get(prov)
        return nm is not None and nm in pacts

    def affordable(tp, reserve):
        c = api.unit_costs.get(tp)
        if not c:
            return False
        if api.res - c.get("res", 0) < reserve:
            return False
        if api.mp < c.get("mp", 0):
            return False
        for k in ("steel", "oil", "rare"):
            if stock.get(k, 0) < c.get(k, 0):
                return False
        return True

    def model_prob(our, es, tv, grp, bonus_pct, rdy):
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

    # 0a. Diplomacy: accept pacts and fair trades
    def deals():
        for o in list(api.offers_in or []):
            try:
                kind = o.get("kind")
                if kind == "pact":
                    ok("accept %s" % o["id"])
                elif kind == "trade":
                    give = sum((o.get("they_give") or {}).values())
                    take = sum((o.get("you_give") or {}).values())
                    if give >= 1.2 * take:
                        ok("accept %s" % o["id"])
            except Exception:
                pass

    # 0b. Turn surplus oil/rare/steel into res with factions we have dealt with
    def sell_surplus():
        if t < 36:
            return
        outs = api.offers_out or []
        pending = set([o.get("to") for o in outs])
        sent = 0
        partners = list(pacts.keys()) + [f for f in (api.met or []) if f not in pacts]
        for f in partners:
            if sent >= 2:
                break
            if f in pending:
                continue
            key = "tr:" + f
            if t - lo.get(key, -999) < 24:
                continue
            lo[key] = t
            if stock.get("oil", 0) > 300 and ok("offer %s trade 150 oil for 80 res" % f):
                sent += 1
            elif stock.get("rare", 0) > 200 and ok("offer %s trade 80 rare for 80 res" % f):
                sent += 1
            elif stock.get("steel", 0) > 300 and ok("offer %s trade 100 steel for 80 res" % f):
                sent += 1

    # 1. Recruitment
    def recruit():
        if api.income < 0 and api.res < 120:
            return
        floor = 40 if t < 120 else 70
        want = []
        if cnt.get("rec", 0) < 3 and t >= 6:
            want.append("rec")
        if t < 240 and api.neutral_border and (cnt.get("inf", 0) + cnt.get("mil", 0)) < 40:
            want += ["mil", "inf"]
        if total >= 8:
            if cnt.get("art", 0) < 0.12 * total:
                want.append("art")
            if cnt.get("arm", 0) < 0.15 * total:
                want.append("arm")
            if cnt.get("atg", 0) < 0.06 * total:
                want.append("atg")
            if cnt.get("eng", 0) < 0.05 * total:
                want.append("eng")
            if stock.get("steel", 0) > 300 and stock.get("rare", 0) > 200 and api.res > 150 \
               and cnt.get("hvt", 0) < 0.06 * total:
                want.append("hvt")
        if stock.get("oil", 0) > 300 and cnt.get("mot", 0) < 0.12 * total:
            want.append("mot")
        if api.mp < 150:
            want = [w for w in want if w not in ("inf", "mil")]
        want += ["inf", "mil"]
        made = 0
        for tp in want:
            if made >= 3:
                break
            if not affordable(tp, floor):
                continue
            line = "recruit %s 1" % tp
            if capital is not None:
                line += " P%d" % capital
            if ok(line):
                made += 1
                cnt[tp] = cnt.get(tp, 0) + 1

    # 2. Research
    def do_research():
        if len(api.research) >= 2:
            return
        ongoing = [r[0] for r in api.research]
        order = ["inf.weapons", "medicine", "industry", "arm.weapons", "art.weapons",
                 "inf.protection", "farming", "logistics", "drill", "discipline", "mining",
                 "conscription", "arm.protection", "mot.weapons", "mot.protection",
                 "mot.mobility", "staffwork", "fieldworks", "drilling", "refining"]
        for line in order:
            tc = tech.get(line)
            if not tc or tc.get("status") != "open" or line in ongoing:
                continue
            cost = tc.get("cost")
            if not cost:
                continue
            if api.res - cost.get("res", 0) < 60:
                continue
            if any(stock.get(k, 0) < cost.get(k, 0) for k in ("steel", "oil", "rare")):
                continue
            if ok("research %s" % line):
                break

    # 2b. Refit outdated units in the rear
    def refit_old():
        if t < 24 or not getattr(api, "old_units", 0):
            return
        border = set(api.border.keys()) if api.border else set()
        by = {}
        for u in units:
            if not u.get("old") or u.get("state") != "ready" or u.get("path"):
                continue
            if not u.get("supplied") or u.get("prov") in border:
                continue
            by.setdefault(u["type"], []).append(u)
        for tp, lst in sorted(by.items(), key=lambda kv: -len(kv[1])):
            rc = api.refit_cost.get(tp)
            if not rc:
                continue
            n = min(len(lst), 20)
            if api.res - rc.get("res", 0) * n < 40:
                n = int((api.res - 40) // max(rc.get("res", 1), 1))
                if n < 3:
                    continue
            if any(stock.get(k, 0) < rc.get(k, 0) * n for k in ("steel", "oil", "rare")):
                continue
            if ok("refit %s" % ids(lst[:n])):
                return

    # 3. Idle units
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
                      if u["type"] in ("inf", "mil", "mtn", "mot", "cav", "grn", "mec")
                      and u.get("str", 0) >= 30][:12]
            if takers and ok("expand %s" % ids(takers)):
                for u in takers:
                    taken.add(u["id"])
        rest = [u for u in combat if u["id"] not in taken]
        if rest:
            ok("front %s" % ids(rest))

    # 4. Formation
    def group_front():
        fresh = [u for u in units if u["type"] != "rec" and u.get("front") and not u.get("group")]
        if not fresh:
            return
        batch = fresh[:40]
        if m.get("gfix"):
            ok("group main + %s" % ids(batch))
        elif ok("group main %s" % ids(batch)):
            m["gfix"] = 1

    # 4b. Forward depots: relieve the capital depot's load
    def forward_depot():
        if t < 48 or api.res < 200 or t - lo.get("depot", -999) < 48:
            return
        if len(depots) >= 6:
            return
        best, best_score = None, -99
        for pid, pv in provs.items():
            if pv.get("owner") != "me" or pid in depots:
                continue
            if not pv.get("supplied", True):
                continue
            nbrs = pv.get("nbrs", [])
            near = sum(1 for n in nbrs if provs.get(n, {}).get("owner") == "enemy")
            backed = sum(1 for n in nbrs if provs.get(n, {}).get("owner") == "me")
            score = backed - 2 * near + (2 if pv.get("city") else 0)
            if score > best_score:
                best, best_score = pid, score
        if best is not None:
            lo["depot"] = t
            ok("depot P%d" % best)

    # 5. Attacks
    def attacks():
        for key in list(plans.keys()):
            p = int(key)
            tgt, start = plans[key]
            el = t - start
            tv = provs.get(tgt, {})
            at = [u for u in units if u.get("plan") == tgt and u.get("prov") == p]
            if tv.get("owner") == "me" or at_peace(tgt) or not at or el > 48:
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
            if our < 2.5 * es:
                ok("front %s" % ids(at))
                del plans[key]
                continue
            pr = model_prob(our, es, tv, at, bonus, rdy)
            if pr is not None and pr < 0.6 and el < 40:
                continue
            if (el >= 24 and len(at) >= 8) or (el >= 36 and len(at) >= 5):
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
            if u.get("str", 0) < 60 or u.get("rdy", 0) < 70 or u.get("state") != "ready":
                continue
            if u.get("prov") is None:
                continue
            pool.setdefault(u["prov"], []).append(u)

        for p, lst in sorted(pool.items(), key=lambda kv: -len(kv[1])):
            if len(plans) >= 2:
                break
            if str(p) in plans or len(lst) < 8:
                continue
            pv = provs.get(p)
            if not pv or pv.get("owner") != "me":
                continue
            our = sum([u.get("str", 0) for u in lst])
            rdy = sum([u.get("rdy", 0) for u in lst]) / float(len(lst))
            arts = sum(1 for u in lst if u["type"] == "art")
            best, best_score = None, -1.0
            for nb in pv.get("nbrs", []):
                npv = provs.get(nb)
                if not npv or npv.get("owner") != "enemy":
                    continue
                if at_peace(nb):
                    continue
                e = enemy.get(nb)
                if not e:
                    continue  # never attack blind
                fort = npv.get("fort", 0) or 0
                if fort >= 3:
                    continue
                if fort >= 2 and arts < 0.15 * len(lst):
                    continue
                es = e.get("str", 0)
                ratio = our / max(es, 1.0)
                if ratio < 3.0 + 1.0 * fort:
                    continue
                pr = model_prob(our, es, npv, lst[:12], 0.0, rdy)
                if pr is not None and pr < 0.6:
                    continue
                score = pr if pr is not None else ratio
                if score > best_score:
                    best, best_score = nb, score
            if best is None:
                continue
            if ok("prepare %s P%d" % (ids(lst[:12]), best)):
                plans[str(p)] = [best, t]

    for step in (deals, sell_surplus, recruit, do_research, refit_old,
                 orders_idle, group_front, forward_depot, attacks):
        try:
            step()
        except Exception:
            pass

    m["calls"] = m.get("calls", 0) + 1
