**Reasoning**

Gallia gets a defence bonus, so I'll play a steady, defensive expansion. The policy keeps a small scouting screen (two `rec`, which are fast, sight 2, and reveal enemy counts), recruits a mixed army weighted toward infantry and anti-armour, and spends on research only when the bank has a safe reserve.

Idle combat units go to `expand` while neutral land is on our border, which lets them take free provinces away from enemies. When no neutral land is left they fall back to the `front` order and dig in. Scouts take `explore`. Research runs two projects at a time, starting with the economy (farming, conscription, then deposit yields) and moving to unit upgrades for the types we actually field. Every order is wrapped in a try block, so one failed call cannot break the tick.

Nothing here is tuned against unknown numbers. Weights and reserves are conservative starting points, and the policy avoids sending units into fights directly, leaving assaults to the `front` and `move` logic of the engine.

```python
def tick(api):
    try:
        _run(api)
    except Exception:
        pass


WEIGHTS = {
    "inf": 0.30, "mtn": 0.08, "mot": 0.05, "arm": 0.14, "art": 0.10,
    "atg": 0.10, "eng": 0.05, "grn": 0.06, "cav": 0.05, "mec": 0.07,
}
LATE_TYPES = ("arm", "mec", "art", "mot")
RESEARCH_ORDER = [
    "farming", "conscription", "mining", "drilling", "logistics",
    "inf.weapons", "atg.weapons", "inf.protection", "arm.weapons",
    "arm.protection", "art.weapons", "mec.protection", "medicine",
    "drill", "discipline", "industry", "fieldworks", "staffwork",
    "refining", "mot.mobility", "mtn.protection",
]


def _run(api):
    t = api.t
    units = api.units
    st = api.stock
    counts = {}
    for u in units:
        counts[u["type"]] = counts.get(u["type"], 0) + 1
    total = len(units)

    def afford(c, reserve=0):
        if not c:
            return False
        for k in ("steel", "oil", "rare"):
            if st.get(k, 0) < c.get(k, 0):
                return False
        if st.get("res", 0) < c.get("res", 0) + reserve:
            return False
        return api.mp >= c.get("mp", 0)

    # --- recruitment: one unit per call, weighted toward the lagging type ---
    if t % 3 == 0 and api.income_by.get("res", 0) >= 0:
        ranked = []
        for typ, w in WEIGHTS.items():
            if typ in LATE_TYPES and t < 96 and typ != "mot":
                continue
            deficit = w * (total + 1) - counts.get(typ, 0)
            ranked.append((deficit, typ))
        ranked.sort(reverse=True)
        for _, typ in ranked:
            uc = api.unit_costs.get(typ)
            if afford(uc, reserve=40):
                r = api.cmd("recruit %s P%d" % (typ, api.capital))
                if r.startswith("ok"):
                    break

    # --- scouts: keep two, used for exploration ---
    if t % 12 == 0 and counts.get("rec", 0) < 2 and api.unexplored:
        uc = api.unit_costs.get("rec")
        if afford(uc, reserve=20):
            api.cmd("recruit rec P%d" % api.capital)

    # --- assign idle units ---
    idle_scouts, idle_combat = [], []
    for u in units:
        if u["path"] or u["front"] or u["expand"] or u["explore"]:
            continue
        if u["state"] not in ("ready", "refitting"):
            continue
        if u["type"] == "rec":
            idle_scouts.append(u["id"])
        else:
            idle_combat.append(u["id"])

    if idle_scouts and api.unexplored:
        api.cmd("explore %s" % ",".join(str(i) for i in idle_scouts))

    if idle_combat:
        for i in range(0, len(idle_combat), 6):
            grp = idle_combat[i:i + 6]
            sel = ",".join(str(x) for x in grp)
            if api.neutral_border:
                api.cmd("expand %s" % sel)
            else:
                api.cmd("front %s" % sel)

    # --- research: keep two projects running, leave a safe reserve ---
    if t % 12 == 0 and len(api.research) < 2:
        for line in RESEARCH_ORDER:
            info = api.tech.get(line)
            if not info or info.get("status") != "open":
                continue
            prefix = line.split(".")[0]
            if "." in line and prefix not in counts:
                continue
            cost = info.get("cost")
            if afford(cost, reserve=150):
                r = api.cmd("research %s" % line)
                if r.startswith("ok"):
                    break
```