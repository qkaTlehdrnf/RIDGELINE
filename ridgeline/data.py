"""Tables for Ridgeline v2. 1 tick = 1 game hour. All names and numbers are original."""

TERRAIN = {
    #            move cost (hours for speed 1), defence multiplier, elevation (plain/forest are 0 or 1 depending on the ground), resource yield range, manpower range
    "plain":    dict(cost=16, dfn=1.00, elev=0, y=(2, 3), mp=(1, 2)),
    "forest":   dict(cost=24, dfn=1.25, elev=0, y=(1, 2), mp=(0, 1)),
    "hill":     dict(cost=28, dfn=1.50, elev=2, y=(1, 2), mp=(0, 1)),
    "mountain": dict(cost=44, dfn=2.00, elev=3, y=(0, 1), mp=(0, 0)),
    "water":    dict(cost=0, dfn=0, elev=0, y=(0, 0), mp=(0, 0)),       # lakes and sea: impassable
}
ROUGH = ("forest", "hill", "mountain")
HIGH = ("hill", "mountain")
CITY_YIELD = 4; CITY_MP = 3; CITY_DFN = 0.25

UNITS = {
    # atk/dfn: attack and defence power      spd: speed          sight: provinces seen      cost: resource
    # mp: manpower to raise                  time: hours to raise          upkeep: resource per day
    # rough: attack multiplier in forest/hill/mountain              high: attack AND defence multiplier in hill/mountain
    # climb: movement-cost multiplier in hill/mountain   dig: fort-building speed   pierce: share of fort bonus ignored
    "inf": dict(atk=10, dfn=14, spd=1.0, sight=1, cost=30, mp=30, time=36, upkeep=0.30, rough=1.0, high=1.0, climb=1.0, dig=1.0, pierce=0.0),
    "mil": dict(atk=3,  dfn=10, spd=0.6, sight=1, cost=12, mp=25, time=18, upkeep=0.10, rough=1.0, high=1.0, climb=1.0, dig=1.0, pierce=0.0),
    "mtn": dict(atk=10, dfn=13, spd=1.0, sight=1, cost=40, mp=30, time=48, upkeep=0.35, rough=1.0, high=1.35, climb=0.55, dig=1.0, pierce=0.0),
    "mot": dict(atk=11, dfn=12, spd=2.0, sight=1, cost=55, mp=30, time=48, upkeep=0.45, rough=0.8, high=1.0, climb=1.4, dig=0.8, pierce=0.0),
    "arm": dict(atk=20, dfn=10, spd=2.0, sight=1, cost=70, mp=15, time=60, upkeep=0.60, rough=0.6, high=1.0, climb=1.6, dig=0.3, pierce=0.25),
    "art": dict(atk=16, dfn=5,  spd=0.7, sight=1, cost=50, mp=15, time=48, upkeep=0.45, rough=0.9, high=1.0, climb=1.2, dig=0.5, pierce=0.6),
    "eng": dict(atk=4,  dfn=8,  spd=1.0, sight=1, cost=40, mp=20, time=36, upkeep=0.30, rough=1.0, high=1.0, climb=1.0, dig=4.0, pierce=0.4),
    "rec": dict(atk=3,  dfn=6,  spd=4.0, sight=2, cost=20, mp=5,  time=18, upkeep=0.15, rough=1.0, high=1.0, climb=1.0, dig=0.3, pierce=0.0),
    # --- v5: more kinds, built from several resources (see EXTRA below for steel / oil / rare, armour and anti-armour)
    "cav": dict(atk=8,  dfn=9,  spd=2.4, sight=1, cost=28, mp=20, time=30, upkeep=0.28, rough=0.9, high=1.0, climb=1.1, dig=0.6, pierce=0.0),
    "grn": dict(atk=14, dfn=13, spd=1.0, sight=1, cost=40, mp=30, time=48, upkeep=0.38, rough=1.0, high=1.0, climb=1.0, dig=1.0, pierce=0.2),
    "atg": dict(atk=6,  dfn=10, spd=0.8, sight=1, cost=30, mp=12, time=36, upkeep=0.25, rough=1.0, high=1.0, climb=1.2, dig=0.8, pierce=0.0),
    "mec": dict(atk=12, dfn=15, spd=1.9, sight=1, cost=60, mp=28, time=54, upkeep=0.50, rough=0.8, high=1.0, climb=1.4, dig=0.8, pierce=0.1),
    "hvt": dict(atk=26, dfn=16, spd=1.3, sight=1, cost=95, mp=15, time=84, upkeep=0.90, rough=0.5, high=1.0, climb=1.8, dig=0.2, pierce=0.35),
    "rkt": dict(atk=20, dfn=4,  spd=1.4, sight=1, cost=70, mp=12, time=60, upkeep=0.55, rough=0.9, high=1.0, climb=1.3, dig=0.3, pierce=0.3),
    # --- v11: ships (dom 1: live in sea zones) and aircraft (dom 2: fly over anything). The numbers are the newest model; see ages.py
    "shp": dict(atk=24, dfn=20, spd=3.0, sight=2, cost=90, mp=15, time=96, upkeep=0.80, rough=1.0, high=1.0, climb=1.0, dig=0.0, pierce=0.3),
    "sub": dict(atk=22, dfn=8,  spd=2.2, sight=1, cost=60, mp=8,  time=72, upkeep=0.50, rough=1.0, high=1.0, climb=1.0, dig=0.0, pierce=0.0),
    "cvn": dict(atk=22, dfn=14, spd=2.8, sight=3, cost=150, mp=25, time=120, upkeep=1.40, rough=1.0, high=1.0, climb=1.0, dig=0.0, pierce=0.3),
    "ftr": dict(atk=14, dfn=9,  spd=12.0, sight=3, cost=70, mp=4,  time=60, upkeep=0.70, rough=1.0, high=1.0, climb=1.0, dig=0.0, pierce=0.0),
    "bmr": dict(atk=26, dfn=6,  spd=9.0, sight=2, cost=100, mp=6, time=72, upkeep=0.90, rough=0.9, high=1.0, climb=1.0, dig=0.0, pierce=0.5),
}
# Resources. `res` (general supplies and money) comes from every province; the other three only from deposits.
RES = ("res", "steel", "oil", "rare", "coal", "rubber")
STRAT = ("steel", "oil", "rare", "coal", "rubber")      # strategic resources: only from deposits, unevenly spread over the world
DEP_CODE = dict(steel="s", oil="o", rare="r", coal="k", rubber="u")      # letters used in province rows
# steel / oil / rare cost of a unit; hard = how armoured it is (0 soft .. 1 tank); ap = fire multiplier against a fully
# armoured target (fire at a target is x(1 + hard x (ap - 1))); supp = suppression multiplier of its fire
EXTRA = {
    "inf": dict(ap=0.5), "mil": dict(ap=0.4), "mtn": dict(ap=0.5), "rec": dict(ap=0.4), "cav": dict(ap=0.4),
    "eng": dict(steel=3, ap=0.7), "grn": dict(steel=8, ap=0.8),
    "mot": dict(steel=4, oil=6, ap=0.6), "art": dict(steel=10, ap=0.8, supp=2.5), "atg": dict(steel=10, ap=2.5),
    "arm": dict(steel=18, oil=8, hard=1.0, ap=1.0), "mec": dict(steel=12, oil=8, hard=0.5, ap=0.7),
    "hvt": dict(steel=30, oil=14, rare=2, hard=1.0, ap=1.3), "rkt": dict(steel=16, oil=8, rare=3, ap=0.7, supp=4.0),
    # dom: 0 land, 1 sea, 2 air.  vg / vs / va: fire multiplier against ground units / ships / aircraft (0 = cannot hit them at all)
    "shp": dict(steel=30, oil=10, hard=0.6, ap=1.0, dom=1, vg=0.6, vs=1.0, va=0.3), "sub": dict(steel=18, oil=8, ap=1.5, dom=1, vg=0.0, vs=1.3, va=0.0),
    "cvn": dict(steel=40, oil=16, rare=3, hard=0.4, ap=1.0, dom=1, vg=1.0, vs=1.0, va=0.6),
    "ftr": dict(steel=8, oil=10, rare=1, ap=0.6, dom=2, vg=0.35, vs=0.3, va=1.0), "bmr": dict(steel=12, oil=14, rare=1, ap=1.0, supp=3.0, dom=2, vg=1.0, vs=0.8, va=0.1),
}
for _c, _u in UNITS.items():
    _u.update(dict(steel=0, oil=0, rare=0, hard=0.0, ap=0.5, supp=1.0, dom=0, vg=1.0, vs=0.6 if _c in ("art", "rkt") else 0.2, va=0.0)); _u.update(EXTRA[_c])
