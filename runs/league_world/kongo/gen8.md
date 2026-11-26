**Reasoning (≤200 words)**

Last war I finished 13th with 113 provinces. The record shows I hold the front well (readiness 79, 77% ready) but rarely take land. Of 1 real assault, 1 succeeded, and it was large. Two things stand out:

- **Idle wealth:** I ended with 1,332 res, 1,767 rare and 5,701 rubber unspent. Rubber is barely used by my units, so it can only pay for upgrades.
- **No economy investment:** The new development layer is unused. Developing provinces raises yield and agglomeration, and my treasury can afford it.

Changes in this version:
1. **New `_economy` step.** When res is comfortable and coal is available, it develops the best-yielding owned provinces, two per tick at most. It stops when the treasury falls below a reserve.
2. **Slightly bolder attacks.** I lower the minimum assault probability from 0.70 to 0.62 and keep the ratio thresholds. This targets the stalemate without changing pact logic.
3. **Keep everything else** (diplomacy, depots, research order, refits), since those were not the bottleneck.

I am not changing the rules-level strategy beyond these tuned thresholds. The agent-level economic choices are kept small and reversible.

```python
W_EARLY = {"inf": 0.40, "mil": 0.10, "mtn": 0.10, "mot": 0.10, "eng": 0.08, "rec": 0.02}
W_LATE = {"inf": 0.16, "mtn": 0.06, "mot": 0.07, "mec": 0.07, "arm": 0.18,
          "hvt": 0.08, "art": 0.14, "grn": 0.07, "atg": 0.05, "eng": 0.04,
          "rkt": 0.05, "cav": 0.01, "mil": 0.01}
RESEARCH = ["mining", "staffwork", "logistics", "industry", "conscription",
            "refining", "drilling", "arm.weapons", "mot.mobility", "art.mobility",
            "farming", "inf.protection", "arm.protection", "art.weapons",
            "inf.weapons", "hvt.weapons", "mec.protection", "fieldworks",
            "medicine", "drill", "discipline", "grn.weapons", "atg.weapons"]
TDEF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
EXCLUDE_ATTACK = ("rec", "eng")
MIN_RATIO_EXACT = 3.0
MIN_RATIO_ESTIMATE = 3.5
PACT_RATIO = 4.0
PACT_PROB = 0.85
FORT_RATIO = 4.0
MIN_PROB = 0.62
UNSEEN_DEF = 120.0
PREP_WAIT = 14
MAX_WAVES = 3
WAVE_CAP = 60


def _nbs(pr):
    out = []
    for x in pr.get("nbrs", []) or []:
        if isinstance(x, int):
            out.append(x)
        elif isinstance(x, dict):
            if isinstance(x.get("id"), int):
                out.append(x["id"])
        else:
            digits = "".join(c for c in str(x) if c.isdigit())
            if digits:
                out.append(int(digits))
    return out


def _csv(ids):
    return ",".join(str(i) for i in ids)


def _neighbour_factions(api):
    out = set()
    for p, pr in api.provs.items():
        if pr.get("owner") != "me":
            continue
        for nb in _nbs(pr):
            nm = (api.owner_name or {}).get(nb)
            if nm and nm != api.me:
                out.add(nm)
    return out


def _fits(api, t, res_left, mp_left, stock, keep):
    c = api.unit_costs.get(t)
    if not c:
        return False
    if res_left - c.get("res", 0) < keep:
        return False
    if mp_left < c.get("mp", 0):
        return False
    for k in ("steel", "oil", "rare"):
        if stock.get(k, 0) < c.get(k, 0):
            return False
    return True


def _recruit_city(api):
    best = None
    for p, pr in api.provs.items():
        if pr.get("owner") == "me" and pr.get("city") and p in api.border:
            best = p
            break
    return best if best is not None else api.capital


def _recruit(api):
    if api.income < -10 and api.res < 400:
        return
    weights = W_EARLY if api.t < 96 else W_LATE
    mp_keep = 0 if api.t < 72 else 40
    counts = {}
    for u in api.units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    res_left = api.res
    mp_left = api.mp
    stock = dict(api.stock)
    keep = 60 + 0.5 * len(api.units)
    city = _recruit_city(api)
    for _ in range(16):
        best = None
        bv = 1e18
        for t, w in weights.items():
            if t == "rec" and counts.get("rec", 0) >= 2:
                continue
            if not _fits(api, t, res_left, mp_left - mp_keep, stock, keep):
                continue
            v = (counts.get(t, 0) + 1) / w
            if v < bv:
                bv = v
                best = t
        if best is None:
            break
        r = api.cmd("recruit %s P%d" % (best, city))
        if not str(r).startswith("ok"):
            break
        c = api.unit_costs[best]
        res_left -= c.get("res", 0)
        mp_left -= c.get("mp", 0)
        for k in ("steel", "oil", "rare"):
            stock[k] = stock.get(k, 0) - c.get(k, 0)
        counts[best] = counts.get(best, 0) + 1


def _research(api):
    if len(api.research) >= 2 or api.res < 200:
        return
    busy = set(r[0] for r in api.research)
    names = [n for n in RESEARCH if n in api.tech]
    names += sorted(n for n in api.tech if n not in names)
    for line in names:
        if len(api.research) + 1 >= 3:
            return
        if line in busy:
            continue
        st = api.tech.get(line)
        if not st or st.get("status") in ("dead end", "complete", "researching"):
            continue
        cost = st.get("cost") or {}
        good = True
        for k, v in cost.items():
            if k == "res":
                if api.res - v < 120:
                    good = False
            elif api.stock.get(k, 0) < v:
                good = False
        if good:
            api.cmd("research %s" % line)
            return


def _economy(api):
    # Spend surplus treasury on development of the most productive owned provinces.
    if api.res < 800 or api.t < 48:
        return
    econ = api.economy or {}
    done = 0
    for pr in (econ.get("provs") or [])[:30]:
        if done >= 2:
            break
        p = pr.get("prov")
        if p is None:
            continue
        dev = pr.get("dev", 0) or 0
        if dev >= 6:
            continue
        dc = pr.get("dev_cost") or 0
        if api.res - dc < 600:
            continue
        if api.stock.get("coal", 0) < 8 * (dev + 1):
            continue
        r = api.cmd("develop P%d" % p)
        if str(r).startswith("ok"):
            done += 1


def _depots(api):
    if api.res < 500 or api.t < 60:
        return
    dep = api.depots or {}
    if not dep or len(dep) >= 6:
        return
    if api.t - api.mem.get("depot_t", -9999) < 96:
        return
    worst = max(dep.values(), key=lambda d: d.get("load", 0) or 0)
    if (worst.get("load", 0) or 0) < 35:
        return
    cands = []
    for p in api.border:
        pr = api.provs.get(p)
        if not pr or pr.get("owner") != "me" or not pr.get("supplied"):
            continue
        if p in dep:
            continue
        if any(q in dep for q in _nbs(pr)):
            continue
        cands.append((0 if pr.get("city") else 1, p))
    if not cands:
        return
    cands.sort()
    r = api.cmd("depot P%d 0.2" % cands[0][1])
    if str(r).startswith("ok"):
        api.mem["depot_t"] = api.t


def _orders(api):
    n = 0
    for u in api.units:
        if n >= 40:
            break
        if u.get("path") or u.get("plan", -1) != -1:
            continue
        if u.get("front") or u.get("expand") or u.get("explore") or u.get("fighting"):
            continue
        if u.get("state") not in ("ready", "digging", "refitting"):
            continue
        if u["type"] == "rec":
            api.cmd("explore %d" % u["id"])
        else:
            api.cmd("expand %d" % u["id"])
        n += 1


def _refit(api):
    if api.old_units <= 0 or api.res < 200:
        return
    st = dict(api.stock)
    ids = []
    for u in api.units:
        if len(ids) >= 30:
            break
        if not u.get("old") or u.get("fighting") or u.get("path"):
            continue
        if u.get("state") != "ready" or not u.get("supplied"):
            continue
        if u["prov"] in api.border:
            continue
        rc = api.refit_cost.get(u["type"]) or {}
        ok = True
        for k in ("res", "steel", "oil", "rare"):
            if st.get(k, 0) - rc.get(k, 0) < (150 if k == "res" else 0):
                ok = False
        if not ok:
            continue
        for k in ("res", "steel", "oil", "rare"):
            st[k] = st.get(k, 0) - rc.get(k, 0)
        ids.append(u["id"])
    if ids:
        api.cmd("refit %s" % _csv(ids))


def _p_take(api, S, D, fort, tdef, rdy, hs, city):
    mdl = api.model or {}
    lr = math.log((S + 1.0) / (D + 1.0))
    if not mdl or "w" not in mdl:
        z = lr * 1.5 - 0.3
    else:
        vals = {"log_ratio": lr, "terrain_dfn": tdef, "fort": fort,
                "city": city, "bonus": 0.0, "att_rdy": rdy / 100.0,
                "heavy_share": hs, "dirs": 1.0}
        z = mdl["b"]
        for i, f in enumerate(mdl["features"]):
            z += mdl["w"][i] * (vals.get(f, 0.0) - mdl["mean"][i]) / mdl["std"][i]
    z = max(-30.0, min(30.0, z))
    return 1.0 / (1.0 + math.exp(-z))


def _attack(api):
    prep = api.mem.setdefault("prep", {})
    broke = api.mem.setdefault("broke", {})
    alive = set(u["id"] for u in api.units)
    for k in list(prep.keys()):
        w = prep[k]
        ids = [i for i in w["ids"] if i in alive]
        if not ids or api.t - w["t0"] > 60:
            del prep[k]
            continue
        w["ids"] = ids
        if api.t - w["t0"] >= PREP_WAIT:
            api.cmd("move %s P%d" % (_csv(ids), w["tgt"]))
            del prep[k]
    if len(prep) >= MAX_WAVES or api.res < 100:
        return

    busy = set()
    for w in prep.values():
        busy |= set(w["ids"])

    by_prov = {}
    for u in api.units:
        by_prov.setdefault(u["prov"], []).append(u)

    mine = set(p for p, pr in api.provs.items() if pr.get("owner") == "me")
    adj = {}
    for p in mine:
        for nb in _nbs(api.provs[p]):
            if nb in mine:
                continue
            pr2 = api.provs.get(nb)
            if pr2 and pr2.get("owner") == "enemy":
                adj.setdefault(nb, []).append(p)

    best = None
    bkey = None
    for nb, ps in adj.items():
        owner = (api.owner_name or {}).get(nb)
        pacted = bool(owner and owner in api.pacts)
        cand = []
        for p in ps:
            for u in by_prov.get(p, []):
                if u["id"] in busy or u["type"] in EXCLUDE_ATTACK:
                    continue
                if u.get("path") or u.get("plan", -1) != -1:
                    continue
                if u.get("state") not in ("ready", "defending", "digging", "refitting"):
                    continue
                cand.append(u)
        if not cand:
            continue
        S = sum(u.get("str", 0) * (0.4 + 0.6 * u.get("rdy", 50) / 100.0) for u in cand)
        rdy = sum(u.get("rdy", 50) for u in cand) / len(cand)
        hs = sum(1 for u in cand if u["type"] in ("arm", "art", "eng", "hvt", "rkt")) / float(len(cand))
        pr2 = api.provs[nb]
        en = api.enemy.get(nb, {}) or {}
        exact = bool(en.get("exact"))
        e = en.get("str", 0) or UNSEEN_DEF
        fort = pr2.get("fort") or 0
        tdef = TDEF.get(pr2.get("terrain"), 1.0)
        city = 1 if pr2.get("city") else 0
        D = e * tdef * (1.25 ** fort)
        need = MIN_RATIO_EXACT if exact else MIN_RATIO_ESTIMATE
        thr = MIN_PROB
        if fort >= 2:
            need = max(need, FORT_RATIO)
        if pacted:
            need = max(need, PACT_RATIO)
        if S < need * D:
            continue
        prob = _p_take(api, S, D, fort, tdef, rdy, hs, city)
        if prob < (PACT_PROB if pacted else thr):
            continue
        key = (prob, S)
        if bkey is None or key > bkey:
            bkey = key
            best = (nb, cand, pacted, owner)

    if not best:
        return
    nb, cand, pacted, owner = best
    if pacted:
        # Only a strong, clearly favourable attack justifies breaking a pact.
        if api.t - broke.get(owner, -9999) < 26:
            return
        r = api.cmd("break %s" % owner)
        if str(r).startswith("ok"):
            broke[owner] = api.t
        return
    cand = cand[:WAVE_CAP]
    ids = [u["id"] for u in cand]
    k = api.mem.get("wave_n", 0) + 1
    api.mem["wave_n"] = k
    api.cmd("group w%d %s" % (k, _csv(ids)))
    api.cmd("hold %s" % _csv(ids))
    api.cmd("prepare %s P%d" % (_csv(ids), nb))
    prep[k] = {"tgt": nb, "t0": api.t, "ids": ids}


def _engineers(api):
    n = 0
    for u in api.units:
        if n >= 10:
            break
        if u["type"] != "eng" or u.get("path") or u.get("fighting") or u.get("state") == "digging":
            continue
        p = u["prov"]
        if p in api.border and (api.provs.get(p, {}).get("fort") or 0) < 3:
            api.cmd("fortify %d" % u["id"])
            n += 1


def _diplomacy(api):
    near = _neighbour_factions(api)
    for o in list(api.offers_in or []):
        oid = o.get("id")
        frm = o.get("frm")
        if o.get("kind") == "pact":
            # Dated pacts from neighbours are accepted; open-ended ones from neighbours are refused.
            if frm in near and not o.get("hours"):
                api.cmd("reject %s" % oid)
            else:
                api.cmd("accept %s" % oid)
            continue
        gy = o.get("you_give", {}) or {}
        if set(gy.keys()) <= {"res"} and gy.get("res", 0) <= 0.3 * api.res:
            api.cmd("accept %s" % oid)
        else:
            api.cmd("reject %s" % oid)
    sent = api.mem.setdefault("sent", {})
    pending = set(o.get("to") for o in (api.offers_out or []))
    for f in api.met:
        if f in api.pacts or f in pending or f in near:
            continue
        if api.t - sent.get(f + "_pact", -9999) < 120:
            continue
        api.cmd("offer %s pact" % f)
        sent[f + "_pact"] = api.t
        if api.t - sent.get(f + "_say", -9999) >= 240:
            api.cmd("say %s Kongo proposes peace: keep fire off each other, we seek no war with you." % f)
            sent[f + "_say"] = api.t


def tick(api):
    for f in (_diplomacy, _research, _economy, _depots, _recruit, _orders, _attack, _engineers, _refit):
        try:
            f(api)
        except Exception:
            pass
```

```feedback
Economy: api.economy provs lists dev_cost but not the coal cost of the next level; a field such as dev_coal would help. Calls to api.provs for enemy land are sparse, so the attack estimate often falls back to UNSEEN_DEF; a per-province last-seen strength would help. The review lists 46 fire exchanges "left out" of the assault table; it would help to see those too. Rubber piles up unused for most factions; a clearer hint about which lines use it would help.
```

REVIEW: standard