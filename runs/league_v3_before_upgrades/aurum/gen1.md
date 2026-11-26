Readiness was the main failure. Almost every assault (259 of 261) launched with readiness 0-34, and only 19 of them succeeded. Units marched to the staging area, lost readiness on the way, and attacked straight away. The plan bonus was almost never built up. Defence and expansion worked: enemy assaults on my land succeeded 12 times out of 215.

Changes:
1. **Strike groups rest before attacking.** Each group gathers at a supplied staging province next to the target. It then holds and prepares until average readiness is at least 65 and the plan bonus is at least 35%, or a time limit passes. It launches only if the battle model gives at least 0.45 to take the province.
2. **A scout joins each strike** and stays next to the target, raising the prepared-attack cap to +75% and giving exact enemy counts.
3. **Several strikes at once,** scaling with army size (up to 4) to keep pressure along a long front. Targets are chosen by model success probability times value, preferring low forts and visible weak garrisons.
4. **Picking strike units uses one breadth-first search over my own land** from the staging province, instead of a path query per unit, so it stays inside the time limit.
5. **Manpower:** no militia when the pool is low. Engineers stay at 6% of the army and artillery stays around 20%, for sieges.
6. **After a capture,** the group holds the province briefly and then joins the front.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
UP = {"inf": .3, "mil": .1, "mtn": .35, "mot": .45, "arm": .6, "art": .45, "eng": .3, "rec": .15}

def _pcap(api, att_str, def_str, prov, rdy, heavy, bonus, dirs=1.0):
    m = api.model or {}
    pr = api.provs.get(prov, {})
    x = [math.log((att_str + 1.0) / (def_str + 1.0)),
         TDF.get(pr.get("terrain"), 1.0) + (0.25 if pr.get("city") else 0),
         pr.get("fort", 0) or 0, 1.0 if pr.get("city") else 0.0,
         bonus, rdy, heavy, dirs]
    if not m.get("w"):
        return _sig(x[0] * 1.5 - 0.5 - 0.3 * x[2] + 2 * bonus + 2 * (rdy - 0.5))
    z = m.get("b", 0)
    for i, w in enumerate(m["w"]):
        sd = m["std"][i] or 1.0
        z += w * (x[i] - m["mean"][i]) / sd
    return _sig(z)

def _recruit(api, mem, units):
    if api.t < mem.get("next_rec", 0):
        return
    mem["next_rec"] = api.t + 6
    if api.t % 24 < 6:
        mem["pend_up"] = 0
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    n = len(units)
    hills = 0; tot = 0
    for pid, p in api.provs.items():
        if p.get("owner") == "me":
            tot += 1
            if p.get("terrain") in ("hill", "mountain"): hills += 1
    for _ in range(5):
        if counts.get("rec", 0) < 3 + n // 120:
            typ = "rec"
        elif counts.get("art", 0) < 0.2 * n:
            typ = "art"
        elif counts.get("eng", 0) < 0.06 * n and n > 10:
            typ = "eng"
        elif tot and hills > 0.4 * tot and counts.get("mtn", 0) < 0.3 * n:
            typ = "mtn"
        else:
            typ = "inf"
        c = api.costs.get(typ, (30, 30))
        up = UP.get(typ, .4)
        if api.res < c[0] or api.mp < c[1] or api.income - mem.get("pend_up", 0) < up + 0.5:
            if typ == "inf":
                cm = api.costs.get("mil", (12, 25))
                if api.res >= cm[0] and api.mp >= cm[1] + 150 and api.income - mem.get("pend_up", 0) > 0.8:
                    r = api.cmd("recruit mil")
                    if r.startswith("ok"):
                        counts["mil"] = counts.get("mil", 0) + 1; n += 1
                        mem["pend_up"] = mem.get("pend_up", 0) + 0.1
                        continue
            break
        r = api.cmd("recruit %s" % typ)
        if not r.startswith("ok"):
            break
        counts[typ] = counts.get(typ, 0) + 1; n += 1
        mem["pend_up"] = mem.get("pend_up", 0) + up

def _assign(api, mem, units, busy):
    rt = mem.setdefault("rec_t", {})
    for u in units:
        if u["id"] in busy: continue
        if u["type"] == "rec":
            if not u["path"] and api.t >= rt.get(u["id"], 0):
                api.cmd("explore %d" % u["id"])
                rt[u["id"]] = api.t + 48
            continue
        if u["front"] or u.get("expand"): continue
        if u["path"] and not u["fighting"]: continue
        if api.neutral_border and api.t < 3000:
            api.cmd("expand %d" % u["id"])
        else:
            api.cmd("front %d" % u["id"])

def _near_own(api, start, depth):
    d = {start: 0}
    fr = [start]
    for k in range(depth):
        nf = []
        for p in fr:
            for nb in api.provs.get(p, {}).get("nbrs", []):
                if nb in d: continue
                if api.provs.get(nb, {}).get("owner") != "me": continue
                d[nb] = k + 1
                nf.append(nb)
        fr = nf
        if not fr: break
    return d