DEPOSIT = dict(steel=(0.11, 2, 5), oil=(0.07, 2, 5), rare=(0.04, 1, 3), coal=(0.09, 2, 5), rubber=(0.05, 2, 4))      # share of land provinces with a deposit, daily yield range

# ---- upgrades (v5). A faction researches LINES; every line has up to TECH_LEVELS levels, each costing resources and
# time. What a faction cannot know: how far a line really goes for IT in THIS war. Each faction has its own hidden depth
# (0..TECH_LEVELS) for every line and a hidden size for every level. Researching a level beyond the depth is a DEAD END:
# the resources are gone and the line is closed. Nothing shows the depth or the sizes in advance, to anyone.
TECH_LEVELS = 3
TECH_SLOTS = 2                           # projects a faction can run at once
TECH_HOURS = 96                          # level L takes L x this
TECH_DEPTH = (0.22, 0.26, 0.28, 0.24)    # hidden: chance that a line is good for 0, 1, 2, 3 levels
TECH_SIZE = (0.06, 0.16)                 # hidden: each successful level is worth this much (uniform)
# per unit type: three lines. cost of level L = L x these amounts
# v8: every line NEEDS strategic resources, more kinds the further it goes: level 1 takes the first kind of `needs`, level 2 the
# first two, level 3 all three (each amount x level). What a level costs is known to everyone; whether it works is not.
TECH_UNIT = dict(weapons=dict(stat="atk", cost=dict(res=60), needs=(("steel", 25), ("coal", 20), ("rare", 6))),
                 protection=dict(stat="dfn", cost=dict(res=50), needs=(("steel", 35), ("rubber", 12), ("coal", 15))),
                 mobility=dict(stat="spd", cost=dict(res=50), needs=(("oil", 30), ("rubber", 15), ("steel", 15))))
