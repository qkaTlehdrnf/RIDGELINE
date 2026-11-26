def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}

def _afford(api, typ, n=1, extra=15):
    c = api.unit_costs.get(typ)
    if not c: return False
    st = api.stock
    if st.get("res", 0) < c.get("res", 0) * n + extra: return False
    if api.mp < c.get("mp", 0) * n + 5: return False
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < c.get(k, 0) * n: return False
    return True

RESEARCH = ["farming", "conscription", "staffwork", "logistics", "medicine", "drill",
            "inf.protection", "inf.weapons", "industry", "art.weapons", "grn.weapons",
            "mining", "refining", "drilling", "discipline", "cav.mobility", "rkt.weapons",
            "art.protection", "grn.protection", "atg.weapons", "fieldworks", "inf.mobility",
            "cav.weapons", "rkt.protection", "art.mobility", "grn.mobility", "atg.protection"]

def _research(api):
    if len(api.research) >= 2: return
    busy = set(r[0] for r in api.research)
    for line in RESEARCH:
        if len(busy) >= 2: return
        tl = api.tech.get(line)
        if not tl or tl.get("status") != "open" or line in busy: continue
        cost = tl.get("cost") or {}
        ok = True
        for k in cost:
            v = cost[k]
            if k == "res": v = v + 60
            if api.stock.get(k, 0) < v:
                ok = False
                break
        if not ok: continue
        r = api.cmd("research " + line)
        if r.startswith("ok"):
            busy.add(line)

def _recruit(api, counts, armor_seen, nown, contact):
    if len(api.units) > 0 and api.income < 2 and api.t > 48: return
    if len(api.units) > 11 * nown + 40: return
    pend = api.mem.get("rq", 0)
    res = api.stock.get("res", 0)
    n = 3
    if res > 500: n = 5
    if res > 1200: n = 8
    if res > 2500: n = 12
    early = bool(api.neutral_border) and not contact
    for _ in range(n):
        nrec = counts.get("rec", 0)
        ncomb = len(api.units) - nrec
        if nrec < 3 or (nrec < 10 and api.t > 300 and ncomb > 20 and nrec * 20 < ncomb):
            typ = "rec"
        elif early or (api.neutral_border and pend % 3 == 0 and api.t < 900):
            typ = "cav" if pend % 2 == 0 else "inf"
        else:
            k = pend % 10
            if armor_seen and k in (3, 8): typ = "atg"
            elif k in (2, 6): typ = "art"
            elif k == 9: typ = "rkt" if _afford(api, "rkt") else "art"
            elif k in (4, 7): typ = "grn"
            else: typ = "inf"
            if not _afford(api, typ): typ = "inf"
        if not _afford(api, typ): return
        r = api.cmd("recruit %s 1" % typ)
        if not r.startswith("ok"): return
        counts[typ] = counts.get(typ, 0) + 1
        if typ != "rec": pend += 1
        api.mem["rq"] = pend

def _refit(api, inop):
    if not api.old_units: return
    if api.stock.get("res", 0) < 400: return
    done = 0
    for u in api.units:
        if done >= 10: break
        if not u.get("old") or u["id"] in inop: continue
        if u.get("fighting") or not u.get("supplied") or u["path"]: continue
        if u["state"] in ("routing", "assault", "preparing", "refitting", "shaken"): continue
        if api.provs.get(u["prov"], {}).get("owner") != "me": continue
        if u["prov"] in api.border: continue
        c = api.refit_cost.get(u["type"]) or {}
        ok = api.stock.get("res", 0) >= c.get("res", 0) + 300
        for k in ("steel", "oil", "rare"):
            if api.stock.get(k, 0) < c.get(k, 0) + 20: ok = False
        if not ok: break
        r = api.cmd("refit %d" % u["id"])
        if r.startswith("ok"): done += 1

