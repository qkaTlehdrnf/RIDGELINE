"""Unit / structure tables. All names and numbers are original to this project.

Time unit: 1 tick = 0.1 s.  Distances are in tiles.
Codes are shared by both factions; factions differ by modifiers below.
"""
TICKS_PER_SEC = 10

UNITS = {
    #        hp  dmg rng  min cd  spd   sight cost time sup armor aa   splash
    "wrk": dict(hp=40, dmg=5, rng=1.0, minr=0, cd=15, spd=0.28, sight=6, cost=50, time=120, sup=1, armor=0, aa=False, splash=0),
    "inf": dict(hp=55, dmg=7, rng=5.0, minr=0, cd=10, spd=0.30, sight=8, cost=50, time=180, sup=1, armor=0, aa=True, splash=0),
    "hvy": dict(hp=150, dmg=16, rng=1.0, minr=0, cd=15, spd=0.26, sight=7, cost=100, time=250, sup=2, armor=2, aa=False, splash=0),
    "art": dict(hp=80, dmg=30, rng=9.0, minr=2.5, cd=30, spd=0.20, sight=8, cost=150, time=350, sup=3, armor=0, aa=False, splash=1.2),
    "fly": dict(hp=70, dmg=0, rng=0.0, minr=0, cd=10, spd=0.40, sight=10, cost=75, time=200, sup=1, armor=0, aa=False, splash=0, fly=True),
}
STRUCTS = {
    "hq":  dict(hp=1200, size=3, cost=400, time=900, sight=9, supply=12, trains=("wrk",), req=None),
    "dep": dict(hp=300, size=2, cost=100, time=250, sight=5, supply=8, trains=(), req=None),
    "bar": dict(hp=800, size=3, cost=150, time=450, sight=7, supply=0, trains=("inf", "hvy"), req=None),
    "wks": dict(hp=800, size=3, cost=200, time=550, sight=7, supply=0, trains=("art", "fly"), req="bar"),
    "tow": dict(hp=400, size=2, cost=125, time=350, sight=10, supply=0, trains=(), req="bar",
                dmg=12, rng=7.0, minr=0, cd=12, aa=True, splash=0, eye_bonus=1),
}
for _s in STRUCTS.values():
    _s.setdefault("dmg", 0); _s.setdefault("armor", 1); _s["struct"] = True; _s.setdefault("eye_bonus", 0)
for _u in UNITS.values():
    _u.setdefault("fly", False); _u["struct"] = False

FACTIONS = {
    "aurum": dict(
        blurb="Aurum Compact: heavier and slower. +10% hp, -5% speed, hvy armor 3, art splash 1.5.",
        names=dict(wrk="Hauler", inf="Lancer", hvy="Bastion", art="Thumper", fly="Lantern",
                   hq="Keep", dep="Cache", bar="Muster", wks="Foundry", tow="Spire"),
    ),
    "sable": dict(
        blurb="Sable Drift: lighter and faster. -10% hp, +10% speed, combat units 10% cheaper and 10% faster to train, fly has a weak gun (4 dmg, range 3, hits air).",
        names=dict(wrk="Gleaner", inf="Stinger", hvy="Mauler", art="Lobber", fly="Wisp",
                   hq="Burrow", dep="Stash", bar="Warren", wks="Kiln", tow="Thorn"),
    ),
}
MINE_TICKS = 20      # ticks to mine one load
MINE_LOAD = 5
ORE_PER_PATCH = 1500
UPHILL_MULT = 0.75   # ranged damage when shooting at a higher tile
REVEAL_TICKS = 20    # a unit that fires is visible to everyone for this long
MAX_QUEUE = 5
START_ORE = 50
START_WORKERS = 6


def stats_for(faction):
    """Return {code: stats} with faction modifiers applied."""
    out = {}
    for code, base in list(UNITS.items()) + list(STRUCTS.items()):
        s = dict(base); s["code"] = code
        if not s["struct"]:
            if faction == "aurum":
                s["hp"] = round(s["hp"] * 1.1); s["spd"] = round(s["spd"] * 0.95, 3)
                if code == "hvy": s["armor"] = 3
                if code == "art": s["splash"] = 1.5
            elif faction == "sable":
                s["hp"] = round(s["hp"] * 0.9); s["spd"] = round(s["spd"] * 1.1, 3)
                if code != "wrk":
                    s["cost"] = int(round(s["cost"] * 0.9 / 5) * 5); s["time"] = int(s["time"] * 0.9)
                if code == "fly": s.update(dmg=4, rng=3.0, aa=True)
        s["name"] = FACTIONS[faction]["names"][code]
        out[code] = s
    return out