# general lines: what they would improve, and the cost of level L = L x these amounts
TECH_GENERAL = dict(
    farming=dict(what="res yield of every province", cost=dict(res=90), needs=(("coal", 15), ("oil", 12), ("rare", 4))),
    mining=dict(what="steel yield of deposits", cost=dict(res=60), needs=(("steel", 20), ("coal", 15), ("rubber", 8))),
    drilling=dict(what="oil yield of deposits", cost=dict(res=60), needs=(("oil", 20), ("steel", 15), ("rare", 4))),
    refining=dict(what="rare yield of deposits", cost=dict(res=60), needs=(("rare", 8), ("coal", 15), ("oil", 12))),
    conscription=dict(what="manpower yield", cost=dict(res=80), needs=(("coal", 12), ("rubber", 8), ("steel", 15))),
    logistics=dict(what="supplies flowing into your provinces", cost=dict(res=70), needs=(("oil", 20), ("rubber", 12), ("coal", 15))),
    medicine=dict(what="how fast units regain strength", cost=dict(res=70), needs=(("rare", 6), ("rubber", 8), ("oil", 12))),
    drill=dict(what="experience of newly raised units", cost=dict(res=80), needs=(("steel", 15), ("oil", 12), ("rubber", 8))),
    fieldworks=dict(what="fort building speed", cost=dict(res=50), needs=(("steel", 25), ("coal", 15), ("rare", 4))),
    discipline=dict(what="morale of newly raised units and morale recovery", cost=dict(res=80), needs=(("coal", 12), ("rare", 4), ("rubber", 8))),
    industry=dict(what="res cost of every unit (cheaper)", cost=dict(res=100), needs=(("coal", 20), ("steel", 20), ("rare", 6))),
    staffwork=dict(what="how fast a prepared attack builds its bonus", cost=dict(res=70), needs=(("rare", 10), ("oil", 12), ("coal", 12))),
)

NOTES = dict(inf="line infantry", mil="militia: cheap, slow, holds ground only", mtn="mountain troops: fast and x1.35 in hill/mountain",
             mot="motorised: fast on open ground", arm="armour: breakthrough on plains, poor in rough ground",
             art="artillery: strong attack, ignores 60% of forts, fragile", eng="engineers: dig forts 4x faster, ignore 40% of forts",
             rec="scout: very fast, sight 2, exact enemy counts; cannot take or hold a province",
             cav="cavalry: fast, cheap, needs no oil, weak against armour", grn="assault infantry: strong attack, ignores 20% of forts",
             atg="anti-tank guns: weak fire, but x2.5 against armour", mec="mechanised infantry: fast, half armoured",
             hvt="heavy armour: very strong, fully armoured, slow and costly, poor in rough ground",
             rkt="rocket artillery: range 10, heavy suppression, ignores 30% of forts, fragile",
             shp="warship: fights ships, shells the coast, cuts enemy sea supply and sinks troops at sea", sub="submarine: strong against ships, cannot hit land",
             cvn="aircraft carrier: its air group reaches 10 cells against ships, land and aircraft", ftr="fighter: shoots down aircraft, strafes a little, sight 3",
             bmr="bomber: heavy fire on ground units and ships far behind the front, ignores 50% of forts")
