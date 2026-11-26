**Reasoning:** Nilotica is a defensive faction (+10% defence, -10% speed), so the policy favours holding ground and taking free land over early attacks. It runs in five parts each tick, each wrapped so one failure doesn't drop the whole call:

1. **Recruit** one or two units a tick from a priority list (scout first, then artillery, anti-tank guns if enemy armour is seen, and infantry as the default). It stops when income is negative with a sizeable army, and keeps a 60-resource reserve.
2. **Assign idle units**: infantry-type units expand into neutral land (falling back to the front order automatically when none is in reach), heavier units go on the front, and scouts explore.
3. **Attack only with a large margin**: a province is assaulted only when local strength is at least 2.2x the estimated enemy there. Units `prepare` first and move once their average bonus reaches 25%.
4. **Research blind**: start one upgrade at a time from a fixed list of lines, only for unit types I own, with enough reserve for the cost. Economy and defence lines come first.
5. **Scale carefully**: all actions use `.get` and checks against the stock, so no tick depends on undocumented fields being present.

The attack ratio and recruit mix are guesses to tune after the first war's results.

```python
INF = ("inf", "mil", "mtn", "mot", "cav")
ENEMY_ARMOUR = ("arm", "hvt", "mec")
LINES = [
    "farming", "conscription", "inf.protection", "discipline", "inf.weapons",
    "fieldworks", "art.weapons", "logistics", "atg.weapons", "mining",
    "medicine", "industry", "drill", "mtn.protection", "staffwork",
    "arm.protection", "arm.weapons",
]


def _ids(lst):
    return ",".join(str(u["id"]) for u in lst)


def _bon(u):
    b = u.get("bonus", 0) or 0
    return b * 100 if b <= 1 else b


def _ok(api, t, n=1):
    c = api.costs.get(t, (0, 0))
    uc = api.unit_costs.get(t, {}) or {}
    if api.res < c[0] * n + 60 or api.mp < c[1] * n:
        return False
    st = api.stock
    for k in ("steel", "oil", "rare"):
        if st.get(k, 0) < uc.get(k, 0) * n:
            return False
    return True


def _pick(api, counts, total, armour):
    prio = []
    if counts.get("rec", 0) < 1 and total >= 4:
        prio.append("rec")
    if counts.get("art", 0) < 0.12 * total:
        prio.append("art")
    if armour and counts.get("atg", 0) < 0.12 * total:
        prio.append("atg")
    if total >= 40 and counts.get("arm", 0) < 0.10 * total:
        prio.append("arm")
    prio.append("inf")
    for t in prio:
        if _ok(api, t):
            return t
    return None


def tick(api):
    m = api.mem
    t = api.t
    me = api.me
    units = api.units or []

    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)

    armour = False
    for v in (api.enemy or {}).values():
        ty = str(v.get("types", ""))
        if any(a in ty for a in ENEMY_ARMOUR):
            armour = True

    # 1. Recruit
    try:
        if api.income > 0 or total < 20:
            for _ in range(2):
                pick = _pick(api, counts, total, armour)
                if not pick:
                    break
                r = api.cmd("recruit %s P%d" % (pick, api.capital))
                if not str(r).startswith("ok"):
                    break
                counts[pick] = counts.get(pick, 0) + 1
                total += 1
    except Exception:
        pass

    # 2. Assign idle units
    try:
        idle = [u for u in units
                if u.get("state") == "ready" and not u.get("path")
                and not (u.get("front") or u.get("expand") or u.get("explore"))]
        scouts = [u for u in idle if u["type"] == "rec"]
        inf = [u for u in idle if u["type"] in INF]
        heavy = [u for u in idle if u["type"] not in INF and u["type"] != "rec"]
        if scouts:
            api.cmd("explore " + _ids(scouts))
        if inf:
            api.cmd("expand " + _ids(inf))   # joins the front when no neutral land is in reach
        if heavy:
            api.cmd("front " + _ids(heavy))
    except Exception:
        pass

    # 3. Attacks: only with a large margin, prepared first
    try:
        if api.stock.get("res", 0) >= 80:
            by_prov = {}
            for u in units:
                if (u.get("state") in ("ready", "preparing") and u.get("str", 0) >= 40
                        and not u.get("path") and not u.get("expand")
                        and not u.get("explore") and u["type"] != "rec"):
                    by_prov.setdefault(u["prov"], []).append(u)
            done = False
            for p, lst in by_prov.items():
                if done:
                    break
                pr = api.provs.get(p)
                if not pr:
                    continue
                for n in pr.get("nbrs", []):
                    nd = api.provs.get(n)
                    if not nd or nd.get("who", -1) in (-1, me):
                        continue
                    e = (api.enemy or {}).get(n)
                    if e is None:
                        es = 80.0
                    else:
                        es = e.get("str", 0) * (1.0 if e.get("exact") else 1.4)
                    ours = sum(u.get("str", 0) for u in lst)
                    if ours < 2.2 * es + 60 or ours < 120:
                        continue
                    planned = [u for u in lst if u.get("plan") == n]
                    if planned:
                        avg = sum(_bon(u) for u in planned) / len(planned)
                        if avg >= 25:
                            api.cmd("move %s P%d" % (_ids(planned), n))
                            done = True
                            break
                        continue
                    free = [u for u in lst if u.get("plan", -1) in (-1, None)]
                    if free:
                        api.cmd("prepare %s P%d" % (_ids(free), n))
                        done = True
                        break
    except Exception:
        pass

    # 4. Research (blind; one project started per tick)
    try:
        active = set(r[0] for r in (api.research or []))
        if len(active) < 2 and api.res > 220:
            for line in LINES:
                if line in active:
                    continue
                if "." in line and line.split(".")[0] not in counts:
                    continue
                info = (api.tech or {}).get(line)
                if not info or info.get("status") != "open":
                    continue
                c = info.get("cost") or {}
                if api.res < c.get("res", 0) + 150:
                    continue
                if any(api.stock.get(k, 0) < c.get(k, 0) for k in ("steel", "oil", "rare")):
                    continue
                api.cmd("research %s" % line)
                break
    except Exception:
        pass

    m["calls"] = m.get("calls", 0) + 1
```