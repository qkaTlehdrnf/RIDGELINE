The policy is a staged plan: fund research first, recruit toward a unit mix that is cheap to upkeep, use militia and infantry to claim neutral land and hold the border, and collect armour, artillery and motorised units into a strike group. When that group is large enough to outmatch a visible enemy province, it stages next to the target, prepares the attack, then moves in. It refits when it is worn down. Every order is wrapped so a failed command does not stop the rest of the tick.

Caveats: the enemy strength estimate defaults to 50 when a province is not visible, and the neighbour list format (possibly `~` prefixes) is parsed defensively. I have not tested this against the engine, so the thresholds are reasoned guesses to tune after the first observed run.

```python
ECON = ["farming", "conscription", "logistics", "industry", "discipline",
        "drill", "fieldworks", "medicine", "mining", "drilling", "refining"]
MILLINES = ["inf.weapons", "inf.protection", "mil.protection", "arm.weapons",
            "arm.protection", "mot.mobility", "mot.weapons", "art.weapons",
            "grn.weapons", "atg.weapons", "eng.protection", "mtn.protection"]
DEPOSIT = {"mining": "steel", "drilling": "oil", "refining": "rare"}
TARGET = {"inf": 0.30, "mil": 0.14, "mtn": 0.06, "mot": 0.08, "arm": 0.10,
          "art": 0.09, "eng": 0.04, "atg": 0.05, "grn": 0.05, "mec": 0.03,
          "cav": 0.02, "hvt": 0.02, "rkt": 0.02}
ATTACK = ("arm", "mot", "art", "grn", "atg", "hvt", "mec", "rkt")
FRONTT = ("inf", "mil", "mtn", "eng", "cav")


def tick(api):
    m = api.mem
    t = api.t
    units = api.units
    provs = api.provs
    cap = api.capital
    m["n"] = m.get("n", 0) + 1

    def cmd(s):
        try:
            return api.cmd(s)
        except Exception:
            return "err"

    def ids(lst):
        return ",".join(str(u["id"]) for u in lst)

    def nid(x):
        try:
            return int(str(x).replace("~", "").replace("P", "").strip())
        except Exception:
            return None

    def nbrs(p):
        pr = provs.get(p)
        if not pr:
            return []
        out = []
        for x in pr.get("nbrs", []):
            v = nid(x)
            if v is not None:
                out.append(v)
        return out

    owned = [p for p, pr in provs.items() if pr.get("owner") == "me"]
    enemy_near = {}
    for p in owned:
        for n in nbrs(p):
            q = provs.get(n)
            if q and q.get("owner") == "enemy":
                enemy_near.setdefault(n, []).append(p)
    enemy_adj = set(p for lst in enemy_near.values() for p in lst)

    own_dep = {}
    for k in ("steel", "oil", "rare"):
        own_dep[k] = any(provs[p].get(k, 0) > 0 for p in owned)

    # spending pool for this tick
    keep = 60 if api.income >= 0 else 120
    pool = {"res": api.stock.get("res", 0) - keep, "mp": api.mp,
            "steel": api.stock.get("steel", 0), "oil": api.stock.get("oil", 0),
            "rare": api.stock.get("rare", 0)}

    def pay(d):
        if not d:
            return False
        for k in ("res", "mp", "steel", "oil", "rare"):
            if pool.get(k, 0) < d.get(k, 0):
                return False
        return True

    def spend(d):
        for k in ("res", "mp", "steel", "oil", "rare"):
            pool[k] = pool.get(k, 0) - d.get(k, 0)

    # ---- research: at most 2 projects, economy first ----
    try:
        types_have = set(u["type"] for u in units)
        busy = set(r[0] for r in api.research)
        slots = 2 - len(api.research)
        for line in ECON + MILLINES:
            if slots <= 0:
                break
            if line in busy:
                continue
            if "." in line and line.split(".")[0] not in types_have:
                continue
            dep = DEPOSIT.get(line)
            if dep and not own_dep.get(dep):
                continue
            tk = api.tech.get(line)
            if not tk or tk.get("status") != "open" or tk.get("level", 0) >= 3:
                continue
            cost = tk.get("cost")
            if not pay(cost):
                continue
            if cmd("research " + line).startswith("ok"):
                spend(cost)
                slots -= 1
    except Exception:
        pass

    # ---- recruitment toward target mix ----
    try:
        counts = {}
        for u in units:
            counts[u["type"]] = counts.get(u["type"], 0) + 1
        n0 = len(units)

        front_city = cap
        for p in owned:
            if provs[p].get("city") and p in enemy_adj:
                front_city = p
                break

        if counts.get("rec", 0) < 2 and pay(api.unit_costs.get("rec")):
            if cmd("recruit rec 1 P%d" % cap).startswith("ok"):
                spend(api.unit_costs.get("rec"))
                counts["rec"] = counts.get("rec", 0) + 1

        made = 0
        while made < 4:
            best, bd = None, -1e9
            for ty, share in TARGET.items():
                d = api.unit_costs.get(ty)
                if not pay(d):
                    continue
                deficit = share * (n0 + made + 1) - counts.get(ty, 0)
                if deficit > bd:
                    bd, best = deficit, ty
            if best is None:
                break
            if bd < -0.5 and pool["res"] < 400:
                break
            city = front_city if best in FRONTT else cap
            if cmd("recruit %s 1 P%d" % (best, city)).startswith("ok"):
                spend(api.unit_costs.get(best))
                counts[best] = counts.get(best, 0) + 1
                made += 1
            else:
                break
    except Exception:
        pass

    # ---- unit roles ----
    try:
        def free(u):
            return (not u.get("path") and u.get("state") == "ready"
                    and not u.get("front") and not u.get("expand")
                    and not u.get("explore") and u.get("group") != "strike")

        for u in units:
            if u["type"] == "rec" and not u.get("explore") and not u.get("path") \
                    and u.get("state") == "ready":
                cmd("explore %d" % u["id"])

        to_strike = [u for u in units if u["type"] in ATTACK and free(u)]
        if to_strike:
            verb = "group strike + %s" if "strike" in api.formations else "group strike %s"
            cmd(verb % ids(to_strike))

        fr = [u for u in units if u["type"] in FRONTT and free(u)]
        if fr:
            fr.sort(key=lambda u: 0 if u["type"] == "mil" else 1)
            neutral = list(api.neutral_border)
            n_exp = sum(1 for u in units if u.get("expand"))
            need = 2 * len(neutral) - n_exp
            sel = []
            if need > 0:
                sel = fr[:need]
                cmd("expand %s" % ids(sel))
            rest = [u for u in fr if u not in sel]
            if rest:
                cmd("front %s" % ids(rest))
    except Exception:
        pass

    # ---- strike group: stage, prepare, launch ----
    try:
        st = [u for u in units if u.get("group") == "strike"]
        op = m.get("op")
        if op is not None:
            e, s = op["tgt"], op["stg"]
            if provs.get(e, {}).get("owner") == "me" or len(st) < 2:
                m["op"] = None
            elif op["ph"] == "gather":
                away = [u for u in st if u["prov"] != s and not u.get("path")]
                if away:
                    cmd("move %s P%d" % (ids(away), s))
                there = [u for u in st if u["prov"] == s]
                if len(there) >= max(2, int(0.8 * len(st))) or t - op["t0"] >= 48:
                    if there:
                        cmd("prepare %s P%d" % (ids(there), e))
                    op["ph"], op["tp"] = "prep", t
                elif t - op["t0"] > 96:
                    m["op"] = None
            elif op["ph"] == "prep":
                if t - op["tp"] >= 12:
                    cmd("move %s P%d" % (ids(st), e))
                    op["ph"], op["tg"] = "go", t
            elif op["ph"] == "go":
                if t - op["tg"] >= 30:
                    m["op"] = None
        elif len(st) >= 4:
            total = sum(u.get("str", 0) for u in st)
            avg = total / len(st)
            if avg < 55:
                if t - m.get("refit_t", -99) >= 24 and cap is not None:
                    cmd("move %s P%d" % (ids(st), cap))
                    m["refit_t"] = t
            else:
                caps = set(api.enemy_capitals.values()) if api.enemy_capitals else set()
                best, bscore = None, -1e9
                for e, cands in enemy_near.items():
                    seen = api.enemy.get(e)
                    es = seen.get("str", 50) if seen else 50
                    if total < 1.5 * es:
                        continue
                    score = -es + (200 if e in caps else 0) + 0.5 * provs[e].get("y", 0)
                    if score > bscore:
                        bscore, best = score, (e, cands)
                if best:
                    e, cands = best
                    stg, bl = None, 1e9
                    for s in cands[:6]:
                        pth = api.path(st[0]["prov"], s)
                        if pth is not None and len(pth) < bl:
                            bl, stg = len(pth), s
                    if stg is not None:
                        m["op"] = {"tgt": e, "stg": stg, "ph": "gather", "t0": t}
    except Exception:
        pass

    # ---- scouting and sight: keep unit counts sane ----
    m["last_t"] = t
```