FACTIONS = {
    "aurum": dict(blurb="Aurum Compact: defence +10%, speed -10%.",
                  names=dict(inf="Line Brigade", mil="Levy", mtn="Crag Guard", mot="Road Legion", arm="Iron Column",
                             art="Siege Battery", eng="Sapper Corps", rec="Outrider")),
    "sable": dict(blurb="Sable Drift: speed +10%, units 10% cheaper, defence -5%.",
                  names=dict(inf="Drift Band", mil="Hearth Watch", mtn="Ridge Stalker", mot="Swift Host", arm="Storm Wedge",
                             art="Thunder Crew", eng="Delver", rec="Shade Rider")),
    "cinder": dict(blurb="Cinder Reach: attack +10%, units 5% dearer.",
                   names=dict(inf="Ember Cohort", mil="Ash Guard", mtn="Slag Climber", mot="Kiln Runner", arm="Forge Ram",
                              art="Furnace Train", eng="Smelter Gang", rec="Spark Scout")),
}
# The world map (ridgeline/worldgen.py): about 30 factions, each starting around a real city. Names are old regional
# names, not present-day states. (faction, capital city, latitude, longitude, doctrine)
WORLD = [
    ("cascadia", "Seattle", 47.6, -122.3, "drift"), ("laurentia", "New York", 40.7, -74.0, "guard"), ("anahuac", "Mexico City", 19.4, -99.1, "levy"),
    ("granada", "Bogota", 4.7, -74.1, "bulwark"), ("andea", "Lima", -12.0, -77.0, "ember"), ("amazonia", "Brasilia", -15.8, -47.9, "levy"),
    ("platina", "Buenos Aires", -34.6, -58.4, "drift"), ("albion", "London", 51.5, -0.1, "guard"), ("gallia", "Paris", 48.9, 2.3, "bulwark"),
    ("iberia", "Madrid", 40.4, -3.7, "ember"), ("germania", "Berlin", 52.5, 13.4, "drift"), ("scandia", "Stockholm", 59.3, 18.1, "bulwark"),
    ("sarmatia", "Kyiv", 50.4, 30.5, "levy"), ("muscovy", "Moscow", 55.8, 37.6, "ember"), ("anatolia", "Ankara", 39.9, 32.9, "guard"),
    ("maghreb", "Algiers", 36.7, 3.1, "drift"), ("nilotica", "Cairo", 30.0, 31.2, "bulwark"), ("sahelia", "Kano", 12.0, 8.5, "levy"),
    ("abyssinia", "Addis Ababa", 9.0, 38.7, "bulwark"), ("kongo", "Kinshasa", -4.3, 15.3, "ember"), ("austral", "Johannesburg", -26.2, 28.0, "guard"),
    ("persia", "Tehran", 35.7, 51.4, "ember"), ("arabia", "Riyadh", 24.7, 46.7, "drift"), ("hindustan", "Delhi", 28.6, 77.2, "levy"),
    ("turan", "Tashkent", 41.3, 69.2, "drift"), ("siberia", "Novosibirsk", 55.0, 82.9, "bulwark"), ("zhongyuan", "Beijing", 39.9, 116.4, "levy"),
    ("yamato", "Tokyo", 35.7, 139.7, "guard"), ("nusantara", "Jakarta", -6.2, 106.8, "ember"), ("oceania", "Sydney", -33.9, 151.2, "drift"),
    ("haedong", "Hanseong", 37.6, 127.0, "bulwark"),
]
DOCTRINES = dict(bulwark="defence +10%, speed -10%", drift="speed +10%, units 10% cheaper, defence -5%", ember="attack +10%, units 5% dearer",
                 levy="units need 20% less manpower, attack -5%", guard="new units start with +15 experience, units 10% dearer")