def _diplo(api):
    mem = api.mem
    met = list(api.met or [])
    pacts = api.pacts or {}
    unpacted = [f for f in met if f not in pacts]
    for o in (api.offers_in or []):
        if o.get("kind") == "pact":
            if len(unpacted) >= 2 and o.get("frm") in unpacted:
                r = api.cmd("accept %s" % o["id"])
                if r.startswith("ok"):
                    unpacted.remove(o["frm"])
                    continue
            api.cmd("reject %s" % o["id"])
        else:
            api.cmd("reject %s" % o["id"])
    last = mem.get("dip_t", -1000)
    if api.t - last < 240 or len(met) < 3: return
    mem["dip_t"] = api.t
    npact = len(met) - len(unpacted)
    pending = set(o.get("to") for o in (api.offers_out or []))
    for f in unpacted:
        if npact >= len(met) // 2: break
        if len(unpacted) - 1 < 2: break
        if f in pending: continue
        api.cmd("offer %s pact" % f)
        api.cmd("say %s Austral proposes peace. We will not attack you while a pact holds." % f)
        npact += 1

def _dstr(api, tgt):
    e = api.enemy.get(tgt)
    d = 0.0
    if e: d = e["str"] * (1.0 if e.get("exact") else 1.3)
    for n in api.provs.get(tgt, {}).get("nbrs", []):
        e2 = api.enemy.get(n)
        if e2 and api.provs.get(n, {}).get("owner") == "enemy":
            d += 0.2 * e2["str"]
    return d

def _need(api, tgt):
    pr = api.provs.get(tgt, {})
    d = _dstr(api, tgt)
    f = pr.get("fort", 0) or 0
    return d * 3.0 * TDF.get(pr.get("terrain"), 1.0) * (1 + 0.25 * f) * (1.2 if pr.get("city") else 1.0) + 250

def _targets(api, base, taken):
    provs = api.provs
    pacts = api.pacts or {}
    fails = api.mem.setdefault("fails", {})
    caps = set(api.enemy_capitals.values())
    out = []
    seen = set()
    for b in base:
        for n in provs.get(b, {}).get("nbrs", []):
            if n in seen or n in taken: continue
            seen.add(n)
            pr = provs.get(n)
            if not pr or pr.get("owner") != "enemy": continue
            if api.owner_name.get(n) in pacts: continue
            if fails.get(str(n), -9999) > api.t - 150: continue
            need = _need(api, n)
            sc = need - (pr.get("y", 0) or 0) * 8
            if pr.get("city"): sc -= 60
            if pr.get("harsh"): sc += 150
            if n in caps: sc -= 500
            out.append((sc, n, b))
    out.sort()
    return out

def _stage_for(api, tgt, cnt):
    best = None
    for n in api.provs.get(tgt, {}).get("nbrs", []):
        pr = api.provs.get(n, {})
        if pr.get("owner") != "me": continue
        s = cnt.get(n, 0) * 10 - (50 if pr.get("harsh") else 0) - (30 if n in pr.get("sea", []) else 0)
        if tgt in (pr.get("sea") or []): s -= 40
        if best is None or s > best[0]: best = (s, n)
    return best[1] if best else None

def _free(api, u, inop):
    if u["id"] in inop or u["type"] in ("rec", "mil"): return False
    if u.get("expand") or u.get("explore"): return False
    if u["str"] < 70 or u["mor"] < 45 or u["rdy"] < 35: return False
    if u["state"] in ("routing", "shaken", "refitting", "assault", "preparing"): return False
    return True

