"""v11: two thousand years in one war. Seven ages, a tree of discoveries, and what each one opens.

Every faction starts in the ancient world with spearmen, levies and runners. Everything else (horsemen, siege engines,
guns, rifles, engines, tanks, ships, aircraft, satellites) has to be discovered, in an order the tree allows. A
discovery either OPENS a kind of unit, or gives a kind a NEW MODEL (units already in the field keep the old one until
refitted), or changes what the faction can do (bigger forts, ocean sailing, missiles, satellites).

What nobody can know beforehand: how good a faction's own version of a new model turns out. Every model has a nominal
power for its age; the faction's real one is that times a hidden factor drawn per faction, kind and model (QUALITY).
A new model is usually better than the old one, sometimes much better, sometimes barely. It shows only when it is done.

The calendar is compressed: one war of CAL_HOURS game hours stands for the years 0 to 2000.
"""
from . import data as D

ERAS = ("ancient", "medieval", "gunpowder", "industrial", "great-war", "modern", "space")
ERA_YEAR = (0, 600, 1400, 1780, 1900, 1940, 1960)          # roughly when each age began in our own history (for the reader only)
CAL_HOURS = 9216; CAL_YEARS = 2000
POW = (0.30, 0.38, 0.48, 0.62, 0.80, 1.00, 1.20)           # nominal attack and defence of a model of that age (x the table in data.py)
RNG = (0.50, 0.50, 0.60, 0.80, 1.00, 1.00, 1.10)           # range likewise (never below 1.5 cells)
STEEL = (0.0, 0.3, 0.5, 0.8, 1.0, 1.0, 1.2)                # share of the table's steel a model of that age needs
QUALITY = (0.85, 1.20)                                     # HIDDEN factor per faction, kind and model
HOURS = (120, 200, 280, 360, 440, 520, 600)                # research time of a discovery of that age
COST = (200, 450, 800, 1400, 2100, 3000, 4500)             # its res cost ...
NEEDS = ((), (("steel", 20),), (("steel", 40),), (("steel", 60), ("coal", 60)), (("steel", 80), ("coal", 60), ("oil", 80)),
         (("steel", 100), ("oil", 120), ("rubber", 60), ("rare", 20)), (("steel", 120), ("oil", 140), ("rubber", 60), ("rare", 60)))   # ... and what else
DIFFUSE = 0.10; DIFFUSE_MAX = 0.5      # a discovery is this much cheaper for every faction you have met that already has it
START = dict(inf="spearmen", mil="levy", rec="runners")     # what everyone has in the year 0