HARSH_COST = 6          # extra move-hours in desert and tundra; supplies also arrive at half speed there
AMPHIB = 0.7            # attack multiplier when firing across a sea link (strait or sea lane)
DMG_K = 0.10            # battle damage scale per hour
RETREAT_AT = 20         # strength below which a unit breaks off
REINFORCE = 0.25        # strength regained per hour in supplied home territory (uses manpower)
ATTRITION = 0.30        # strength lost per hour when out of supply
UNSUPPLIED_MULT = 0.7   # attack/defence when out of supply
SKIRMISH = 0.2          # share of attack power exchanged automatically across every contact border, each hour
UPHILL = 0.90; DOWNHILL = 1.08; FLANK = 0.10      # attack multiplier PER LEVEL of height difference (4 levels, 0..3)
# --- preparing an offensive -------------------------------------------------------------------------------
STOCK_CAP = 660; STOCK_CAP_CITY = 1320      # supplies a province can hold
STOCK_FLOW = 10.0; STOCK_HOP = 0.2          # hourly inflow = FLOW / (1 + HOP * provinces from the capital)
USE_IDLE = 0.02; USE_CONTACT = 0.04; USE_DEFEND = 0.20; USE_ASSAULT = 0.50     # supplies a unit burns per hour
DRY_MULT = 0.5                             # attack power when the province's stock is empty
RDY_REST = 1.0; RDY_CONTACT = 0.8; RDY_MOVE = -0.5; RDY_ASSAULT = -1.5; RDY_DEFEND = -0.6   # readiness change per hour
RDY_ATK = 0.6; RDY_DFN = 0.3               # attack = x(1-RDY_ATK + RDY_ATK*rdy/100); defence likewise with RDY_DFN
RDY_NEW = 50                               # readiness of a freshly raised unit
PLAN_RATE = 1.0; PLAN_MAX = 50; PLAN_MAX_EXACT = 75; PLAN_DECAY = 1.0   # prepared attack: +% per hour waiting, cap, cap with exact intel, loss per hour attacking
FORT_MAX = 3            # fort levels: trench, bunker line, fortress
FORT_DFN = 0.25         # each level: defenders take 1/(1+0.25*L) damage (less the attacker's pierce) ...
FORT_FIRE = 0.10        # ... and return +10% fire per level
FORT_HOURS = 150        # unit-hours (dig 1.0) for level 1; level L costs L times that
XP_NEW = dict(mil=0)    # experience of a freshly raised unit (default 10)
FORT_NAMES = ("none", "trench", "bunkers", "fortress")


GENERIC = dict(inf="Infantry", mil="Militia", mtn="Mountain Troops", mot="Motorised", arm="Armour", art="Artillery", eng="Engineers", rec="Scouts",
               cav="Cavalry", grn="Assault Infantry", atg="Anti-tank Guns", mec="Mechanised Infantry", hvt="Heavy Armour", rkt="Rocket Artillery",
               shp="Warship", sub="Submarine", cvn="Carrier", ftr="Fighter", bmr="Bomber")
for _w in WORLD:
    FACTIONS[_w[0]] = dict(blurb="%s (capital %s): %s." % (_w[0].capitalize(), _w[1], DOCTRINES[_w[4]]), names=GENERIC, doctrine=_w[4])
FACTIONS["aurum"]["doctrine"] = "bulwark"; FACTIONS["sable"]["doctrine"] = "drift"; FACTIONS["cinder"]["doctrine"] = "ember"


def stats_for(faction):
    out = {}; fname = faction; faction = FACTIONS[faction]["doctrine"]
    for code, base in UNITS.items():
        s = dict(base); s["code"] = code; s["xp0"] = XP_NEW.get(code, 10)
        if faction == "levy": s["mp"] = int(round(s["mp"] * 0.8)); s["atk"] = round(s["atk"] * 0.95, 1)
        elif faction == "guard": s["xp0"] += 15; s["cost"] = int(round(s["cost"] * 1.1))
        if faction == "bulwark":
            s["dfn"] = round(s["dfn"] * 1.1, 1); s["spd"] = round(s["spd"] * 0.9, 2)
        elif faction == "drift":
            s["spd"] = round(s["spd"] * 1.1, 2); s["cost"] = int(round(s["cost"] * 0.9)); s["dfn"] = round(s["dfn"] * 0.95, 1)
        elif faction == "ember":
            s["atk"] = round(s["atk"] * 1.1, 1); s["cost"] = int(round(s["cost"] * 1.05))
        s["cost"] = max(1, int(round(s["cost"] * UNIT_SCALE))); s["mp"] = max(1, int(round(s["mp"] * UNIT_SCALE))); s["upkeep"] = round(s["upkeep"] * UNIT_SCALE, 3)
        for k in ("steel", "oil", "rare"): s[k] = int(round(s[k] * UNIT_SCALE)) if s[k] else 0
        s["range"] = RANGE[code]; s["fuel"] = FUEL.get(code, 0.0); s["gen"] = 0
        s["name"] = FACTIONS[fname]["names"].get(code, GENERIC[code])
        out[code] = s
    return out

# Combat frontage (force-to-space): only so many units can fight across one border at once. Per attack direction the
# FRONTAGE[target terrain] strongest units fight at full weight, the rest only as SUPPORT. Artillery fires over
# the line and is never crowded out. Defenders get the same width per attacked direction plus FRONT_DEPTH.
FRONTAGE = {"plain": 5, "forest": 4, "hill": 3, "mountain": 2}
SUPPORT = 0.25
FRONT_DEPTH = 2