def tick(api):
    mem = api.mem
    ops = mem.setdefault("ops", {})
    fails = mem.setdefault("fails", {})
    provs = api.provs
    units = api.units
    t = api.t
    byid = {}
    counts = {}
    cnt = {}
    for u in units:
        byid[u["id"]] = u
        counts[u["type"]] = counts.get(u["type"], 0) + 1
        cnt[u["prov"]] = cnt.get(u["prov"], 0) + 1
    armor_seen = mem.get("armor", False)
    for e in api.enemy.values():
        ty = e.get("types") or {}
        try:
            if ty.get("arm") or ty.get("hvt") or ty.get("mec"): armor_seen = True
        except Exception:
            pass
    mem["armor"] = armor_seen
    nown = 0
    for p in provs.values():
        if p.get("owner") == "me": nown += 1
    contact = bool(api.enemy) or bool(api.enemy_capitals)

    _research(api)
    _recruit(api, counts, armor_seen, nown, contact)
    if t % 24 < 6:
        try:
            _diplo(api)
        except Exception:
            pass

    inop = set()
    for tk in list(ops.keys()):
        for i in ops[tk]["u"]:
            if i in byid: inop.add(i)

    taken = set(int(k) for k in ops.keys())
    for tk in list(ops.keys()):
        op = ops[tk]
        tgt = op["tgt"]
        ids = [i for i in op["u"] if i in byid]
        weak = [i for i in ids if byid[i]["str"] < 35 or byid[i]["state"] in ("routing", "shaken")]
        ids = [i for i in ids if i not in weak]
        if weak:
            api.cmd("front " + ",".join(str(i) for i in weak))
            for i in weak: inop.discard(i)
        op["u"] = ids
        pr = provs.get(tgt, {})
        def disband():
            if ids:
                api.cmd("front " + ",".join(str(i) for i in ids))
                for i in ids: inop.discard(i)
            del ops[tk]
            taken.discard(tgt)
        if not ids:
            disband(); continue
        if api.owner_name.get(tgt) in (api.pacts or {}):
            disband(); continue
        if pr.get("owner") == "me" and tgt not in api.enemy:
            # success: roll on
            good = [i for i in ids if byid[i]["str"] >= 55]
            nxt = _targets(api, [tgt], taken)
            have = sum(byid[i]["str"] for i in good)
            chosen = None
            for sc, n, b in nxt[:4]:
                if have >= 0.8 * _need(api, n):
                    chosen = n
                    break
            if chosen is None or len(good) < 3:
                disband(); continue
            rest = [i for i in ids if i not in good]
            if rest:
                api.cmd("front " + ",".join(str(i) for i in rest))
                for i in rest: inop.discard(i)
            del ops[tk]
            taken.discard(tgt)
            ops[str(chosen)] = {"tgt": chosen, "stage": tgt, "u": good, "ph": "g", "t0": t, "s0": have}
            taken.add(chosen)
            api.cmd("move %s P%d" % (",".join(str(i) for i in good), tgt))
            continue
        tot = sum(byid[i]["str"] for i in ids)
        if tot < 0.4 * op.get("s0", tot):
            fails[str(tgt)] = t
            disband(); continue
        st = op["stage"]
        if provs.get(st, {}).get("owner") != "me":
            disband(); continue
        ph = op["ph"]
        if ph == "g":
            at = [i for i in ids if byid[i]["prov"] == st and not byid[i]["path"]]
            lag = [i for i in ids if byid[i]["prov"] != st and not byid[i]["path"]]
            if lag:
                api.cmd("move %s P%d" % (",".join(str(i) for i in lag), st))
            if len(at) >= 0.8 * len(ids) or (t - op["t0"] > 100 and len(at) >= 3):
                r = api.cmd("prepare %s P%d" % (",".join(str(i) for i in at), tgt))
                if r.startswith("ok"):
                    op["ph"] = "p"; op["tp"] = t
                    late = [i for i in ids if i not in at]
                    if late:
                        api.cmd("front " + ",".join(str(i) for i in late))
                        for i in late: inop.discard(i)
                    op["u"] = at
                else:
                    disband()
            elif t - op["t0"] > 160:
                disband()
            continue
        if ph == "p":
            bon = sum(byid[i].get("bonus", 0) for i in ids) / float(len(ids))
            rdy = sum(byid[i]["rdy"] for i in ids) / float(len(ids))
            e = api.enemy.get(tgt)
            waited = t - op.get("tp", t)
            go = False
            if not e and waited >= 6 and rdy >= 40: go = True
            elif bon >= 40 and rdy >= 60: go = True
            elif waited >= 60 and rdy >= 50 and bon >= 25: go = True
            elif waited >= 100: go = True
            if go:
                mv = [i for i in ids if byid[i]["type"] not in ("art", "rkt")]
                hd = [i for i in ids if byid[i]["type"] in ("art", "rkt")]
                if not mv: mv = ids; hd = []
                api.cmd("move %s P%d" % (",".join(str(i) for i in mv), tgt))
                if hd: api.cmd("hold " + ",".join(str(i) for i in hd))
                op["ph"] = "a"; op["lt"] = t
            continue
        if ph == "a":
            if t - op.get("lt", t) > 80:
                fails[str(tgt)] = t
                disband()

    comb = [u for u in units if u["type"] != "rec"]
    maxops = min(10, 1 + len(comb) // 45)
    if contact and len(ops) < maxops and t % 12 < 6:
        cands = _targets(api, list(api.border.keys()), taken)
        pool = [u for u in comb if _free(api, u, inop)]
        tries = 0
        for sc, tgt, b in cands:
            if len(ops) >= maxops or tries >= 5 or len(pool) < 4: break
            tries += 1
            st = _stage_for(api, tgt, cnt)
            if st is None: continue
            sp = provs.get(st, {})
            sx = sp.get("x", 0); sy = sp.get("y0", 0)
            need = _need(api, tgt)
            ds = []
            for u in pool:
                pp = provs.get(u["prov"])
                if not pp: continue
                d = (pp.get("x", 0) - sx) ** 2 + (pp.get("y0", 0) - sy) ** 2
                if d > 1600: continue
                if u["prov"] == api.capital and cnt.get(api.capital, 0) <= 4: continue
                ds.append((d, u["id"], u))
            ds.sort()
            pick = []; s = 0.0
            for d, i, u in ds:
                if s >= need or len(pick) >= 60: break
                pick.append(u); s += u["str"]
            if s < need or len(pick) < 3: continue
            ids = [u["id"] for u in pick]
            r = api.cmd("move %s P%d" % (",".join(str(i) for i in ids), st))
            if not r.startswith("ok"): continue
            ops[str(tgt)] = {"tgt": tgt, "stage": st, "u": ids, "ph": "g", "t0": t, "s0": s}
            taken.add(tgt)
            pset = set(ids)
            for i in ids: inop.add(i)
            pool = [u for u in pool if u["id"] not in pset]

    if t % 12 < 6:
        try:
            _refit(api, inop)
        except Exception:
            pass

    # recon support for ops
    recpost = mem.setdefault("recpost", {})
    for k in list(recpost.keys()):
        if int(k) not in byid or str(recpost[k]) not in ops:
            del recpost[k]
    covered = set(recpost.values())
    needs = [ops[k]["tgt"] for k in ops if ops[k]["tgt"] not in covered]
    nexp = sum(1 for u in comb if u.get("expand"))
    cap_exp = len(comb) if not contact else int(len(comb) * 0.5)
    nexplore = sum(1 for u in units if u["type"] == "rec" and u.get("explore"))
    for u in units:
        if u["type"] == "rec":
            if str(u["id"]) in recpost: continue
            if u["state"] == "routing": continue
            if needs and not (u.get("explore") and nexplore <= 1 and api.unexplored):
                tgt = needs.pop(0)
                st = ops[str(tgt)]["stage"]
                if u.get("explore"): nexplore -= 1
                api.cmd("move %d P%d" % (u["id"], st))
                recpost[str(u["id"])] = tgt
                continue
            if u["path"] or u.get("explore") or u.get("front"): continue
            if api.unexplored:
                api.cmd("explore %d" % u["id"])
                nexplore += 1
            continue
        if u["id"] in inop: continue
        if u["path"] or u.get("plan", -1) != -1: continue
        if u.get("front") or u.get("expand") or u.get("explore"): continue
        if u["state"] in ("routing", "assault", "preparing", "refitting"): continue
        if api.neutral_border and (nexp < cap_exp or u["type"] == "cav"):
            r = api.cmd("expand %d" % u["id"])
            if r.startswith("ok"):
                nexp += 1
                continue
        api.cmd("front %d" % u["id"])
    mem["calls"] = mem.get("calls", 0) + 1
