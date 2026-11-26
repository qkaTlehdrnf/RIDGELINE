Aurum gets +10% defence and −10% speed, so the plan is to defend first, expand early and attack only selectively.

- **Early game:** two scouts keep the `explore` order going. Every other idle unit takes neutral land with `expand`. When nothing neutral is left in reach, the engine moves it to the front order, where it spreads along the border and digs in.
- **Recruiting:** I recruit only while the bank covers the cost and daily income stays positive after the new unit's upkeep. The army is mostly infantry, about one artillery per four units, some engineers, and mountain troops when the home ground is mostly hills. Militia fill in when resources are short but manpower is high.
- **Attacking:** once the army has 12 or more units, about a third becomes a strike group. It picks an adjacent enemy province (the capital if one is adjacent) using the fitted model's capture chance times the province's yield. It gathers in an owned province next to the target, prepares for about 30 hours to get up to +30% attack, then assaults. The group re-forms after a success or failure, or when it is worn down. Units under 40 strength go back to the front order so it rotates them to the rear to refit.
- **Robustness:** all calls are guarded against errors, and the work per tick is light.

```python
def _sig(z):
    if z < -30: return 0.0
    if z > 30: return 1.0
    return 1.0 / (1.0 + math.exp(-z))

TDF = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}

def _pcap(api, att_str, def_str, prov, rdy, heavy, bonus):
    m = api.model or {}
    pr = api.provs.get(prov, {})
    x = [math.log((att_str + 1.0) / (def_str + 1.0)),
         TDF.get(pr.get("terrain"), 1.0) + (0.25 if pr.get("city") else 0),
         pr.get("fort", 0) or 0, 1.0 if pr.get("city") else 0.0,
         bonus, rdy, heavy, 1.0]
    if not m.get("w"):
        return _sig(x[0] * 1.5 - 0.5 - 0.3 * x[2])
    z = m.get("b", 0)
    for i, w in enumerate(m["w"]):
        sd = m["std"][i] or 1.0
        z += w * (x[i] - m["mean"][i]) / sd
    return _sig(z)

def _recruit(api, mem, units):
    if api.t < mem.get("next_rec", 0):
        return
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    n = len(units)
    hills = 0; tot = 0
    for pid, p in api.provs.items():
        if p.get("owner") == "me":
            tot += 1
            if p.get("terrain") in ("hill", "mountain"): hills += 1
    for _ in range(4):
        if counts.get("rec", 0) < 2:
            typ = "rec"
        elif counts.get("art", 0) < 0.22 * n:
            typ = "art"
        elif counts.get("eng", 0) < 0.06 * n and n > 8:
            typ = "eng"
        elif tot and hills > 0.4 * tot and counts.get("mtn", 0) < 0.3 * n:
            typ = "mtn"
        else:
            typ = "inf"
        c = api.costs.get(typ, (30, 30))
        up = {"inf": .3, "mil": .1, "mtn": .35, "mot": .45, "arm": .6, "art": .45, "eng": .3, "rec": .15}.get(typ, .4)
        if api.res < c[0] or api.mp < c[1] or api.income - mem.get("pend_up", 0) < up + 0.5:
            if typ == "inf":
                cm = api.costs.get("mil", (12, 25))
                if api.res >= cm[0] and api.mp >= cm[1] + 40 and api.income - mem.get("pend_up", 0) > 0.8:
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
    if api.t % 24 < 6:
        mem["pend_up"] = 0
    mem["next_rec"] = api.t + 6

def _assign(api, mem, units, strike):
    for u in units:
        if u["id"] in strike: continue
        if u["type"] == "rec":
            if not u["path"] and api.t >= mem.setdefault("rec_t", {}).get(u["id"], 0):
                api.cmd("explore %d" % u["id"])
                mem["rec_t"][u["id"]] = api.t + 48
            continue
        if u["front"] or u.get("expand"): continue
        if u["path"] and not u["fighting"]: continue
        if api.neutral_border and api.t < 2400:
            api.cmd("expand %d" % u["id"])
        else:
            api.cmd("front %d" % u["id"])

def _strike(api, mem, units):
    byid = dict((u["id"], u) for u in units)
    s = mem.setdefault("s", {"ids": [], "ph": "idle", "tgt": -1, "stg": -1, "t0": 0})
    s["ids"] = [i for i in s["ids"] if i in byid]
    combat = [u for u in units if u["type"] not in ("rec",)]
    def release(ids):
        for i in ids:
            api.cmd("front %d" % i)
    # drop weak
    weak = [i for i in s["ids"] if byid[i]["str"] < 40]
    if weak:
        release(weak)
        s["ids"] = [i for i in s["ids"] if i not in weak]
    if s["ph"] != "idle" and len(s["ids"]) < 3:
        release(s["ids"]); s["ids"] = []; s["ph"] = "idle"
    if s["ph"] == "idle":
        if len(combat) < 12 or api.t < mem.get("s_cool", 0):
            return
        best = None
        caps = set((api.enemy_capitals or {}).values())
        for pid, p in api.provs.items():
            if p.get("owner") != "enemy": continue
            stgs = [nb for nb in p.get("nbrs", []) if api.provs.get(nb, {}).get("owner") == "me"
                    and api.provs[nb].get("supplied")]
            if not stgs: continue
            e = api.enemy.get(pid)
            ds = e["str"] if e else 150.0
            pool = [u for u in combat if u["str"] >= 70 and u["type"] != "mil"]
            k = max(4, len(combat) // 3)
            att = sum(u["str"] for u in pool[:k])
            p_ = _pcap(api, att, ds * 1.3, pid, 0.8, 0.3, 0.3)
            val = p_ * (1.0 + p.get("y", 0) + p.get("mp", 0) * 0.2 + (20 if pid in caps else 0))
            if p_ > 0.5 and (best is None or val > best[0]):
                stg = max(stgs, key=lambda x: api.provs[x].get("stock", 0))
                best = (val, pid, stg)
        if not best:
            mem["s_cool"] = api.t + 24
            return
        k = max(4, len(combat) // 3)
        cand = [u for u in combat if u["str"] >= 70 and u["type"] != "mil" and not u["fighting"]]
        tg = best[2]
        def dist(u):
            pa = api.path(u["prov"], tg)
            return len(pa) if pa else 999
        cand.sort(key=dist)
        pick = [u for u in cand[:k] if dist(u) < 999]
        if len(pick) < 4:
            mem["s_cool"] = api.t + 24
            return
        s["ids"] = [u["id"] for u in pick]
        s["tgt"] = best[1]; s["stg"] = tg; s["ph"] = "gather"; s["t0"] = api.t
        api.cmd("move %s P%d" % (",".join(str(i) for i in s["ids"]), tg))
        return
    ids = ",".join(str(i) for i in s["ids"])
    tp = api.provs.get(s["tgt"], {})
    if s["ph"] == "gather":
        if api.provs.get(s["stg"], {}).get("owner") != "me" or tp.get("owner") == "me":
            release(s["ids"]); s["ids"] = []; s["ph"] = "idle"; return
        here = [i for i in s["ids"] if byid[i]["prov"] == s["stg"] and not byid[i]["path"]]
        if len(here) >= 0.8 * len(s["ids"]) or api.t - s["t0"] > 72:
            api.cmd("prepare %s P%d" % (",".join(str(i) for i in here) or ids, s["tgt"]))
            s["ph"] = "prep"; s["t0"] = api.t
        return
    if s["ph"] == "prep":
        if tp.get("owner") == "me":
            release(s["ids"]); s["ids"] = []; s["ph"] = "idle"; return
        if api.t - s["t0"] >= 30:
            att = sum(byid[i]["str"] for i in s["ids"])
            e = api.enemy.get(s["tgt"])
            ds = e["str"] if e else 50.0
            heavy = sum(1 for i in s["ids"] if byid[i]["type"] in ("art", "eng", "arm")) / float(len(s["ids"]))
            rdy = sum(byid[i]["rdy"] for i in s["ids"]) / (100.0 * len(s["ids"]))
            if _pcap(api, att, ds, s["tgt"], rdy, heavy, 0.3) < 0.35 and api.t - s["t0"] < 60:
                return
            if _pcap(api, att, ds, s["tgt"], rdy, heavy, 0.3) < 0.25:
                release(s["ids"]); s["ids"] = []; s["ph"] = "idle"; mem["s_cool"] = api.t + 48; return
            api.cmd("move %s P%d" % (ids, s["tgt"]))
            s["ph"] = "assault"; s["t0"] = api.t
        return
    if s["ph"] == "assault":
        if tp.get("owner") == "me":
            api.cmd("hold %s" % ids)
            # keep momentum: pick next target from here
            release(s["ids"]); s["ids"] = []; s["ph"] = "idle"
            mem["s_cool"] = api.t + 6
            return
        if api.t - s["t0"] > 72:
            release(s["ids"]); s["ids"] = []; s["ph"] = "idle"; mem["s_cool"] = api.t + 36

def tick(api):
    mem = api.mem
    units = api.units
    try:
        _recruit(api, mem, units)
    except Exception:
        pass
    try:
        _strike(api, mem, units)
    except Exception:
        mem["s"] = {"ids": [], "ph": "idle", "tgt": -1, "stg": -1, "t0": 0}
    strike = set(mem.get("s", {}).get("ids", []))
    _assign(api, mem, units, strike)
```