# ---- unit-level movement and fire (v3). Distances are in map cells; neighbouring key points are about SPAN apart.
RANGE = dict(inf=3.0, mil=2.5, mtn=3.0, mot=3.0, arm=3.5, art=9.0, eng=2.5, rec=3.0, cav=2.5, grn=3.0, atg=4.0, mec=3.0, hvt=3.5, rkt=10.0, shp=6.0, sub=3.0, cvn=10.0, ftr=4.0, bmr=4.0)    # firing range of each unit type
SPAN = 5.7              # a unit crosses SPAN cells in the province's move-cost hours
SLOT = 0.45             # spacing of units formed up around a point (cells): big groups take up real room
CAP_R = 1.5             # a unit this close to a province's key point holds it...
TARGETS = 3             # a unit splits its fire over at most this many nearest enemies
HOLD_FIRE = 0.8         # a unit standing its ground fires with max(atk, HOLD_FIRE * dfn)

# ---- the state of each unit (v4). Real armies are not interchangeable counters: the same battalion fights very
# differently green or seasoned, rested or worn, steady or shaken, free or pinned down.
# experience 0-100 (green < 20 <= trained < 40 <= regular < 60 <= veteran < 80 <= elite)
XP_LEVELS = ("green", "trained", "regular", "veteran", "elite")
XP_ATK0 = 0.85; XP_ATK = 0.35           # fire power x(0.85 + 0.35*xp/100): green 0.85 ... elite 1.20
XP_DFN0 = 0.90; XP_DFN = 0.30           # damage taken divided by (0.90 + 0.30*xp/100)
XP_ASSAULT = 0.12; XP_DEFEND = 0.08     # gained per hour of firing (x(1.2 - xp/100): slower near the top)
XP_KILL = 3.0                           # destroying an enemy unit
XP_TRAIN = 0.02; XP_TRAIN_CAP = 30      # drill while resting at home: slow, and only up to 'trained'
XP_REPL = 10                            # experience of replacements: refilling a mauled unit dilutes what it learned
# morale 0-100
MOR_NEW = 70
MOR_DMG = 0.6                           # lost per point of strength lost ...
MOR_VET = 0.4                           # ... less for experienced units: x(1 - 0.4*xp/100)
MOR_SHOCK = 3.0                         # a friendly unit destroyed in the same province
MOR_BREAK = 15; MOR_SHAKEN = 35         # below BREAK the unit runs even if it still has men
MOR_RALLY = 25                          # a routed unit that reaches the rear pulls itself together to at least this
MOR_SURRENDER = 8                       # surrounded, unsupplied and below this: it surrenders
MOR_REST = 0.5; MOR_CONTACT = 0.1       # recovered per hour resting / in contact but not under fire
MOR_CUT = 0.4; MOR_DRY = 0.2            # lost per hour cut off from supply / with the depot empty
MOR_KILL = 4.0; MOR_WIN = 5.0           # destroying an enemy unit; taking a province from an enemy
MOR_ATK = 0.25                          # fire power x(0.75 + 0.25*morale/100)
# suppression 0-100: incoming fire pins a unit down
SUP_K = 8.0; SUP_ART = 2.5              # gained per point of damage taken (artillery x2.5)
SUP_DECAY = 0.5                         # halves every hour
SUP_FIRE = 0.5                          # fire power x(1 - 0.5*suppression/100)
# formation experience 0-100 per named group (Player.fxp): units that keep fighting side by side
FORM_MIN = 3                            # at least this many of the group in the same province to count as fighting together
FORM_GAIN = 0.06                        # per hour in which the formation fights (full rate from 10 firing units)
FORM_ATK = 0.15                         # fire power x(1 + 0.15*fxp/100)
FORM_MOR = 0.3                          # morale loss x(1 - 0.3*fxp/100)
# ---- scale: one unit is a small element, so armies are large
UNIT_SCALE = 0.3                        # cost, manpower and upkeep of every unit are multiplied by this
BUCKET = 5.0                            # spatial hash cell (map cells)
SLICES = 8                              # calm units are updated every SLICES hours, for SLICES hours at once

# re-equipping a unit in the field to its type's current model: share of the unit's price (res and special resources), and the readiness lost while it retrains
REFIT_COST = 0.35
REFIT_RDY = 30

# diplomacy (mechanics only; what to offer, accept or break is each faction's business)
GIVE = ("res", "mp", "steel", "oil", "rare", "coal", "rubber")     # what can change hands in a gift or a trade
PACT_NOTICE = 24        # hours between breaking a pact and the first shot
OFFER_HOURS = 72        # an unanswered offer lapses
OFFERS_OPEN = 3         # open offers per pair, per sender
MAIL_LEN = 300; MAIL_KEEP = 40; MAIL_PER_DAY = 4