def _new_strike(api, mem, units, byid, busy, taken_tgts, ncombat):
    caps = set((api.enemy_capitals or {}).values())
    pool = [u for u in units if u["type"] not in ("rec", "mil") and u["id"] not in busy
            and u["str"] >= 75 and not u["fighting"]]
    if len(pool) < 5:
        return None
    k = max(5, min(30, ncombat // 4))
    avg = sum(u["str"] for u in pool) / float(len(pool))
    att = avg * min(k, len(pool))
    best = None
    for pid in list(api.border.keys()):
        for tid in api.provs.get(pid, {}).get("nbrs", []):
            p = api.provs.get(tid, {})
            if p.get("owner") != "enemy" or tid in taken_tgts: continue
            if not api.provs[pid].get("supplied"): continue
            e = api.enemy.get(tid)
            if e:
                ds = e["str"] * (1.0 if e.get("exact") else 1.3)
            else:
                ds = 120.0
            pc = _pcap(api, att, ds, tid, 0.7, 0.3, 0.4)
            val = pc * (1.0 + p.get("y", 0) + p.get("mp", 0) * 0.2 + (25 if tid in caps else 0))
            if pc > 0.5 and (best is None or val > best[0]):
                best = (val, tid, pid)
    if not best:
        return None
    tg = best[2]
    dmap = _near_own(api, tg, 8)
    cand = [u for u in pool if u["prov"] in dmap]
    cand.sort(key=lambda u: dmap[u["prov"]])
    pick = cand[:k]
    if len(pick) < 5:
        return None
    ids = [u["id"] for u in pick]
    rec = None
    for u in units:
        if u["type"] == "rec" and u["id"] not in busy and u["str"] >= 50:
            rec = u["id"]; break
    s = {"ids": ids, "rec": rec, "ph": "gather", "tgt": best[1], "stg": tg, "t0": api.t}
    api.cmd("move %s P%d" % (",".join(str(i) for i in ids), tg))
    if rec is not None:
        api.cmd("move %d P%d" % (rec, tg))
    return s

def _run_strike(api, mem, s, byid):
    def release():
        for i in s["ids"]:
            api.cmd("front %d" % i)
        if s.get("rec") is not None and s["rec"] in byid:
            api.cmd("explore %d" % s["rec"])
        s["ph"] = "done"
    s["ids"] = [i for i in s["ids"] if i in byid]
    if s.get("rec") is not None and s["rec"] not in byid:
        s["rec"] = None
    weak = [i for i in s["ids"] if byid[i]["str"] < 40]
    for i in weak:
        api.cmd("front %d" % i)
    s["ids"] = [i for i in s["ids"] if i not in weak]
    if len(s["ids"]) < 3:
        release(); return
    ids = ",".join(str(i) for i in s["ids"])
    tp = api.provs.get(s["tgt"], {})
    if tp.get("owner") == "me":
        if s["ph"] != "hold":
            api.cmd("hold %s" % ids)
            s["ph"] = "hold"; s["t0"] = api.t
            return
    if s["ph"] == "hold":
        if api.t - s["t0"] >= 12:
            release()
        return
    if s["ph"] == "gather":
        if api.provs.get(s["stg"], {}).get("owner") != "me":
            release(); return
        here = [i for i in s["ids"] if byid[i]["prov"] == s["stg"] and not byid[i]["path"]]
        if len(here) >= 0.8 * len(s["ids"]) or api.t - s["t0"] > 96:
            api.cmd("prepare %s P%d" % (",".join(str(i) for i in here) or ids, s["tgt"]))
            s["ids"] = here or s["ids"]
            s["ph"] = "prep"; s["t0"] = api.t
        return
    if s["ph"] == "prep":
        if api.provs.get(s["stg"], {}).get("owner") != "me":
            release(); return
        us = [byid[i] for i in s["ids"]]
        att = sum(u["str"] for u in us)
        rdy = sum(u["rdy"] for u in us) / (100.0 * len(us))
        bon = sum((u.get("bonus") or 0) for u in us) / (100.0 * len(us))
        heavy = sum(1 for u in us if u["type"] in ("art", "eng", "arm")) / float(len(us))
        e = api.enemy.get(s["tgt"])
        ds = e["str"] if e else 60.0
        pc = _pcap(api, att, ds, s["tgt"], rdy, heavy, bon)
        el = api.t - s["t0"]
        ready = rdy >= 0.65 and bon >= 0.35
        if (ready and pc >= 0.45) or (el >= 66 and pc >= 0.45):
            api.cmd("move %s P%d" % (ids, s["tgt"]))
            s["ph"] = "assault"; s["t0"] = api.t
            return
        if el >= 90:
            release(); mem["s_cool"] = api.t + 24
        return
    if s["ph"] == "assault":
        if api.t - s["t0"] > 60:
            release(); mem["s_cool"] = api.t + 24

def _strikes(api, mem, units):
    byid = dict((u["id"], u) for u in units)
    S = mem.setdefault("S", [])
    for s in S:
        try:
            _run_strike(api, mem, s, byid)
        except Exception:
            s["ph"] = "done"
    S[:] = [s for s in S if s["ph"] != "done"]
    combat = [u for u in units if u["type"] not in ("rec", "mil")]
    ncombat = len(combat)
    maxs = min(4, 1 + ncombat // 150)
    if ncombat < 14 or len(S) >= maxs or api.t < mem.get("s_cool", 0):
        return
    busy = set()
    tg = set()
    for s in S:
        busy.update(s["ids"])
        if s.get("rec") is not None: busy.add(s["rec"])
        tg.add(s["tgt"])
    ns = _new_strike(api, mem, units, byid, busy, tg, ncombat)
    if ns:
        S.append(ns)
    else:
        mem["s_cool"] = api.t + 12

def tick(api):
    mem = api.mem
    units = api.units
    try:
        _recruit(api, mem, units)
    except Exception:
        pass
    try:
        _strikes(api, mem, units)
    except Exception:
        mem["S"] = []
    busy = set()
    for s in mem.get("S", []):
        busy.update(s["ids"])
        if s.get("rec") is not None: busy.add(s["rec"])
    _assign(api, mem, units, busy)
```