# name: (age, needs these first, [(kind, model name)], other effect or None, a word on what it is)
TREE = dict(
    iron_working=(0, (), [("inf", "heavy infantry")], None, "iron weapons and armour"),
    horse_riding=(0, (), [("cav", "horsemen"), ("rec", "mounted scouts")], None, "cavalry"),
    siege_engines=(0, (), [("art", "catapults"), ("eng", "sappers")], None, "stone throwers and men who dig"),
    galleys=(0, (), [("shp", "war galleys")], "sail1", "oared warships; troops can be carried along the coast"),
    roads=(0, (), [], "flow", "paved roads: supplies flow faster"),
    masonry=(0, (), [], "fort2", "stone walls: forts up to level 2"),
    stirrup=(1, ("horse_riding",), [("cav", "knights")], None, "shock cavalry"),
    pikes_crossbows=(1, ("iron_working",), [("inf", "pikemen and crossbows"), ("mil", "town militia")], None, "drilled foot"),
    hillmen=(1, ("iron_working",), [("mtn", "hill tribesmen")], None, "light troops for high ground"),
    trebuchet=(1, ("siege_engines",), [("art", "trebuchets")], None, "counterweight artillery"),
    castles=(1, ("masonry",), [], "fort3", "forts up to level 3"),
    sailing=(1, ("galleys",), [("shp", "cogs and carracks")], "sail2", "ships that sail further from home"),
    crop_rotation=(1, ("roads",), [], "farm", "better farming: more res from the land"),
    gunpowder=(2, ("pikes_crossbows", "trebuchet"), [("art", "cannon")], None, "guns that break walls"),
    matchlock=(2, ("gunpowder",), [("inf", "musketeers"), ("mil", "armed burghers")], None, "firearms for the foot"),
    grenadiers=(2, ("matchlock",), [("grn", "grenadiers")], None, "assault infantry"),
    dragoons=(2, ("stirrup", "matchlock"), [("cav", "dragoons"), ("rec", "light horse")], None, "cavalry with firearms"),
    navigation=(2, ("sailing",), [], "ocean", "open-ocean sailing: deep water and the long sea lanes"),
    ships_of_the_line=(2, ("navigation", "gunpowder"), [("shp", "ships of the line")], "sail3", "gunned sailing warships"),
    banking=(2, ("crop_rotation",), [], "bank", "credit: more res from cities"),
    steam_power=(3, ("gunpowder", "banking"), [], "steam", "steam engines: more res, more manpower"),
    railways=(3, ("steam_power",), [], "rail", "supplies flow much faster"),
    rifling=(3, ("matchlock",), [("inf", "riflemen"), ("mtn", "mountain rifles"), ("grn", "storm troops"), ("mil", "reservists")], None, "rifled firearms"),
    steel_guns=(3, ("rifling", "steam_power"), [("art", "field guns")], None, "breech-loading artillery"),
    field_engineering=(3, ("rifling",), [("eng", "pioneers")], None, "trenches, wire and demolition"),
    ironclads=(3, ("steam_power", "ships_of_the_line"), [("shp", "ironclads")], "sail4", "armoured steam warships"),
    combustion=(4, ("steam_power",), [("mot", "lorried infantry")], None, "the petrol engine"),
    machine_guns=(4, ("rifling",), [("inf", "infantry"), ("mil", "territorials"), ("cav", "last cavalry")], None, "automatic fire"),
    heavy_artillery=(4, ("steel_guns",), [("art", "howitzers")], None, "indirect fire"),
    tanks=(4, ("combustion", "steel_guns"), [("arm", "early tanks")], None, "armour"),
    anti_tank_guns=(4, ("heavy_artillery",), [("atg", "anti-tank guns")], None, "guns that kill armour"),
    dreadnoughts=(4, ("ironclads", "heavy_artillery"), [("shp", "battleships")], "sail5", "big-gun warships"),
    submarines=(4, ("ironclads", "combustion"), [("sub", "submarines")], None, "ships that hunt ships"),
    flight=(4, ("combustion",), [("ftr", "biplane fighters")], None, "aircraft"),
    bombers=(4, ("flight",), [("bmr", "bombers")], None, "aircraft that attack the ground and the sea"),
    mechanisation=(5, ("tanks",), [("mec", "mechanised infantry"), ("arm", "battle tanks")], None, "infantry that keeps up with tanks"),
    heavy_armour=(5, ("tanks", "heavy_artillery"), [("hvt", "heavy tanks")], None, "heavy armour"),
    rocket_artillery=(5, ("heavy_artillery",), [("rkt", "rocket launchers")], None, "massed rockets"),
    assault_rifles=(5, ("machine_guns",), [("inf", "modern infantry"), ("grn", "assault infantry"), ("mtn", "mountain troops")], "aa", "modern small arms; infantry can hit aircraft a little"),
    jet_engines=(5, ("flight",), [("ftr", "jet fighters"), ("bmr", "jet bombers")], None, "jets"),
    carriers=(5, ("dreadnoughts", "flight"), [("cvn", "aircraft carriers")], None, "airfields at sea"),
    rocketry=(6, ("jet_engines", "rocket_artillery"), [("rkt", "guided rockets")], None, "big rockets"),
    satellites=(6, ("rocketry",), [], "sat", "eyes in orbit: you see the whole world"),
    ballistic_missiles=(6, ("rocketry",), [], "missile", "the 'strike' command: a missile on any province you can see"),
    guided_weapons=(6, ("satellites",), [("atg", "guided missiles"), ("ftr", "multirole fighters"), ("shp", "missile destroyers")], None, "weapons that find their target"),
    composite_armour=(6, ("heavy_armour",), [("arm", "modern tanks"), ("hvt", "modern heavy tanks")], None, "better armour"),
)
SAIL = dict(sail1=(1.5, 3), sail2=(2.0, 6), sail3=(2.5, 10), sail4=(3.0, 14), sail5=(3.5, 20))      # transport speed, how many sea zones from a home coast ships and transports stay supplied
# models per kind, in the order they can appear: (discovery or None, name, age)
GENS = {c: [(None, n, 0)] for c, n in START.items()}
for _t, (_e, _req, _un, _fx, _w) in TREE.items():
    for _c, _n in _un: GENS.setdefault(_c, []).append((_t, _n, _e))
for _c in GENS: GENS[_c].sort(key=lambda g: (g[2], g[0] is not None))
OPENED_BY = {c: g[0][0] for c, g in GENS.items()}          # kind -> discovery that opens it (None: there from the start)


def year(tick): return int(tick * CAL_YEARS / CAL_HOURS)


def cost(game, pid, name):
    """What the discovery costs this faction now: cheaper for every faction it has met that already knows it."""
    e = TREE[name][0]; p = game.players[pid]
    k = sum(1 for o in p.met if name in game.players[o].known)
    f = 1.0 - min(DIFFUSE_MAX, DIFFUSE * k)
    c = dict(res=int(round(COST[e] * f)))
    for r, v in NEEDS[e]: c[r] = int(round(v * f))
    return c