# v6, from how real fronts behave (see README "역사에서 가져온 것")
MOR_FLANK = 6.0         # morale lost by units next to a province their side has just lost: an open flank unsettles the neighbours
LOOT_MP = 0.25          # share of a fallen faction's manpower pool the victor can press into service (its res and stockpiles go over whole)
PACT_MAX = 0            # 0 = no upper limit: how long a pact runs is for the two factions to decide (0 hours in an offer = until broken)
PACT_RENEW = 96
FLANK_COVER = (0.65, 0.4)   # share of terrain and fort cover that still counts when a province is assaulted from 2 / 3+ directions

# v7: where a faction keeps its treasury and where its supply starts is its own choice (depots); the physical limits are below
DEPOT_COST = 150        # res to set up a depot in a province of yours
DEPOT_HOURS = 48        # hours until it works
DEPOT_SHIFT = 0.02      # share of the whole treasury that can be carried between depots per hour
HUB_LOAD = 30.0; HUB_LOAD_CITY = 60.0     # what one depot can push out at full rate: the sum over the provinces it serves of 1/(1 + STOCK_HOP x steps); beyond that all get proportionally less

# v8: engines need fuel. Oil burned per day by every unit of these types (already x UNIT_SCALE); with the oil stock at zero they
# fire at FUEL_OUT of their power and do not regain readiness.
FUEL = dict(mot=0.02, arm=0.05, mec=0.04, hvt=0.07, rkt=0.03, shp=0.08, sub=0.04, cvn=0.12, ftr=0.06, bmr=0.09)
FUEL_OUT = 0.6
DEAL_MAX = 6            # standing deliveries a faction can have running with one other faction
TRUCE_HOURS = 48        # when land changes hands by agreement, the two sides do not fight for this long (time to march out)

# v8 environment. A year is 4 x SEASON_DAYS days and a war starts in spring; south of the equator the seasons are reversed.
SEASON_DAYS = 24
SEASONS = ("spring", "summer", "autumn", "winter")
COLD_LAT = 36.0         # beyond this latitude the land freezes in winter; tundra is frozen in every season but summer; high mountains (elev 3) beyond 25 freeze in winter
COLD_MOVE = 1.5         # move-hours multiplier on frozen ground
COLD_FLOW = 0.6         # supplies arriving in a frozen province
FROST = 0.12            # strength lost per hour by a unit on frozen ground that is not its own supplied land ...
HARDY = 0.35            # ... times this for factions whose capital lies beyond HARDY_LAT (they know winter)
HARDY_LAT = 50.0
JUNGLE_LAT = 15.0       # forest within this latitude is jungle
FEVER = 0.06            # strength lost per hour in jungle by units of factions from outside the tropics (capital beyond TROPIC_LAT) off their own supplied land; divided by the medicine multiplier
TROPIC_LAT = 23.5
SEA_HOPS = 4            # a sea link counts as this many steps for supply (shipping), and supplies do not cross it at all into a frozen harbour


# ---- economy (v9): cities grow, wealth follows how developed and how well connected a region is -------------------------
DEV_MAX = 6.0; INFRA_MAX = 3.0
DEV_COST = 50; DEV_NEED = ("coal", 8); DEV_HOURS = 72       # one more level of development: cost and need are multiplied by the level being built
INFRA_COST = 30; INFRA_NEED = ("steel", 6); INFRA_HOURS = 48  # one more level of roads and rail, likewise
DEV_START_CITY = 1.0; DEV_START_CAPITAL = 2.0
DEV_Y = 0.30; DEV_FLAT = 0.8; DEV_MP = 0.15                 # yield = (base * (1 + DEV_Y * d) + DEV_FLAT * d) * agglomeration; manpower * (1 + DEV_MP * d)
DEV_ROOM = 2.0; DEV_ROOM_INFRA = 1.5; DEV_ROOM_RURAL = -1.0  # development a province can carry before it chokes: ROOM + ROOM_INFRA * infrastructure (a non-city has ROOM_RURAL less)
DEV_CHOKE = 0.3                                             # what each level beyond that room is still worth
AGG = 0.18                                                  # agglomeration = 1 + AGG * ln(1 + market)
LINK = 0.15; LINK_INFRA = 0.25                              # how much of a neighbour's development counts towards your market: LINK + LINK_INFRA * min(infrastructure of the two)
DEV_KEEP = 0.12; INFRA_KEEP = 0.15                          # res a day: DEV_KEEP * d^2 per province, INFRA_KEEP per infrastructure level
DEV_GROW = 0.02                                             # organic growth a day = DEV_GROW * (agglomeration - 1) * free room share
DEV_DECAY = 0.01                                            # lost a day when the upkeep cannot be paid
DEV_SACK = 0.6; INFRA_SACK = 0.75                           # what is left after a province is taken by force
DEV_BATTLE = 0.004                                          # development lost per hour while a battle is fought in the province
INFRA_MOVE = 0.2; INFRA_HOP = 0.5; INFRA_HUB = 0.25         # movement cost / (1 + MOVE * L); supply distance of a province / (1 + HOP * L); depot capacity * (1 + HUB * L)

