**Reasoning (Haiku 5.5, war 9 review)**

Sarmatia placed 24th of 31 with 55 provinces. The main problems were:

- **No discoveries were ever researched.** The policy only ran upgrade lines, so the faction stayed on ancient inf/mil/rec for the whole war. The 2,000-year tree is now the rule set, so this is the biggest gap.
- **Attacks were too weak.** Assaults at strength ratio under 1 won 0 of 8. Only ratios of 3 or more won. The new policy attacks only at a ratio of about 2.5 or more, scaled by fort level and terrain.
- **Recruitment drained the purse.** Refused recruits and research were common. Recruiting now keeps a reserve and checks upkeep (`budget.net`).
- **Economy was underused.** Infrastructure was never built. Development and infrastructure now run on interior provinces.
- **Diplomacy froze the map.** Long pacts with neighbours were rejected, which left wars short and unresolved. Short pacts with neighbours are now accepted, and access is offered to pact partners who share a border.

Research uses one slot for discoveries and one for upgrades. Units are recruited across the unlocked types by weighted deficit.

```python
DISC_ORDER = [
    "iron_working", "roads", "horse_riding", "masonry", "siege_engines",
    "pikes_crossbows", "crop_rotation", "stirrup", "galleys", "hillmen",
    "trebuchet", "castles", "sailing", "gunpowder", "banking", "matchlock",
    "steam_power", "rifling", "field_engineering", "steel_guns", "railways",
    "machine_guns", "combustion", "tanks", "anti_tank_guns", "heavy_artillery",
    "flight", "grenadiers", "dragoons", "ironclads", "mechanisation",
    "assault_rifles", "heavy_armour", "rocket_artillery", "navigation",
    "ships_of_the_line", "submarines", "dreadnoughts", "bombers", "jet_engines",
    "carriers", "composite_armour", "rocketry", "satellites", "guided_weapons",
    "ballistic_missiles",
]

GEN_LINES = ["farming", "conscription", "industry", "medicine", "staffwork",
             "fieldworks", "drill", "discipline", "logistics", "mining",
             "drilling", "refining"]
TYPE_LINE_TYPES = ["inf", "art", "arm", "cav", "mot", "mec", "hvt", "mil",
                   "grn", "eng", "atg", "mtn", "rec"]

MIX = {
    "inf": 0.24, "mil": 0.05, "rec": 0.02, "cav": 0.06, "mtn": 0.05,
    "art": 0.10, "eng": 0.04, "arm": 0.07, "mot": 0.05, "atg": 0.04,
    "grn": 0.05, "hvt": 0.03, "mec": 0.04, "rkt": 0.02,
}

RES_KEEP = 120
RECRUIT_MIN_NET = 2
MIN_ATTACK_STR = 200
PREP_HOURS = 8
MAX_PREP = 3
PACT_EVERY = 60
PACT_HOURS = 168
ACCESS_EVERY = 480
DEPOT_EVERY = 96
MAX_DEPOTS = 6
ECO_EVERY = 12
REFIT_KEEP_RES = 60
REFIT_MAX_PER_TICK = 120


def _count(api, name):
    try:
        api.count(name)
    except Exception:
        pass


def _neighbour_factions(api):
    names = set()
    for p in api.border:
        pr = api.provs.get(p, {})
        for nb in pr.get("nbrs", []):
            o = api.owner_name.get(nb)
            if o:
                names.add(o)
    return names


def _diplo(api, m):
    w = {"res": 1.0, "mp": 1.0, "steel": 0.5, "oil": 1.0, "rare": 1.5,
         "coal": 0.5, "rubber": 1.0}
    near = _neighbour_factions(api)
    for o in list(api.offers_in):
        try:
            kind = o.get("kind")
            oid = o.get("id")
            frm = o.get("frm")
            if kind == "pact":
                hours = o.get("hours")
                if frm in near and (hours is None or hours > 168):
                    api.cmd("reject %s" % oid)
                else:
                    api.cmd("accept %s" % oid)
            elif kind == "alliance":
                if frm in near:
                    api.cmd("reject %s" % oid)
                else:
                    api.cmd("accept %s" % oid)
            elif kind in ("trade", "supply"):
                give = sum(w.get(k, 1.0) * v for k, v in (o.get("you_give") or {}).items())
                get = sum(w.get(k, 1.0) * v for k, v in (o.get("they_give") or {}).items())
                if get >= give:
                    api.cmd("accept %s" % oid)
                else:
                    api.cmd("reject %s" % oid)
        except Exception:
            pass


def _pact_offers(api, m):
    if api.t - m.get("last_pact", -10000) < PACT_EVERY:
        return
    m["last_pact"] = api.t
    near = _neighbour_factions(api)
    for f in api.met:
        if f in api.pacts or f in near:
            continue
        api.cmd("offer %s pact %d" % (f, PACT_HOURS))


def _access(api, m):
    sent = m.setdefault("access_t", {})
    near = _neighbour_factions(api)
    for f in list(api.pacts.keys()):
        if f not in near:
            continue
        if api.t - sent.get(f, -10000) < ACCESS_EVERY:
            continue
        sent[f] = api.t
        api.cmd("offer %s access" % f)


def _research(api, m):
    active = [r[0] for r in api.research]
    n_disc = 0
    for d in active:
        if d in api.tree:
            n_disc += 1
    n_up = len(active) - n_disc
    if len(active) >= 2:
        return
    # one discovery slot
    if n_disc == 0:
        for d in DISC_ORDER:
            v = api.tree.get(d)
            if not isinstance(v, dict) or v.get("status") != "open":
                continue
            if (v.get("res_now") or 0) > api.res - 80:
                continue
            if api.cmd("research " + d).startswith("ok"):
                return
    # one upgrade slot
    if n_up == 0:
        lines = list(GEN_LINES)
        for typ in TYPE_LINE_TYPES:
            for suf in ("weapons", "protection", "mobility"):
                lines.append(typ + "." + suf)
        for line in lines:
            info = api.tech.get(line)
            if not info or info.get("status") != "open":
                continue
            cost = info.get("cost") or {}
            if all(api.stock.get(k, 0) >= v + 30 for k, v in cost.items()) \
                    and api.res >= cost.get("res", 0) + 80:
                if api.cmd("research " + line).startswith("ok"):
                    return


def _economy(api, m):
    if api.t - m.get("last_eco", -10000) < ECO_EVERY:
        return
    eco = api.economy if isinstance(api.economy, dict) else {}
    works = eco.get("works") or []
    if len(works) >= 2:
        return
    border = set(api.border)
    for r in eco.get("provs") or []:
        if not isinstance(r, dict):
            continue
        p = r.get("prov")
        if p is None or p in border:
            continue
        if r.get("can_dev") and (r.get("dev") or 0) + 1 <= (r.get("room") or 0) and api.res >= 200:
            if api.cmd("develop P%d" % p).startswith("ok"):
                m["last_eco"] = api.t
                _count(api, "develop_ok")
                return
        if r.get("can_infra") and (r.get("infra") or 0) < 2 \
                and (r.get("agg") or 0) >= 1.1 and api.res >= 200:
            if api.cmd("build P%d" % p).startswith("ok"):
                m["last_eco"] = api.t
                _count(api, "build_ok")
                return


def _refit(api, m):
    if api.res < REFIT_KEEP_RES + 20 or api.old_units <= 0:
        return
    cands = [u for u in api.units
             if u.get("old") and not u["fighting"] and not u["path"]
             and u["state"] in ("ready", "shaken") and u.get("supplied")]
    if not cands:
        return
    budget = api.res - REFIT_KEEP_RES
    stock = dict(api.stock)
    chosen = []
    for u in cands:
        rc = api.refit_cost.get(u["type"], {})
        if rc.get("res", 0) > budget:
            continue
        if any(rc.get(k, 0) > stock.get(k, 0) for k in ("steel", "oil", "rare")):
            continue
        budget -= rc.get("res", 0)
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - rc.get(k, 0)
        chosen.append(u["id"])
        if len(chosen) >= REFIT_MAX_PER_TICK:
            break
    if chosen:
        api.cmd("refit " + ",".join(str(i) for i in chosen))


def _depots(api, m):
    if api.t - m.get("last_depot", -10000) < DEPOT_EVERY:
        return
    if api.res < 260 or len(api.depots) >= MAX_DEPOTS:
        return
    hot = False
    for d in api.depots.values():
        cap = d.get("capacity", 0) or 0
        if cap and (d.get("load", 0) or 0) >= 0.6 * cap:
            hot = True
            break
    if not hot:
        return
    m["last_depot"] = api.t
    cands = []
    for p in api.border:
        if p in api.depots:
            continue
        pr = api.provs.get(p, {})
        if pr.get("owner") != "me" or not pr.get("supplied"):
            continue
        path = api.path(api.capital, p)
        if path:
            cands.append((len(path), p))
    cands.sort(reverse=True)
    for L, p in cands[:8]:
        near = 99
        for d in api.depots:
            dp = api.path(d, p)
            if dp:
                near = min(near, len(dp))
        if near >= 5:
            if api.cmd("depot P%d" % p).startswith("ok"):
                _count(api, "depot_opened")
            return


def _recruit(api, m):
    if api.res < 120:
        return
    budget = api.budget if isinstance(api.budget, dict) else {}
    net = budget.get("net", api.income)
    if net is None:
        net = api.income
    if net < RECRUIT_MIN_NET and api.res < 600:
        return
    mix = {}
    for typ, s in MIX.items():
        if typ in api.costs and s > 0:
            mix[typ] = s
    if not mix:
        return
    S = sum(mix.values())
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total_now = len(api.units)
    res = api.res
    mp = api.mp
    stock = dict(api.stock)
    for _ in range(4):
        total = total_now + 1
        best = None
        bd = -1e9
        for typ, s in mix.items():
            rc, mc = api.costs[typ]
            if rc > res - RES_KEEP or mc > mp:
                continue
            uc = api.unit_costs.get(typ, {})
            if any(uc.get(k, 0) > stock.get(k, 0) for k in ("steel", "oil", "rare")):
                continue
            d = (s / S) * total - counts.get(typ, 0)
            if d > bd:
                bd = d
                best = typ
        if best is None:
            return
        r = api.cmd("recruit %s 1 P%d" % (best, api.capital))
        if not r.startswith("ok"):
            return
        rc, mc = api.costs[best]
        res -= rc
        mp -= mc
        uc = api.unit_costs.get(best, {})
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - uc.get(k, 0)
        counts[best] = counts.get(best, 0) + 1
        total_now += 1


def _ids(us):
    return ",".join(str(u["id"]) for u in us)


def _assign(api, m):
    idle = [
        u for u in api.units
        if not u["path"] and not u["front"] and not u["expand"]
        and not u["explore"] and not u["fighting"] and u["state"] == "ready"
    ]
    if not idle:
        return
    scouts = [u for u in idle if u["type"] == "rec"]
    rest = [u for u in idle if u["type"] != "rec"]
    if scouts:
        if api.cmd("explore " + _ids(scouts)).startswith("ok"):
            _count(api, "explore_scouts")
    if not rest:
        return
    explorers = [u for u in api.units if u["explore"]]
    if not api.neutral_border and api.unexplored and len(explorers) < 2:
        inf = [u for u in rest if u["type"] == "inf"] or rest
        pick = inf[0]
        if api.cmd("explore %d" % pick["id"]).startswith("ok"):
            _count(api, "explore_inf")
        rest = [u for u in rest if u["id"] != pick["id"]]
    if not rest:
        return
    if api.neutral_border:
        share = max(1, (len(rest) * 4) // 5)
        half = rest[:share]
        if api.cmd("expand " + _ids(half)).startswith("ok"):
            _count(api, "expand_units")
        rest = rest[share:]
    if rest:
        ids = _ids(rest)
        api.cmd("front " + ids)
        if m.get("line_init"):
            api.cmd("group line + " + ids)
        elif api.cmd("group line " + ids).startswith("ok"):
            m["line_init"] = True


def _ratio(api, us, tgt):
    e = api.enemy.get(tgt)
    if not e or not us:
        return 0.0
    att = sum(u["str"] for u in us)
    return att / max(1.0, float(e.get("str", 0) or 0))


def _need(api, tgt):
    pr = api.provs.get(tgt, {})
    fort = int(pr.get("fort", 0) or 0)
    req = 2.5 + 0.8 * fort
    t = str(pr.get("terrain", "")).lower()
    if t.startswith(("hill", "mount", "mtn")):
        req += 0.5
    e = api.enemy.get(tgt, {})
    if not e.get("exact"):
        req += 0.5
    return req


def _attack(api, m):
    prep = m.setdefault("prep", {})
    t = api.t
    by_prov = {}
    for u in api.units:
        if u["path"] or u["type"] == "rec" or u.get("dom", 0) != 0:
            continue
        by_prov.setdefault(u["prov"], []).append(u)

    for pid, (tgt, t0) in list(prep.items()):
        if pid not in by_prov or api.provs.get(tgt, {}).get("owner") == "me":
            del prep[pid]
            continue
        if t - t0 >= PREP_HOURS:
            us = [u for u in by_prov[pid] if u["rdy"] >= 60 and not u["fighting"]]
            att = sum(u["str"] for u in us)
            if _ratio(api, us, tgt) >= _need(api, tgt) - 0.5 and att >= MIN_ATTACK_STR:
                if api.cmd("move @P%d P%d" % (pid, tgt)).startswith("ok"):
                    _count(api, "assault_launch")
            else:
                api.cmd("hold @P%d" % pid)
                _count(api, "assault_called_off")
            del prep[pid]

    if len(prep) >= MAX_PREP:
        return
    busy = set(prep.keys()) | set(v[0] for v in prep.values())
    cands = []
    for pid, us in by_prov.items():
        if pid in prep:
            continue
        pr = api.provs.get(pid)
        if not pr:
            continue
        ready = [u for u in us if u["rdy"] >= 65 and u["str"] >= 40
                 and u["state"] in ("ready", "defending") and not u["fighting"]]
        if sum(u["str"] for u in ready) < MIN_ATTACK_STR:
            continue
        for nb in pr.get("nbrs", []):
            if nb not in api.enemy or nb in busy:
                continue
            if api.owner_name.get(nb) in api.pacts:
                continue
            pn = api.provs.get(nb, {})
            if pn.get("owner") == "me":
                continue
            ratio = _ratio(api, ready, nb)
            if ratio >= _need(api, nb):
                cands.append((ratio, pid, nb))
    used = set()
    for ratio, pid, nb in sorted(cands, key=lambda c: c[0], reverse=True):
        if len(prep) >= MAX_PREP:
            break
        if pid in used or nb in used:
            continue
        if api.cmd("prepare @P%d P%d" % (pid, nb)).startswith("ok"):
            prep[pid] = (nb, t)
            used.add(pid)
            used.add(nb)
            _count(api, "prepare_ok")


def tick(api):
    m = api.mem
    for f in (_diplo, _pact_offers, _access, _research, _economy, _refit,
              _depots, _recruit, _attack, _assign):
        try:
            f(api, m)
        except Exception:
            pass
```

```feedback
Most useful: a single list of discoveries with their prerequisites and res_now, plus api.tree status for each, is easy to use. The per-line upgrade names (inf.weapons etc.) are not listed anywhere I could find unless q tech is called; a sample name list in the briefing would help. api.enemy 'exact' is only set next to units, so attack-ratio decisions rely on estimates far from the front; an explicit confidence field would help. offers_in kinds for access/supply were unclear. Assault outcome by strength ratio would be good to see live via api.army(1).
```

REVIEW: standard