def model(p, code, g):
    """Stats of model g of a kind for player p (hidden quality included; what p has learned on its side lines carried over)."""
    tech, name, e = GENS[code][g]; s = dict(p.base[code]); q = p._q.get((code, g), 1.0)
    f = POW[e] * q * 1.12 ** sum(1 for x in GENS[code][:g] if x[2] == e)        # a second model within one age is a step up too
    s["atk"] = round(s["atk"] * f, 2); s["dfn"] = round(s["dfn"] * f, 2); s["range"] = round(max(1.5, s["range"] * RNG[e]), 2)
    s["steel"] = int(round(s["steel"] * STEEL[e]))
    if e < 4: s["oil"] = 0; s["fuel"] = 0.0
    if e < 5: s["rare"] = 0
    if e < 4: s["va"] = 0.0
    if e < 3 and s["dom"] == 1: s["hard"] = 0.0
    if p.aa and s["dom"] == 0 and code in ("inf", "mec", "grn", "mtn"): s["va"] = 0.15
    s["name"] = name; s["gen"] = g; s["era"] = e
    for k, v in p.lmul.get(code, {}).items(): s[k] = round(s[k] * v, 3)
    s["xp0"] += p.gadd["xp0"]; s["dig"] = round(s["dig"] * p.gmul["dig"], 3); s["cost"] = max(1, int(round(s["cost"] * p.gmul["cost"])))
    return s


def setup(game, p, rng):
    """Put player p in the year 0."""
    p.base = p.stats; p.known = set(); p.gen = {}; p.lmul = {}; p.gmul = dict(dig=1.0, cost=1.0); p.gadd = dict(xp0=0)
    p.fort_cap = 1; p.sail = 0.0; p.sea_reach = 0; p.ocean = False; p.sat = False; p.missile = False; p.aa = False
    p._q = {(c, g): round(rng.uniform(*QUALITY), 3) for c, gs in GENS.items() for g in range(len(gs))}
    p.stats = {}; p.marks = {}
    for c in START:
        st = model(p, c, 0); st["mark"] = 1; p.stats[c] = st; p.marks[c] = [st]; p.gen[c] = 0


def modern(p):
    """No ages (small maps, tests): everything is open, in its newest form."""
    p.base = p.stats; p.known = set(TREE); p.gen = {c: len(GENS[c]) - 1 for c in GENS}; p.lmul = {}; p.gmul = dict(dig=1.0, cost=1.0); p.gadd = dict(xp0=0)
    p.fort_cap = D.FORT_MAX; p.sail = 3.5; p.sea_reach = 20; p.ocean = True; p.sat = False; p.missile = False; p.aa = False; p._q = {}


def status(game, pid, name):
    """'known' | 'researching' | 'open' | 'locked'"""
    p = game.players[pid]
    if name in p.known: return "known"
    if any(r[0] == name for r in p.research): return "researching"
    return "open" if all(r in p.known for r in TREE[name][1]) else "locked"


def era_of(p):
    return max([TREE[t][0] for t in p.known] or [0])


def finish(game, p, name):
    """The discovery is made. Returns the text of what it brought."""
    e, req, unlocks, fx, word = TREE[name]; p.known.add(name); out = []
    for code, label in unlocks:
        g = [i for i, x in enumerate(GENS[code]) if x[0] == name][0]
        if p.gen.get(code, -1) >= g: continue
        old = p.stats.get(code); st = model(p, code, g); st["mark"] = (old["mark"] + 1) if old else 1
        p.stats[code] = st; p.marks.setdefault(code, []).append(st); p.gen[code] = g
        if old is None: out.append("%s (%s) can now be raised: atk %g dfn %g spd %g range %g" % (code, label, st["atk"], st["dfn"], st["spd"], st["range"]))
        else: out.append("%s new model '%s': atk %g -> %g, dfn %g -> %g (units in the field keep the old model until refitted)" % (code, label, old["atk"], st["atk"], old["dfn"], st["dfn"]))
    if fx in SAIL:
        p.sail, p.sea_reach = SAIL[fx]; out.append("troops sail at speed %g; ships and transports are supplied up to %d sea zones from a home coast" % (p.sail, p.sea_reach))
    elif fx == "flow": p.mult["flow"] *= 1.25; out.append("supply inflow +25%")
    elif fx == "fort2": p.fort_cap = max(p.fort_cap, 2); out.append("forts up to level 2")
    elif fx == "fort3": p.fort_cap = max(p.fort_cap, 3); out.append("forts up to level 3")
    elif fx == "farm": p.mult["res"] *= 1.12; out.append("res yield +12%")
    elif fx == "bank": p.mult["res"] *= 1.12; out.append("res yield +12%")
    elif fx == "steam": p.mult["res"] *= 1.15; p.mult["mp"] *= 1.15; out.append("res and manpower yield +15%")
    elif fx == "rail": p.mult["flow"] *= 1.5; out.append("supply inflow +50%")
    elif fx == "ocean": p.ocean = True; out.append("ships and transports can cross deep water and use the long sea lanes")
    elif fx == "sat": p.sat = True; out.append("you now see every province in the world")
    elif fx == "missile": p.missile = True; out.append("'strike P<id>' is available (%s each)" % ", ".join("%d %s" % (v, k) for k, v in D.STRIKE.items()))
    elif fx == "aa":
        p.aa = True
        for c in ("inf", "mec", "grn", "mtn"):
            if c in p.stats: p.stats[c]["va"] = max(p.stats[c]["va"], 0.15)
    game._pfree.clear(); game._pown.clear(); game.sdirty[p.id] = True; game.vdirty[p.id] = True; game._seadirty = True
    return "%s (%s age): %s" % (name, ERAS[e], "; ".join(out) or word)