# --- v10: great rivers (world map). A border a river runs through is a river border (Prov.river)
RIVER_ATK = 0.65        # fire of an ADVANCING unit at targets on the far bank (an opposed crossing); units holding their bank fire normally
RIVER_MOVE = 0.45       # speed of a unit on its way to the far bank (finding boats, building bridges)
RIVER_BRIDGE = 1        # infrastructure level on both banks, both yours, at which your own units cross at normal speed (bridges; blown when a bank is lost)
RDY_MARCH = -0.15       # readiness per hour marching through your own supplied land, out of contact (an administrative march); RDY_MOVE applies everywhere else
RDY_RAIL = 0.0          # ... and where that province has infrastructure 1 or more (troops moved by rail arrive fresh)
FORT_DECAY = 0.08       # fort levels lost per day in a province where no unit of its owner stands (unmanned works fall in)

# ---- v11: sea and air
SEA_COST = 9.0            # move cost of a sea zone (hours for speed 1; a zone is about 26 cells across)
AIR_COST = 6.0            # the same for aircraft, over any ground
EMBARK = 10.0             # extra hours to load troops on ships / land them
SEA_SUPPLY_HOP = 2.0      # a sea zone counts as this many steps for supply carried by ship
AT_SEA_DFN = 0.25         # troops on transports: helpless (cannot fire, this share of their defence)
WAR_HOURS = 720           # two factions count as at war for this long after the last real attack, strike or declaration between them
AIR_BURN = 4.0            # readiness an aircraft burns per hour away from its base (it turns back at AIR_HOME)
AIR_REST = 5.0            # readiness regained per hour on the ground at its base
AIR_HOME = 35
STRIKE = dict(res=260, oil=40, rare=12)      # one long-range missile
STRIKE_HOURS = 6; STRIKE_DMG = 22.0          # hours of flight; strength taken from every unit in the province (forts halve it)

# --- roads and railways: links between two neighbouring provinces (v13) ---
ROAD_COST = 12; ROAD_HOURS = 36                              # res per stretch (x the ground's movement cost, x LINK_RIVER across a river: a bridge)
RAIL_COST = 40; RAIL_NEED = ("steel", 8); RAIL_HOURS = 72    # likewise; a railway replaces the road on that stretch
LINK_RIVER = 2.0; LINK_GROUND = 16.0                         # prices are for open plain (movement cost 16); other ground costs in proportion (mountain about x2.75)
ROAD_KEEP = 0.03; RAIL_KEEP = 0.10                           # res a day per stretch
ROAD_MOVE = 1.5; RAIL_MOVE = 4.0                             # land units move this much faster along the stretch (rail: only its owner's and access partners' units, out of contact)
ROAD_HOP = 0.6; RAIL_HOP = 0.3                               # a supply step along the stretch counts this much
LINK_ROAD = 0.10; LINK_RAIL = 0.25                           # added to how much of the neighbour's development counts towards your market
LINK_NEED = dict(road="roads", rail="railways")              # the discovery each kind needs (on maps with the tree)

# --- local peoples: land no faction owns is not empty (v14) ---
LOCAL_BASE = 2.0; LOCAL_CITY = 4.0; LOCAL_HARSH = 0.5        # militia a free province can call out, in units' worth (x100 strength): base, more around a city, x this in desert / tundra / jungle
LOCAL_SPREAD = (0.6, 1.4)                                    # drawn per province and war
LOCAL_ATK = 8.0; LOCAL_DFN = 12.0                            # per 100 strength, x the nominal power of the locals' age, defence also x terrain cover
LOCAL_LAG = 2                                                # the locals' weapons are this many ages behind the median faction (never before ancient)
LOCAL_JOIN = 240.0                                           # years for a free province to join a neighbouring faction of the locals' own age; / (1 + ages that faction is ahead)^2
LOCAL_JOIN_SHARE = 0.5                                       # pull = this + (1 - this) x the share of the province's land neighbours the faction owns
LOCAL_CUT = 30.0                                             # years an ungarrisoned province stays yours while cut off from all your depots; then it goes to the neighbour holding most land around it, or to its own people
LOCAL_HEAL = 0.04                                            # share of their full strength they regain a day when no intruder stands on their land
