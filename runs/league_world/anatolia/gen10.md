**Reasoning**

The review shows three problems. Upkeep consumed almost all income (569k of 620k res earned), mostly from about 2,500 infantry at 0.09 res/day each. That starved discoveries, which is why ships and aircraft never appeared and dreadnoughts never started. Second, the research loop kept retrying lines that need rubber (10,298 refusals), because the stock check ignored coal and rubber. Third, engineers re-issued `fortify` about 93k times. Assaults also mostly failed (2 of 111), so I keep the attack logic and only trim the army's growth.

Changes: cap army size per owned province and stop recruiting when net income is thin, which frees res for discoveries. Check every strategic resource before starting research, and remember refused orders for 96 hours. Throttle engineer orders to once per 96 hours per unit. The discovery and research logic otherwise stays as it was.

```python
RESEARCH = ["logistics", "conscription", "mining", "farming", "industry", "medicine",
            "drill", "fieldworks", "discipline", "staffwork", "mot.mobility", "cav.mobility",
            "inf.protection", "mec.protection", "art.weapons", "atg.weapons", "inf.weapons",
            "arm.weapons", "arm.protection", "art.protection"]
DISC = ["iron_working", "horse_riding", "siege_engines", "roads", "masonry", "galleys",
        "pikes_crossbows", "stirrup", "hillmen", "trebuchet", "crop_rotation", "castles",
        "sailing", "banking", "gunpowder", "matchlock", "grenadiers", "dragoons",
        "steam_power", "rifling", "steel_guns", "field_engineering", "railways", "navigation",
        "ironclads", "combustion", "machine_guns", "tanks", "flight", "heavy_artillery",
        "anti_tank_guns", "ships_of_the_line", "submarines", "bombers", "dreadnoughts",
        "mechanisation", "heavy_armour", "rocket_artillery", "assault_rifles", "jet_engines",
        "carriers", "rocketry", "satellites", "ballistic_missiles", "guided_weapons",
        "composite_armour"]
ARMOUR = ("arm", "hvt", "mec")
EXPANDERS = ("cav", "mot", "inf", "mtn")
TDEF = (("plain", 1.0), ("forest", 1.25), ("hill", 1.5), ("mountain", 2.0))
NO_FRONT = ("rec", "eng")
ARMY_PER_PROV = 40
BAD_RETRY = 96


def _ids(us):
    return ",".join(str(u["id"]) for u in us)


def _counts(api):
    c = {}
    for u in api.units:
        c[u["type"]] = c.get(u["type"], 0) + 1
    return c


def _enemy_armour(api):
    n = 0
    for p, e in api.enemy.items():
        ty = e.get("types")
        if isinstance(ty, dict):
            for k, v in ty.items():
                if k in ARMOUR:
                    n += v
        elif isinstance(ty, (list, tuple)):
            n += sum(1 for k in ty if k in ARMOUR)
        elif isinstance(ty, str):
            n += sum(1 for k in ARMOUR if k in ty)
    return n


def _afford(uc, res, mp, st, reserve):
    if not uc:
        return False
    if res < (uc.get("res", 0) or 0) + reserve:
        return False
    if mp < (uc.get("mp", 0) or 0):
        return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < (uc.get(k, 0) or 0):
            return False
    return True


def _tdef(terr):
    s = str(terr)
    for k, v in TDEF:
        if s.startswith(k):
            return v
    return 1.0


def _p_take(api, os_, es, tq, bonus, rdy, heavy, dirs):
    mdl = api.model or {}
    if "w" not in mdl or "features" not in mdl:
        return None
    vals = {
        "log_ratio": math.log((os_ + 1.0) / (es + 1.0)),
        "terrain_dfn": _tdef(tq.get("terrain")),
        "fort": float(tq.get("fort") or 0),
        "city": 1.0 if tq.get("city") else 0.0,
        "bonus": bonus / 100.0,
        "att_rdy": rdy / 100.0,
        "heavy_share": heavy,
        "dirs": float(dirs),
    }
    z = mdl["b"]
    for i, n in enumerate(mdl["features"]):
        if n in vals:
            z += mdl["w"][i] * (vals[n] - mdl["mean"][i]) / mdl["std"][i]
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _eval(api, q, attackers):
    if not attackers:
        return None
    e = api.enemy.get(q)
    tq = api.provs.get(q)
    if not e or not tq:
        return None
    es = float(e.get("str") or 0)
    os_ = sum((u.get("str") or 0) * (u.get("rdy") or 0) / 100.0 for u in attackers)
    rdy = sum((u.get("rdy") or 0) for u in attackers) / float(len(attackers))
    bonus = max((u.get("bonus") or 0) for u in attackers)
    heavy = sum(1 for u in attackers if u["type"] in ("art", "eng", "arm")) / float(len(attackers))
    dirs = len(set(u["prov"] for u in attackers))
    fort = float(tq.get("fort") or 0)
    arts = sum(1 for u in attackers if u["type"] == "art")
    p = _p_take(api, os_, es, tq, bonus, rdy, heavy, dirs)
    if p is None:
        z = 0.9 * math.log((os_ + 1.0) / (es + 1.0)) - 1.5 - 0.8 * fort
        p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
    if fort >= 2 and arts < 3:
        p *= 0.4
    return p, os_, es, arts


def _diplo(api, m):
    # Accept incoming pacts as a safety measure. Do not offer pacts ourselves.
    for o in list(api.offers_in):
        if o.get("kind") == "pact":
            try:
                api.cmd("accept %s" % o["id"])
            except Exception:
                pass


def _discover(api, m):
    # Discoveries unlock the units and models that the ancient kinds cannot reach.
    if api.income <= 0 or len(api.research) >= 2:
        return
    bad = m.setdefault("bad", {})
    tree = api.tree or {}
    for d in DISC:
        if api.t - bad.get("d:" + d, -999) < BAD_RETRY:
            continue
        t = tree.get(d)
        if not t or t.get("status") != "open":
            continue
        need = (t.get("res_now") or 0) + 100
        if api.res < need:
            continue
        r = api.cmd("research %s" % d)
        if r.startswith("ok"):
            return
        bad["d:" + d] = api.t


def _research(api, m):
    if api.income <= 0 or len(api.research) >= 2:
        return
    bad = m.setdefault("bad", {})
    active = set(r[0] for r in api.research)
    for line in RESEARCH:
        if line in active or api.t - bad.get("r:" + line, -999) < BAD_RETRY:
            continue
        t = api.tech.get(line)
        if not t or t.get("status") != "open":
            continue
        cost = t.get("cost")
        if not cost:
            continue
        ok = True
        for k in ("res", "steel", "oil", "rare", "coal", "rubber"):
            need = cost.get(k, 0) or 0
            if k == "res":
                need += 150
            if need and api.stock.get(k, 0) < need:
                ok = False
                break
        if not ok:
            continue
        r = api.cmd("research %s" % line)
        if r.startswith("ok"):
            return
        bad["r:" + line] = api.t


def _economy(api, m):
    # Spend idle res on land improvement: build infrastructure where steel allows,
    # develop where coal allows. Richest provinces first (api.economy is sorted).
    if api.t - m.get("last_eco", -99) < 6:
        return
    eco = api.economy or {}
    provs = eco.get("provs") or []
    st = api.stock
    done = False
    if api.res >= 500 and st.get("steel", 0) >= 12:
        for p in provs:
            inf = p.get("infra", 0) or 0
            if inf >= 3:
                continue
            if st.get("steel", 0) < 6 * (inf + 1):
                continue
            if api.cmd("build P%d" % p["prov"]).startswith("ok"):
                done = True
                break
    if api.res >= 700 and st.get("coal", 0) >= 16:
        for p in provs:
            dev = p.get("dev", 0) or 0
            if dev >= 6 or not ((p.get("room", 0) or 0) > 0):
                continue
            if st.get("coal", 0) < 8 * (dev + 1):
                continue
            if api.cmd("develop P%d" % p["prov"]).startswith("ok"):
                done = True
                break
    if done:
        m["last_eco"] = api.t


def _recruit(api, m):
    if api.t - m.get("last_rec", -99) < 1:
        return
    bud = api.budget or {}
    net = bud.get("net", 0) or 0
    dl = bud.get("days_left")
    if net < 0 and dl is not None and dl < 40:
        return
    # Upkeep was the purse killer: keep the army within a size the income carries.
    own = sum(1 for p in api.provs.values() if p.get("owner") == "me")
    cap = ARMY_PER_PROV * max(1, own)
    if len(api.units) >= cap and (net < 60 or api.res < 800):
        return
    if net < 10 and api.res < 500:
        return
    can = set(api.can_raise or [])
    c = _counts(api)
    nb = len(api.neutral_border)
    armour = _enemy_armour(api)
    exp_want = min(30, 8 + nb // 2)
    res = api.res
    mp = api.mp
    st = dict(api.stock)
    done = 0
    for _ in range(8):
        inf_n = sum(c.get(k, 0) for k in ("inf", "mtn", "mil", "grn"))
        exp_n = c.get("cav", 0) + c.get("mot", 0)
        rich = st.get("steel", 0) >= 120 and st.get("oil", 0) >= 60
        if c.get("rec", 0) < 3 and api.unexplored:
            choice = "rec"
        elif nb and exp_n < exp_want:
            if c.get("cav", 0) < 16 or st.get("oil", 0) < 40:
                choice = "cav"
            else:
                choice = "mot"
        elif c.get("eng", 0) < max(2, inf_n // 10):
            choice = "eng"
        elif armour > 0 and c.get("atg", 0) < max(2, inf_n // 8):
            choice = "atg"
        elif c.get("art", 0) < max(6, inf_n // 4):
            choice = "art"
        elif rich and c.get("mec", 0) < max(4, inf_n // 4):
            choice = "mec"
        elif armour > 0 and c.get("arm", 0) < max(2, inf_n // 8):
            choice = "arm"
        elif c.get("grn", 0) < max(2, inf_n // 6):
            choice = "grn"
        else:
            choice = "inf"
        if choice not in can:
            choice = "inf"
        uc = api.unit_costs.get(choice)
        if not _afford(uc, res, mp, st, 250):
            if choice != "inf" and _afford(api.unit_costs.get("inf"), res, mp, st, 250):
                choice = "inf"
                uc = api.unit_costs.get("inf")
            else:
                break
        if len(api.units) + done >= cap and choice in ("inf", "mil", "mtn", "grn"):
            break
        if not api.cmd("recruit %s P%d" % (choice, api.capital)).startswith("ok"):
            break
        c[choice] = c.get(choice, 0) + 1
        res -= (uc.get("res", 0) or 0)
        mp -= (uc.get("mp", 0) or 0)
        for k in ("steel", "oil", "rare"):
            st[k] = st.get(k, 0) - (uc.get(k, 0) or 0)
        done += 1
    if done:
        m["last_rec"] = api.t


def _refit(api, m):
    # Bring units on an outdated model up to date, but only in the rear and with spare res.
    if not api.old_units or api.t - m.get("last_refit", -99) < 12:
        return
    border = api.border
    rc = api.refit_cost or {}
    cand = [u for u in api.units if u.get("old") and u.get("state") == "ready"
            and not u.get("path") and u["prov"] not in border
            and (u.get("str") or 0) >= 40 and not u.get("dry")]
    if not cand:
        return
    take = cand[:20]
    need_res = 0
    st = dict(api.stock)
    for u in take:
        cst = rc.get(u["type"]) or {}
        need_res += cst.get("res", 0) or 0
        for k in ("steel", "oil", "rare"):
            st[k] = st.get(k, 0) - (cst.get(k, 0) or 0)
    if api.res < need_res + 300 or min(st.get("steel", 0), st.get("oil", 0), st.get("rare", 0)) < 0:
        return
    if api.cmd("refit %s" % _ids(take)).startswith("ok"):
        m["last_refit"] = api.t


def _deploy(api, m):
    units = api.units
    border = api.border
    scouts = [u for u in units if u["type"] == "rec" and not u.get("explore")
              and not u.get("path")]
    if scouts and api.unexplored:
        api.cmd("explore %s" % _ids(scouts[:3]))
    nb = list(api.neutral_border)
    if nb:
        want = min(24, len(nb) + 6)
        cur = [u for u in units if u.get("expand")]
        if len(cur) < want:
            cand = [u for u in units if u["type"] in EXPANDERS
                    and not u.get("expand") and not u.get("explore")
                    and not u.get("path") and u.get("state") == "ready"
                    and (u.get("str") or 0) >= 40
                    and u.get("plan", -1) in (-1, None)
                    and (not u.get("front") or u["prov"] not in border)]
            cand.sort(key=lambda u: (0 if u["type"] == "cav" else 1, -(u.get("str") or 0)))
            pick = cand[: want - len(cur)]
            if pick:
                api.cmd("expand %s" % _ids(pick))
    idle = [u for u in units if not u.get("path") and not u.get("front")
            and not u.get("expand") and not u.get("explore")
            and u["type"] not in NO_FRONT
            and u.get("state") in ("ready", "refitting")
            and u.get("plan", -1) in (-1, None)]
    if nb:
        idle = [u for u in idle if u["type"] not in EXPANDERS]
    if idle:
        api.cmd("front " + _ids(idle))


def _engineers(api, m):
    # Orders are throttled: one per engineer per 96 h (the review showed ~93k fortify repeats).
    border = api.border
    ft = m.setdefault("fort_t", {})
    if len(ft) > 3000:
        ft.clear()
    for u in api.units:
        if u["type"] != "eng" or u.get("path") or u.get("state") == "digging":
            continue
        uid = str(u["id"])
        if api.t - ft.get(uid, -999) < BAD_RETRY:
            continue
        if u["prov"] in border:
            if (api.provs.get(u["prov"], {}).get("fort") or 0) < 3:
                api.cmd("fortify %d" % u["id"])
                ft[uid] = api.t
        else:
            best = None
            for pid in border:
                f = api.provs.get(pid, {}).get("fort") or 0
                if f >= 3:
                    continue
                if best is None or f < best[0]:
                    best = (f, pid)
            if best:
                api.cmd("move %d P%d" % (u["id"], best[1]))
                ft[uid] = api.t


def _attack(api, m):
    t = api.t
    prep = m.setdefault("prep", {})
    units = api.units
    pacts = api.pacts or {}
    for key in list(prep.keys()):
        tgt = int(key)
        waited = t - prep[key]
        pl = [u for u in units if u.get("plan") == tgt]
        if not pl:
            if waited > 2:
                del prep[key]
            continue
        ev = _eval(api, tgt, pl)
        if ev is None:
            continue
        p = ev[0]
        mean_rdy = sum((u.get("rdy") or 0) for u in pl) / float(len(pl))
        bonus = max((u.get("bonus") or 0) for u in pl)
        if waited >= 6 and p >= 0.6 and len(pl) >= 6 and mean_rdy >= 65 and (bonus >= 20 or waited >= 12):
            api.cmd("move %s P%d" % (_ids(pl), tgt))
            del prep[key]
        elif waited >= 30 or (p < 0.45 and waited >= 6) or mean_rdy < 45:
            api.cmd("hold %s" % _ids(pl))
            del prep[key]
    if len(prep) >= 2:
        return
    avail = {}
    for u in units:
        if u["type"] in NO_FRONT or u.get("expand") or u.get("explore") or u.get("path"):
            continue
        if u.get("plan", -1) not in (-1, None):
            continue
        if (u.get("str") or 0) < 60 or (u.get("rdy") or 0) < 65:
            continue
        if u.get("state") != "ready" or u.get("dry"):
            continue
        avail.setdefault(u["prov"], []).append(u)
    best = None
    for pid in list(api.border.keys()):
        p0 = api.provs.get(pid)
        if not p0:
            continue
        for q in p0.get("nbrs", []):
            if str(q) in prep:
                continue
            tq = api.provs.get(q)
            if not tq or tq.get("owner") != "enemy":
                continue
            if api.owner_name.get(q) in pacts:
                continue
            cand = []
            seen = set()
            for r in tq.get("nbrs", []):
                for u in avail.get(r, []):
                    if u["id"] not in seen:
                        seen.add(u["id"])
                        cand.append(u)
            if len(cand) < 6:
                continue
            fort = tq.get("fort") or 0
            arts = sum(1 for u in cand if u["type"] == "art")
            if fort >= 3 and arts < 4:
                continue
            ev = _eval(api, q, cand)
            if ev is None:
                continue
            p = ev[0]
            if p < 0.6:
                continue
            if best is None or p > best[0]:
                best = (p, q, cand)
    if best:
        _, q, cand = best
        if api.cmd("prepare %s P%d" % (_ids(cand), q)).startswith("ok"):
            prep[str(q)] = t


def tick(api):
    m = api.mem
    m["n"] = m.get("n", 0) + 1
    for fn in (_diplo, _discover, _research, _economy, _recruit, _refit, _deploy, _engineers, _attack):
        try:
            fn(api, m)
        except Exception:
            pass
```

```feedback
Upkeep dominated my purse (about 569k of 620k res earned). Per-unit upkeep, and a budget view of how much army the income carries, would help. Research refusals for rubber repeated 10k times because the stock check ignored coal and rubber; a machine-readable refusal reason would prevent this. Engineer fortify orders repeated 93k times with no state change; a 'already fortified' reply would help. api.budget is useful. A per-faction history of discovery prices would make the discovery order easier to plan.
```

REVIEW: standard