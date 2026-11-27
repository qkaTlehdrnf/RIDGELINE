"""Agent-facing interface for Ridgeline v2: one Session per player.

  brief()          rules + province table + command grammar; send once (cacheable prefix).
  obs("full")      compact text of everything the player knows.
  obs("delta")     only lines that changed since the last obs() call, plus new events.
  act(text)        command lines -> terse result.
  query(text)      on-demand detail.
  set_policy(...)  install/replace a standing-order program (python, tick(api)) that runs inside the engine.
  obs_json()       verbose structured state (baseline for token comparison / tooling).

Two ways to drive units, usable together:
  1. policy: a program written before the game (or rewritten during it) that issues orders every few hours.
  2. live commands: an agent that looks at the delta every few seconds and overrides or redirects.
"""
import math
import re
import time

from . import data as D
from . import ages as A
from .mapgen import ascii_map

CODES = tuple(D.UNITS)


def _need(d):
    return "%s + %s" % (_cost(d["cost"]), " > ".join("%s %d" % kv for kv in d["needs"]))

def _cost(c): return "+".join("%d %s" % (v, k) for k, v in c.items())


def _ids(ids):
    ids = sorted(ids); out = []; i = 0
    while i < len(ids):
        j = i
        while j + 1 < len(ids) and ids[j + 1] == ids[j] + 1: j += 1
        out.append(str(ids[i]) if i == j else "%d-%d" % (ids[i], ids[j]))
        i = j + 1
    return ",".join(out)


def _counts(c):
    return " ".join("%s×%d" % (k, c[k]) for k in CODES if k in c)


class CmdError(Exception):
    pass


class Session:
    def __init__(self, game, pid):
        self.g = game; self.pid = pid; self.p = game.players[pid]
        self._last = {}; self._ev = 0
        self.policies = {}
        self.model = {}             # learned parameters (plain JSON data) handed to policies as api.model
        self.front = set()          # unit ids under the automatic front-line order
        self.resting = set()        # front units pulled back to recover
        self.counters = {}          # the policy's own tallies (api.count): shown back to the faction in its review
        self.expand = set()         # unit ids under the standing order to keep taking neutral land
        self.expand_x = 3.0         # a party sent against a free province is this many times the strength of the people seen there
        self.expand_to = {}         # unit id -> province the commander picked as the area to expand around
        self.explore = set()        # unit ids under the standing order to go and look at unexplored land
        self.no_go = set()          # unexplored provinces that turned out unreachable (water)
        self.neutral_border = []
        self.policy_budget_ms = 25.0
        self.stats = dict(cmds=0, errors=0); self.rejects = {}; self.verbs = {}
        self.multi = len(game.players) > 2
        self.sources = {}           # installed policy name -> (code, every)
        self.candidates = {}        # strategies a commander has drafted for trials: name -> (code, every)

    # ============================================================ brief
    def brief(self):
        g, p = self.g, self.p; eps = [e for e in g.players if e.id != self.pid]; L = []
        L.append("RIDGELINE. You are P%d (%s) against %s. Every faction fights every other; there are no alliances." % (
            self.pid, p.faction, (" and " if len(eps) < 4 else ", ").join("P%d (%s)" % (e.id, e.faction) for e in eps)))
        if len(eps) < 4: L.append(" ".join(D.FACTIONS[e.faction]["blurb"] for e in [p] + eps))
        else:
            L.append("You: " + D.FACTIONS[p.faction]["blurb"] + " Doctrines of the others: " + "; ".join(
                "%s = %s (%s)" % (d, D.DOCTRINES[d], " ".join("P%d" % e.id for e in eps if D.FACTIONS[e.faction]["doctrine"] == d))
                for d in D.DOCTRINES if any(D.FACTIONS[e.faction]["doctrine"] == d for e in eps)) + ".")
        if g.map.world:
            L.append("THE MAP IS THE REAL WORLD (coastlines, great mountain ranges, deserts, tundra). Land masses are joined by SEA LINKS "
                     "(straits and sea lanes, marked ~ in a province's neighbour list): units cross them like any border, only slower "
                     "over long water, supply and sight pass over them, and fire across a sea link is x%.1f (a landing). Desert and "
                     "tundra (d, t after the terrain letter) are harsh: +%d move-hours, almost no yield, no manpower, supplies arrive at half speed."
                     % (D.AMPHIB, D.HARSH_COST))
            L.append("GREAT RIVERS run where they really do (Rhine, Danube, Dnieper, Volga, Nile, Yangtze, Yalu, Mississippi, Amazon and some fifty more). A border a river runs through is a "
                     "RIVER BORDER (marked = in a province's neighbour list; api.provs[id]['river'] lists the neighbours on the far bank). A unit on its way across moves at x%.2f speed until it is over, "
                     "and an advancing unit fires at x%.2f at targets on the far bank; units holding their own bank fire normally, and a unit falling back across a river is as slow as one attacking across it. "
                     "A river is no obstacle while both banks are frozen (winter in the cold latitudes), and your own units cross at normal speed where both banks are yours and both have infrastructure %d or more (bridges)."
                     % (D.RIVER_MOVE, D.RIVER_ATK, D.RIVER_BRIDGE))
        L.append("TIME 1 tick = 1 hour, 24 = 1 day. The game runs in real time and does not wait for you.")
        if g.ages: L += self._brief_ages()
        L.append("MAP is a graph of provinces. Owning a province that connects to one of your depots through your own provinces "
                 "(a supply line) pays its yield every day. Cut-off provinces pay nothing.")
        L.append("ECONOMY: every province has a development level (0-%g; cities start at %g, capitals at %g) and an infrastructure level (roads and rail, 0-%g). "
                 "A province yields (base x (1 + %.2f x d) + %.1f x d) x agglomeration res a day and base x (1 + %.2f x d) manpower, where d is its development. "
                 "Agglomeration = 1 + %.2f x ln(1 + market); a province's market is its own development plus its neighbours' and their neighbours', each step counted at "
                 "%.2f + %.2f x (the lower infrastructure level of the two provinces), and only across land of one owner or of owners who have opened their roads to each other. "
                 "A province can carry only so much development: %g + %.1f x infrastructure (%g less outside a city); each level beyond that counts %.1f. "
                 "`develop P<id>` adds one development level (%d res and %d %s, times the level being built, %d h); `build P<id>` adds one infrastructure level (%d res and %d %s, times the level, %d h). "
                 "Upkeep every day: %.2f x d^2 res per province and %.2f res per infrastructure level; if your treasury is empty and you cannot pay, both decay. "
                 "Developed provinces with room also grow on their own, faster where agglomeration is higher (%.3f x (agglomeration - 1) x free room share a day). "
                 "Infrastructure also speeds everybody's movement through the province (cost / (1 + %.1f x level)), whoever they are, shortens supply distance (a step into it counts 1/(1 + %.1f x level)) "
                 "and lets a depot standing on it push out more (x (1 + %.2f x level)). A battle in a province wears its development down (%.3f an hour), a province taken by force keeps %d%% of its development "
                 "and %d%% of its infrastructure, and land handed over by agreement or gained when a faction falls is undamaged. "
                 "`offer <faction> access` proposes that the two of you open your roads to each other: supply may then pass through the partner's provinces that have infrastructure 1 or more, "
                 "and the markets on both sides of the border count for each other. Either side ends it with `revoke <faction>` (everyone who knows you hears of it); it also ends when one takes land from the other. "
                 "`q economy` lists your developed provinces, what is being built, upkeep, and the price of the next level; api.provs carries dev, infra, agg, yield_now, room and links ({neighbour: 1 road | 2 railway} as last seen) for every province (others' as last seen)."
                 % (D.DEV_MAX, D.DEV_START_CITY, D.DEV_START_CAPITAL, D.INFRA_MAX, D.DEV_Y, D.DEV_FLAT, D.DEV_MP, D.AGG, D.LINK, D.LINK_INFRA, D.DEV_ROOM, D.DEV_ROOM_INFRA, -D.DEV_ROOM_RURAL, D.DEV_CHOKE,
                    D.DEV_COST, D.DEV_NEED[1], D.DEV_NEED[0], D.DEV_HOURS, D.INFRA_COST, D.INFRA_NEED[1], D.INFRA_NEED[0], D.INFRA_HOURS, D.DEV_KEEP, D.INFRA_KEEP, D.DEV_GROW,
                    D.INFRA_MOVE, D.INFRA_HOP, D.INFRA_HUB, D.DEV_BATTLE, round(D.DEV_SACK * 100), round(D.INFRA_SACK * 100)))
        L.append("DEPOTS: a depot is where your supply starts and where your treasury (res, steel, oil, rare) is kept. You begin with one, in your capital, holding everything. "
                 "`depot P<id> [weight]` opens another in any supplied province of yours (%d res, works after %d h) or changes the weight of one you have; the treasury is "
                 "spread over your working depots in proportion to the weights, carried at %g%% of the whole per hour and only between depots joined by your own land. "
                 "`depot P<id> 0` empties one and closes it (you always keep at least one). Every province draws supply from its nearest depot. One depot can push out "
                 "only so much: its load is the sum over the provinces it serves of 1/(1+%.2f x steps) (harsh land counts half); above %g (in a city %g) everything it serves "
                 "arrives proportionally slower. Whoever takes a depot takes the share of your treasury kept there. `q depots` shows share, weight, load and output of each."
                 % (D.DEPOT_COST, D.DEPOT_HOURS, D.DEPOT_SHIFT * 100, g.stock_hop, D.HUB_LOAD, D.HUB_LOAD_CITY))
        L.append("UNITS MOVE AND FIGHT INDIVIDUALLY. Every province has one key point. Orders name provinces; a unit walks in a "
                 "straight line from key point to key point and forms up around the one it is sent to (groups take up real room, "
                 "about %.2f cells per unit, so the front ranks of a big group reach the enemy first)." % D.SLOT)
        L.append("CAPTURE: a province is yours once one of your units stands at its key point and no fighting unit of any other "
                 "side is left in the province. Holding the key point is what counts, not the land around it.")
        L.append("FIRE: each hour a unit fires at up to %d nearest enemies within its range (cells: %s; neighbouring key points are "
                 "about %.1f cells apart). A unit under move orders is ADVANCING: it halts while it has a target, fires with atk, and "
                 "has no cover. A unit standing its ground fires with max(atk, %.1f x dfn), and incoming fire is divided by the terrain "
                 "defence and, on its own soil, by the fort. Artillery outranges everything: it can hit a key point from the next "
                 "province, and only other artillery or an advance can answer it. Units below strength %d fall back and do not fire."
                 % (D.TARGETS, " ".join("%s %g" % kv for kv in D.RANGE.items()), D.SPAN, D.HOLD_FIRE, D.RETREAT_AT))
        L.append("Units near the enemy (roughly within two provinces) do not recover strength; pull them back to refit.")
        L.append("TERRAIN move-hours(speed 1)/defence-mult/elevation: " + ", ".join(
            "%s %d/%.2f/%d" % (k, v["cost"], v["dfn"], v["elev"]) for k, v in D.TERRAIN.items() if k != "water") +
            ". Plain and forest lie at height 0 or 1 (lowland or upland), so there are four height levels 0-3. city +0.25 defence. "
            "Attack power is x%.2f per level when attacking downhill and x%.2f per level uphill. arm is slow and weak (x0.6) in forest/hill/mountain." % (D.DOWNHILL, D.UPHILL))
        L.append("SUPPLY: units in your supplied territory regain strength; units with no supplied friendly province "
                 "next to them lose strength and fight at 70%. Upkeep is paid from income.")
        L.append("EXPLORATION: the map itself is hidden. You know a province (terrain, height, yield, manpower, neighbours) only "
                 "after one of your units or provinces has seen it once; orders and routes can only use explored land plus one step beyond it.")
        L.append("FOG: you see your provinces, their neighbours, and what your units see (sight + elevation of the province "
                 "they stand on; higher ground blocks the view beyond it). Enemy strength is exact only next to your units "
                 "or under a rec's eyes; otherwise it is a rough estimate marked ~. Enemy capitals and depots are unknown until seen.")
        L.append("FRONTS: units holding their own land do not open fire on enemy units that merely stand on theirs: a front where nobody advances is quiet "
                 "(no losses, readiness recovers at the contact rate). Fire starts when units advance (have a route) or stand on land that is not theirs; units that "
                 "`prepare` an attack on a province also shell it if it is in their range (and can be shelled back by whoever reaches them); and "
                 "everyone in range joins a battle once it is on, including artillery standing behind either side. When a province falls, the loser's units in "
                 "A province assaulted from two directions keeps only %d%% of its terrain and fort cover, from three or more %d%%. "
                 "the neighbouring provinces lose %g morale (their flank is open); units cut off from supply lose %g strength per hour and surrender when "
                 "their morale is gone. Whoever takes a faction's last depot also takes %d%% of its manpower pool."
                 % (round(D.FLANK_COVER[0] * 100), round(D.FLANK_COVER[1] * 100), D.MOR_FLANK, D.ATTRITION, round(D.LOOT_MP * 100)))
        L.append("WIN: a faction that has lost its last depot is out; all its land passes to whoever took that depot and its units disband. "
                 "The last faction standing wins. At tick %d the highest score (territory yield, then army) wins." % g.max_ticks)
        L.append("MANPOWER: provinces also yield manpower (cities most). Raising a unit and replacing its losses both draw "
                 "on the manpower pool; with no manpower units do not recover.")
        L.append("FORTS: units told to `fortify` dig in where they stand (own province). Levels 1 trench, 2 bunkers, 3 fortress: "
                 "each level divides damage taken there by a further +25%% and adds 10%% return fire. Level L takes L x %d unit-hours "
                 "(eng digs 4x faster). art ignores 60%% of a fort, eng 40%%, arm 25%%. A captured fort loses half its levels. Works need men: in a province where none of your units stands, the fort loses %.2f of a level a day. MARCHING: a unit loses %.1f readiness an hour on the move, but only %.2f an hour while it marches through your own supplied land out of contact, and %s where that province has infrastructure 1 or more (rail)." % (D.FORT_HOURS, D.FORT_DECAY, -D.RDY_MOVE, -D.RDY_MARCH, "none" if D.RDY_RAIL == 0 else "%.2f" % -D.RDY_RAIL))
        L.append("SUPPLIES: every supplied province stores supplies (cap %d, city %d). Inflow per hour is %.0f/(1+%.2f x provinces "
                 "from the nearest depot of yours, times that depot's output), so fronts far from any depot fill slowly. A unit burns %.2f/h idle, %.2f in contact, %.2f defending an "
                 "assault and %.2f assaulting, from the province it stands in (or an adjacent own province when on foreign soil). "
                 "With the stock empty it attacks at half power and loses readiness. Captured provinces keep 25%% of their stock."
                 % (D.STOCK_CAP, D.STOCK_CAP_CITY, D.STOCK_FLOW, g.stock_hop, D.USE_IDLE, D.USE_CONTACT, D.USE_DEFEND, D.USE_ASSAULT))
        L.append("READINESS 0-100 per unit: +1/h resting, +%g/h in contact, -0.5/h marching, -1.5/h assaulting, -0.6/h defending. "
                 "Attack power is x(0.4+0.6*r/100), defence x(0.7+0.3*r/100). New units start at %d." % (D.RDY_CONTACT, D.RDY_NEW))
        L.append("PREPARED ATTACK: `prepare <sel> P<target>` makes units next to the target plan the attack: +1%% attack per hour "
                 "of waiting up to +%d%% (+%d%% if a rec of yours is next to the target). The bonus applies when they `move` into "
                 "that target, shrinks 1%%/h while assaulting, and is lost if they are sent anywhere else. "
                 "ACROSS THE WATER: once your troops can go by sea, units standing in a coastal province can also prepare against a province on the far shore of a sea zone both provinces touch "
                 "(a zone in your shipping's reach and not closed to you); `move` then takes them straight over, together, and the bonus lands with them. "
                 "api.overseas = {province id: sea zones from your coast} lists every coastal province you have seen that is not yours and that your shipping can reach now." % (D.PLAN_MAX, D.PLAN_MAX_EXACT))
        L.append("EVERY UNIT HAS ITS OWN STATE. EXPERIENCE 0-100 (%s, 20 points each): fire power x(%.2f+%.2f*xp/100) and damage taken "
                 "/(%.2f+%.2f*xp/100). Gained by fighting (+%.2f/h assaulting, +%.2f/h defending, slower near the top, +%g for destroying a unit) "
                 "and slowly by drill at home (up to %d). Replacements arrive green (xp %d), so rebuilding a mauled veteran unit dilutes it. "
                 "New units start at %d (mil %d)." % ("/".join(D.XP_LEVELS), D.XP_ATK0, D.XP_ATK, D.XP_DFN0, D.XP_DFN, D.XP_ASSAULT, D.XP_DEFEND,
                                                     D.XP_KILL, D.XP_TRAIN_CAP, D.XP_REPL, p.stats["inf"]["xp0"], p.stats["mil"]["xp0"]))
        L.append("MORALE 0-100 (new units %d): falls with losses (%.1f per strength point, up to 40%% less for veterans), -%g when a friendly unit "
                 "is destroyed in the same province, -%.1f/h cut off from supply, -%.1f/h with an empty depot; rises +%.1f/h resting, +%g for "
                 "destroying a unit, +%g for taking an enemy province. Fire power x(0.75+0.25*morale/100). Below %d a unit breaks and "
                 "runs even at high strength (it rallies in the rear at %d); surrounded, unsupplied and below %d it surrenders."
                 % (D.MOR_NEW, D.MOR_DMG, D.MOR_SHOCK, D.MOR_CUT, D.MOR_DRY, D.MOR_REST, D.MOR_KILL, D.MOR_WIN, D.MOR_BREAK, D.MOR_RALLY, D.MOR_SURRENDER))
        L.append("SUPPRESSION 0-100: incoming fire pins a unit (+%g per strength point lost, artillery x%.1f), halving each hour; "
                 "fire power x(1-0.5*suppression/100)." % (D.SUP_K, D.SUP_ART))
        L.append("FORMATIONS: units you put in a named group (`group <name> <sel>`) build FORMATION EXPERIENCE 0-100 while at least %d of them "
                 "fight in the same province (+%.2f per hour of combat at full rate). It gives the group's units fire power x(1+%.2f*fxp/100) "
                 "and %d%% less morale loss at 100. Adding units that were not in the group dilutes it in proportion; scattering the group "
                 "earns nothing." % (D.FORM_MIN, D.FORM_GAIN, D.FORM_ATK, int(D.FORM_MOR * 100)))
        L.append("RESOURCES: six kinds. res (general supplies and money) comes from every supplied province and pays upkeep. The five strategic "
                 "resources steel, oil, rare, coal and rubber come only from supplied provinces with a deposit (shown on the province: s<n> steel, o<n> oil, "
                 "r<n> rare, k<n> coal, u<n> rubber per day). Deposits are not spread evenly: they lie in fields, thick in some regions and almost absent "
                 "in others, so most factions start without some kinds. Units cost res + manpower and, depending on the kind, steel, oil and rare. "
                 "Engines burn oil every day (%s per unit); with your oil stock at zero those units fire at %d%% and do not regain readiness. "
                 "Upgrades need strategic resources too, more kinds the higher the level (see UPGRADES). What you lack you can only get by "
                 "trade (`offer .. trade`, `offer .. supply`), as a gift, or by holding land that has it."
                 % (", ".join("%s %g" % kv for kv in D.FUEL.items()), round(D.FUEL_OUT * 100)))
        L.append("SEASONS AND CLIMATE: a year is %d days (spring, summer, autumn, winter, %d days each; the war starts in spring; south of the equator the "
                 "seasons are reversed). In winter the land beyond latitude %g freezes, and so do the highest mountains beyond 25; tundra is frozen in every season but summer. "
                 "On frozen ground moving takes x%.1f hours, supplies arrive at x%.1f, no supply crosses a sea link into or out of it, and a unit that is not on "
                 "its own supplied land loses %.2f strength per hour (x%.2f for factions whose capital lies beyond latitude %g: they know winter). Forest within "
                 "latitude %g is jungle: units of factions from outside the tropics (capital beyond %g) lose %.2f strength per hour there when off their own "
                 "supplied land (less with medicine upgrades). A sea link counts as %d steps for supply. `q env` shows the season, what is frozen in your land now and what will freeze."
                 % (4 * D.SEASON_DAYS, D.SEASON_DAYS, D.COLD_LAT, D.COLD_MOVE, D.COLD_FLOW, D.FROST, D.HARDY, D.HARDY_LAT, D.JUNGLE_LAT, D.TROPIC_LAT, D.FEVER, D.SEA_HOPS))
        L.append("ARMOUR: some units are armoured (hard 0-1). Fire at a target is x(1 + hard x (ap - 1)), ap being the firing unit's "
                 "anti-armour value: soft weapons (ap 0.4-0.8) do little to tanks, anti-tank guns (ap 2.5) tear them open.")
        L.append("UPGRADES: `research <line>` starts the next level of a line (up to %d levels per line, %d projects at once, level L takes "
                 "L x %d h and costs L x the amounts below: res always, plus the first of the listed strategic resources at level 1, the first two at level 2 and all three at level 3). Lines: for every unit type <type>.weapons (attack; %s), <type>.protection "
                 "(defence; %s), <type>.mobility (speed; %s); and general lines %s. NOBODY KNOWS IN ADVANCE WHETHER A LINE LEADS ANYWHERE. "
                 "For your faction, in this war, each line secretly goes 0 to %d levels deep, and each level that exists is worth a "
                 "different, unknown amount (roughly +%d%% to +%d%% of the thing improved). When a project finishes you are told the "
                 "result: a BREAKTHROUGH with its exact effect, or a DEAD END (the resources are gone and that line is closed for good). "
                 "A breakthrough on one level says nothing certain about the next. Other factions' results are different from yours and you cannot see them. "
                 "A unit-type breakthrough creates a new model (mark) of that type: units recruited from then on are the new model, but units "
                 "already in the field KEEP THEIR OLD VALUES until you pay to re-equip them: `refit <sel>` costs %d%% of the type's price per unit "
                 "(res and special resources, no manpower), needs the unit out of combat on your own supplied land, and takes %d readiness off it."
                 % (D.TECH_LEVELS, D.TECH_SLOTS, D.TECH_HOURS, _need(D.TECH_UNIT["weapons"]), _need(D.TECH_UNIT["protection"]),
                    _need(D.TECH_UNIT["mobility"]), "; ".join("%s (%s; %s)" % (k, v["what"], _need(v)) for k, v in D.TECH_GENERAL.items()),
                    D.TECH_LEVELS, round(D.TECH_SIZE[0] * 100), round(D.TECH_SIZE[1] * 100), round(D.REFIT_COST * 100), D.REFIT_RDY))
        L.append("DIPLOMACY: you can deal with any faction you have come across (seen its land or units, or received something from it). "
                 "`say <faction> <text>` sends a letter (max %d characters, %d a day per faction). `give <faction> <n> <res|mp|steel|oil|rare|coal|rubber>` hands over resources, no strings attached. `offer <faction> supply <n> <what> .. for <n> <what> .. [hours]` proposes a STANDING delivery carried out every day until it runs out, one side cannot pay, or either side stops it with `cancel <id>` (everyone who knows the one who cut it off hears of it). A trade may also name provinces (`P<id>`) on either side: land can be sold, bought, or handed over as the price of peace; a province with a depot cannot be handed over, and when land changes hands the two sides get a %d h truce unless they already have a pact. `offer <faction> alliance [hours]` is a pact in which the two sides also see everything the other sees. Nothing obliges an ally to fight for you. "
                 "`offer <faction> trade <n> <what> .. for <n> <what> ..` proposes a one-off swap; `offer <faction> pact [hours]` proposes a pact for that many hours, or with no hours one that lasts until somebody breaks it; a dated pact can be offered again in its last %d h. "
                 "The other side answers with `accept <offer id>` or `reject <offer id>`; an unanswered offer lapses after %d h. "
                 "While a pact holds, the two sides' units do not fire at each other, cannot take each other's provinces and cannot prepare attacks on them (they may walk through). "
                 "`break <faction>` ends a pact: fighting can resume %d h later, the partner is told at once, and every faction that knows you hears that you broke it. "
                 "Nothing forces anyone to keep a promise made in a letter. You see only your own dealings."
                 % (D.MAIL_LEN, D.MAIL_PER_DAY, D.TRUCE_HOURS, D.PACT_RENEW, D.OFFER_HOURS, D.PACT_NOTICE))
        L.append("UNITS code atk/dfn speed sight range cost-res/manpower/hours [+steel/oil/rare] upkeep-per-day [hard] ap  notes")
        for c in CODES:
            if c not in p.stats: L.append(" %s  NOT DISCOVERED YET (discovery: %s)  %s" % (c, A.OPENED_BY.get(c), D.NOTES[c])); continue
            s = p.stats[c]
            L.append(" %s %g/%g v%g s%d r%g %d/%d/%d%s u%g%s ap%g  %s" % (
                c, s["atk"], s["dfn"], s["spd"], s["sight"], s["range"], s["cost"], s["mp"], s["time"],
                " +%d/%d/%d" % (s["steel"], s["oil"], s["rare"]) if s["steel"] or s["oil"] or s["rare"] else "", s["upkeep"],
                " hard%g" % s["hard"] if s["hard"] else "", s["ap"], D.NOTES[c]))
        L.append("Strength 0-100 scales both attack and defence. Below %d a unit breaks off or retreats." % D.RETREAT_AT)
        L.append("PROVINCES id terrain(p plain f forest h hill m mountain)+height yield/manpower [c = city] [s<n> o<n> r<n> = steel, oil, rare deposit per day] : neighbours. Water is impassable and not listed.")
        L.append("(you only know the land you have seen. Listed here: what you can see at the start. Everything else is unexplored until a unit "
                 "of yours sees it; 'q near P<id> [steps]' lists explored land around a province in this format. Scouts (rec) are the cheap, fast way to look.)")
        for i in sorted(p.explored):
            if g.provs[i].terrain != "water": L.append(self._prov_row(i))
        L.append("Your capital: P%d (your only depot at the start)." % p.capital)
        L.append("OBSERVATION LINES")
        L.append(" t<tick> res<bank>+<net per day> mp<manpower>+<per day> steel<bank>+<per day> oil<..>+<..> rare<..>+<..> own<provinces> units<n>")
        L.append(" O <your province ids>          K p<player> <province ids last known to be theirs> [cap P<id>] | ...   (full observation only;")
        L.append("                                  afterwards changes arrive as 'took' / 'lost province' events)")
        L.append(" F front order: <n> units         units currently under the automatic front order")
        L.append(" U P<prov> <n>u <avg strength>% r<avg readiness> x<avg experience> m<avg morale> st<supplies here> [prep>P<target> <n>u +<pct>] [atk>P<target> <n>u] [dry] [nosup] [f<fort>]   your units in a border or active province")
        L.append(" U rear <n>u in <k> provinces     everything else (ask 'q prov <id>' for composition)")
        L.append(" E P<prov> [p<owner>] <n>u s<total strength>  or  E P<prov> [p<owner>] ~<n>u s~<estimate>   enemy units you can see (f = their fort level)")
        L.append(" R training <type×n..>            units being recruited")
        L.append(" T research <line> L<level> <hours left>h | ...      projects under way (results arrive as events: BREAKTHROUGH / DEAD END);")
        L.append("   'old models: inf 40 ..' = units of yours still on an earlier model of their type (see refit)")
        L.append(" D pacts: <faction>[(ends t<hour>)] .. | offers to you: #<id> <faction>: <terms>; .. | your offers: .. | letters: the last three received")
        L.append(" X <tick> <event> | ...             took lostprov battle retreat broke lost kill ready cut nosupply intel fort tech surrender")
        L.append(" Delta updates repeat only changed lines; '-U P<id> P<id>' / '-E P<id>' lists lines that are gone.")
        L.append("COMMANDS (one per line)")
        L.append(" move <sel> P<id>        advance to that province's key point by the fastest route, fighting whatever comes within range")
        L.append(" hold <sel>              stop and defend")
        L.append(" prepare <sel> P<id>     plan an attack on an adjacent province (see PREPARED ATTACK); then 'move <sel> P<id>' to launch")
        L.append(" fortify <sel>           dig in where they stand (own province); a later move/hold stops the digging")
        L.append(" front <sel>             standing order: spread along your border, heavier where more enemy is seen, dig in, and keep")
        L.append("                         re-spreading as the border moves; units under 40 strength rotate to the rear until 85. A later move/hold takes a unit off the front.")
        L.append(" expand <sel> [P<id>] [x<r>]  standing order: keep taking free neutral provinces you have explored, one after another, away from")
        L.append("                         enemy units: the nearest one, or with P<id> the reachable one closest to the province you picked.")
        L.append("                         When no neutral land is in reach the unit joins the front order. Scouts (rec) cannot take land.")
        L.append("                         Units go in parties: a province counts as dealt with once the strength sent there is x<r> times the local people's as last seen (r stays as set, 3 at first; see LOCAL PEOPLES).")
        L.append(" explore <sel>           standing order: go to the nearest province you have never seen, look, go on to the next; turns away")
        L.append("                         from enemy units; ends when nothing unexplored is in reach. Any unit can do it; rec is the fast one.")
        L.append(" recruit <type> [n] [P<city>]     default city: capital")
        L.append(" depot P<id> [weight]    open a depot there, or set the weight of one you have (0 = empty and close it); see DEPOTS")
        L.append(" road P<a> P<b> | rail P<a> P<b>   build a road / a railway between two provinces of yours (see ROADS AND RAILWAYS); 'q roads'")
        L.append(" develop P<id> | build P<id>     raise a province's development / its infrastructure by one level (see ECONOMY); 'q economy'")
        L.append(" offer <faction> access | revoke <faction>     open your roads to each other / close them again (see ECONOMY)")
        L.append(" research <line>         start the next level of an upgrade line (see UPGRADES); 'q tech' lists every line with what you know about it")
        L.append(" research <discovery>    start a discovery of the tree (see AGES); 'q tree' lists the tree with what is open to you and what it costs you now")
        L.append(" declare <faction>       be at war with that faction for the next %d days (see WAR)      strike P<id>   fire a missile at a province you can see (needs ballistic_missiles)" % (D.WAR_HOURS // 24))
        L.append(" q budget                where your res comes from and goes (see CAPITAL)      q sea [P<id>]   the sea zones you know (around a province), which your shipping can use, which are closed to you")
        L.append(" say <faction> <text> | give <faction> <n> <what> | offer <faction> pact|alliance [hours] | offer <faction> trade <n> <what>|P<id> .. for ..")
        L.append(" offer <faction> supply <n> <what> .. for <n> <what> .. [hours] | cancel <delivery id>      'q powers': what you know of every faction you met; 'q env': season and climate")
        L.append(" accept <offer id> | reject <offer id> | break <faction>        see DIPLOMACY; 'q dip' shows your dealings")
        L.append(" refit <sel>             re-equip those units to their type's current model (see UPGRADES); units already current are skipped")
        L.append(" group <name> <sel>      name a formation; 'group a + <sel>' adds")
        L.append(" trial <hours> <name> [<name>..]   staff wargame: play up to 4 strategies forward (6-240 h) in a private copy built only from")
        L.append("                         what you currently know, and compare the forecasts. Names: 'current' (your running policy), a candidate you")
        L.append("                         drafted, or a ready-made one: %s. The real game keeps running meanwhile." % " ".join(sorted(f[:-3] for f in __import__("os").listdir(__import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "..", "policies")) if f.endswith(".py"))))
        L.append(" adopt <name>            make that strategy your standing policy from now on")
        L.append(" q front | q prov <id> | q path <from> <to> | q unit <id> | q near P<id> [steps] | q map | q enemy | q tech [prefix] | q dip | q army [0|1|2]")
        L.append("   q army: the condition of your own army and its supply, as much or as little as you ask for. 0 = totals (mean readiness, share ready (>= 60), spent (< 20),")
        L.append("   dry, moving, in contact, fighting, unsupplied). 1 = also by unit type, by standing order (front/expand/explore/direct), and the front as a whole")
        L.append("   (units per border province, stock, inflow against burn per hour, provinces running short). 2 = also one row for every province holding your units.")
        L.append("   (<sel> 'land' = all your ground units, 'sea' = all your ships, 'air' = all your aircraft; ships and aircraft take move / hold / prepare (ships) / refit / group, not the standing orders front / expand / explore)")
        L.append(" <sel> = unit ids '3,5-8' | group name | unit type | all | @P<id> (your units in that province); join with ','; 'old' = all your units on an outdated model, 'old:<type>' = those of one type")
        return "\n".join(L)

    def _brief_ages(self):
        g, p = self.g, self.p; L = []
        L.append("THE CALENDAR IS COMPRESSED: this one war stands for the years 0 to %d (%d game hours; a game day is about %.1f years). The year shows in every observation." % (A.CAL_YEARS, A.CAL_HOURS, A.CAL_YEARS / (A.CAL_HOURS / 24.0)))
        L.append("AGES: everyone starts in the ancient world. You can raise only %s. Every other kind of unit, bigger forts, ships, aircraft, missiles and satellites must be DISCOVERED, "
                 "in the order the tree below allows: `research <discovery>` (uses one of your %d research slots; res cost and hours by age: %s; from the %s age on also strategic resources: %s). "
                 "Strategic resources a discovery needs and you do not have are bought abroad at %d res each, automatically (for discoveries only, not for units or upgrades). "
                 "A discovery that a faction you have met already has is %d%% cheaper for you for each such faction (up to %d%%); 'q tree' and api.tree show your price now. Knowledge also SEEPS in by itself: every day, each discovery whose prerequisites you have fills by %.1f%% for every met faction that has it (a faction counts in full once it has had it %d hours, less before; at most %g factions count). The filled share ('seeped' in api.tree, 0..1) comes off both the price and the hours, so a discovery your neighbours have long had grows cheaper and quicker day by day, and at 100%% it is yours unpaid (a 'tech' event; your units still need `refit`). The nominal power below means that a model two or three ages ahead destroys older ones at almost no loss. "
                 "A discovery OPENS a kind of unit, or gives a kind a NEW MODEL, or changes what you can do. A model's attack and defence are the unit table's values (which describe the newest "
                 "model of all) times the nominal power of its age (%s; a second model inside one age x1.12), its range times %s (never under 1.5), and it needs steel only from the medieval age, oil only from the great-war age. "
                 "WHAT NOBODY KNOWS BEFOREHAND: your own version of a model is its nominal power times a hidden factor between %.2f and %.2f, drawn separately for you, for every kind and model, in this war. "
                 "So a new model is usually better than what you have, sometimes far better, sometimes hardly at all; you learn its real values only when the discovery is made (they are in the result and in api.stats). "
                 "As with all new models, units in the field keep the old one until you pay for `refit`. The UPGRADE lines of a kind (see UPGRADES) exist only for kinds you can raise, and what they gave carries over to later models."
                 % ((", ".join("%s (%s)" % (c, n) for c, n in A.START.items()), D.TECH_SLOTS,
                    "; ".join("%s %d res %d h" % (A.ERAS[e], A.COST[e], A.HOURS[e]) for e in range(len(A.ERAS))), A.ERAS[1],
                    "; ".join("%s %s" % (A.ERAS[e], "+".join("%d %s" % (v, k) for k, v in A.NEEDS[e])) for e in range(1, len(A.ERAS))), A.MARKET,
                    round(A.DIFFUSE * 100), round(A.DIFFUSE_MAX * 100), A.SEEP * 100, A.SEEP_FULL, A.SEEP_CAP, " ".join("%s %.2f" % (A.ERAS[e], A.POW[e]) for e in range(len(A.ERAS))),
                    "/".join("%g" % x for x in A.RNG), A.QUALITY[0], A.QUALITY[1])))
        L.append("THE TREE  discovery [age] <- what it needs first : what it brings")
        for t, (e, req, un, fx, word) in A.TREE.items():
            L.append(" %s [%s]%s : %s%s" % (t, A.ERAS[e], " <- " + ", ".join(req) if req else "", "; ".join("%s %s '%s'" % ("opens" if A.OPENED_BY[c] == t else "new model of", c, n) for c, n in un) or word,
                                         (" (+ " + word + ")") if un and fx else ""))
        L.append("FORTS AND THE TREE: without masonry your forts stop at level 1, with it at 2, with castles at 3.")
        L.append("THE SEA is divided into SEA ZONES (province ids from %d up; api.sea, 'q sea'). A coastal province lists the zones it touches (api.provs[id]['coast']). "
                 "SHIPS (shp, later sub and cvn) are built in a coastal city, appear in the zone off it, and move only from zone to zone (`move <ships> P<zone>`); they need the discovery galleys or later. "
                 "TROOPS GO BY SEA on their own once you have galleys: `move` to a land province routes them over water when that is the faster or the only way (loading and landing cost about %d h each; "
                 "at sea they move at your transport speed, cannot fire, and are sunk easily: x%g of their defence). Deep water (zones touching no land) and the long sea lanes need the discovery navigation. "
                 "Your shipping reaches only so many zones from a coast you own (galleys %d, sailing %d, ships_of_the_line %d, ironclads %d, dreadnoughts %d): troops and ships beyond that reach, "
                 "or inside a zone closed to you, are out of supply and waste away. SUPPLY ALSO GOES BY SEA: your coastal provinces supply each other through the zones your shipping can use "
                 "(a zone counts %g supply steps), so a landing can be fed from home, and can be starved by closing the sea behind it. "
                 "A ZONE IS CLOSED TO YOU while a warship of a faction at war with you lies in it and none of yours does. Ships regain strength and readiness only in a zone that touches your own supplied coast. "
                 "Ships fire at ships and at troops at sea; they fire at ground units (x their vg value) only in a province your side is assaulting, or one they `prepare` against (a zone next to it). "
                 "Ground units answer ships with x their vs value (artillery 0.6, others 0.2). Unit table columns for these: dom (0 land, 1 sea, 2 air), vg/vs/va = fire multiplier against ground units / ships / aircraft."
                 % (g.sea0, D.EMBARK, D.AT_SEA_DFN, A.SAIL["sail1"][1], A.SAIL["sail2"][1], A.SAIL["sail3"][1], A.SAIL["sail4"][1], A.SAIL["sail5"][1], D.SEA_SUPPLY_HOP))
        L.append("THE AIR (discoveries flight, bombers, jet_engines): an aircraft has a BASE, the province it was raised in. `move <aircraft> P<id>` to a province that is not yours is a SORTIE: it flies there over anything, "
                 "fights within its range while it stays, and turns for home by itself when its readiness falls under %d (it burns %g readiness an hour away from base and regains %g an hour on the ground; "
                 "with readiness 0 in the air it goes down). `move` to a supplied province of your own makes that its new base. Fighters (ftr) shoot at aircraft; bombers (bmr) hit ground units and ships in the "
                 "province they were sent against, and troops at sea. Aircraft on the ground cannot be shot at, but are lost if their base province is taken. Aircraft never take or hold land. "
                 "Ground units can hit aircraft only after assault_rifles (va 0.15); ships from the great-war age (va 0.3); carriers (cvn) reach 10 cells against everything."
                 % (D.AIR_HOME, D.AIR_BURN, D.AIR_REST))
        L.append("SPACE: satellites let you see every province in the world (strengths stay estimates where you have no unit near). ballistic_missiles gives `strike P<id>` on any province in your sight: %s, lands after %d h, "
                 "every unit in the province that is not yours or a pact partner's loses about %g strength (halved per fort level x0.5) and is pinned, the stock there halves, roads and development are damaged."
                 % (", ".join("%d %s" % (v, k) for k, v in D.STRIKE.items()), D.STRIKE_HOURS, D.STRIKE_DMG))
        L.append("WAR: at sea and in the air units fire only at factions you are AT WAR with. You are at war with a faction for %d days after the last real assault on land between you (either way), "
                 "a missile strike, an air or naval attack on ground units, or `declare <faction>`; the other side is told. A pact ends it. On land nothing changes: see FRONTS. api.wars lists whom you are at war with."
                 % (D.WAR_HOURS // 24))
        if g.ages:
            L.append("LOCAL PEOPLES: land that no faction owns is not empty. Each such province has a militia of the people who live there (%g to %g units' worth of strength, about %g more around a city, x%g in desert, tundra and jungle; "
                     "api.provs[id]['locals'] and the province lists show the strength as you last saw it). They never leave their province and attack nobody. Units that enter it (scouts excepted) fight them every hour: "
                     "per 100 strength the locals have attack %g and defence %g, times the nominal power of THEIR age, defence also times the terrain's cover; their age is %d ages behind the median faction's (never before ancient). "
                     "Your units' fire is their atk x strength x readiness as in any fight; the locals' fire is spread evenly over your units there. The province can be taken as usual once the militia is at 0. "
                     "A militia nobody is pressing regains %d%% of its full strength a day, and land that loses its owner fills up again the same way. "
                     "Free land also joins a neighbour by itself, without a fight: a faction of the locals' own age that borders a free province draws it in over about %d years (now %d days) if it owns all the land around it, "
                     "twice as long if it owns almost none; a faction 1, 2, 3 ages ahead of the locals takes a 4th, a 9th, a 16th of that. Several neighbours each fill their own share and the first to be full gets the province, "
                     "with its militia gone and nothing wrecked; it waits while another faction's troops stand there."
                     % (D.LOCAL_BASE * D.LOCAL_SPREAD[0], D.LOCAL_BASE * D.LOCAL_SPREAD[1], D.LOCAL_CITY, D.LOCAL_HARSH, D.LOCAL_ATK, D.LOCAL_DFN, D.LOCAL_LAG, round(D.LOCAL_HEAL * 100), D.LOCAL_JOIN, round(D.LOCAL_JOIN * A.CAL_HOURS / A.CAL_YEARS / 24.0)))
        L.append("ROADS AND RAILWAYS join two neighbouring provinces (the infrastructure level above is what stands INSIDE one province: streets, yards, stores). "
                 "`road P<a> P<b>` builds a road, `rail P<a> P<b>` a railway (it replaces the road). Neighbours: that one stretch. Provinces further apart: the shortest way between them through your own supplied land, "
                 "as many stretches from P<a>'s end as you can pay for now (the reply says how many were started). Both ends of a stretch must be yours%s. "
                 "One stretch of road costs %d res and %d h, of railway %d res + %d %s and %d h, on open plain; other ground costs in proportion to its movement cost (forest about x1.5, hill x1.75, mountain x2.75), and x%g across a river (it is then a bridge: the river no longer slows or weakens those who hold both banks). "
                 "Upkeep a day: road %.2f, railway %.2f res per stretch. "
                 "What they do: land units move x%g along a road and x%g along a railway (the railway only carries its owner's units and those of factions with an access agreement, and not units in contact with the enemy or routed; everyone else uses it as a road); "
                 "a march along either in your own supplied land costs no readiness; a supply step along a road counts %.1f and along a railway %.1f (so depots reach much further and fronts at the end of a line are fed); "
                 "and a neighbour joined by road counts +%.2f, by railway +%.2f more towards your market (see ECONOMY). "
                 "A province taken by force keeps its roads; its railways become roads. Routes (`move`, api.path) take roads and railways into account by themselves. `q roads` lists yours; api.links lists all you have seen."
                 % ((" and you need the discovery %s for roads and %s for railways" % (D.LINK_NEED["road"], D.LINK_NEED["rail"])) if g.ages else "",
                    D.ROAD_COST, D.ROAD_HOURS, D.RAIL_COST, D.RAIL_NEED[1], D.RAIL_NEED[0], D.RAIL_HOURS, D.LINK_RIVER, D.ROAD_KEEP, D.RAIL_KEEP, D.ROAD_MOVE, D.RAIL_MOVE, D.ROAD_HOP, D.RAIL_HOP, D.LINK_ROAD, D.LINK_RAIL))
        L.append("CAPITAL: your res is finite and everything draws on the same purse: raising units, their upkeep every day, discoveries and upgrades, refits, development and roads and their upkeep, depots, missiles. "
                 "`q budget` / api.budget show: res in hand, income per day, upkeep per day (units, cities and roads), net per day, how many days the purse lasts at the present rate if net is negative, "
                 "what you have taken in and paid out so far by purpose, upkeep by unit kind, the res tied up in recruitment and research under way, and for every discovery open to you how many days of net income it costs. "
                 "Nothing in the rules tells you how to divide it.")
        return L

    def tree_view(self):
        """The tree as this faction knows it: status, its price now, what it needs and brings. No hidden data."""
        g, p = self.g, self.p; out = {}
        for t, (e, req, un, fx, word) in A.TREE.items():
            st = A.status(g, p.id, t)
            out[t] = dict(status=st, age=A.ERAS[e], needs=list(req), missing=[r for r in req if r not in p.known], opens=[c for c, n in un if A.OPENED_BY[c] == t],
                          new_models=[c for c, n in un if A.OPENED_BY[c] != t], effect=word, cost=A.cost(g, p.id, t) if st != "known" else None, res_now=A.price(g, p.id, t)[1] if st != "known" else None, hours=A.hours(p, t) if st != "known" else 0, seeped=round(A.seeped(p, t), 2),
                          known_to_met=sum(1 for o in p.met if t in g.players[o].known))
        return out

    def budget_view(self):
        g, p = self.g, self.p; net = p.income - p.upkeep - p.maint; kinds = {}
        for u in g.punits[p.id].values(): kinds[u.type] = kinds.get(u.type, 0.0) + u.st["upkeep"]
        tied = sum(p.stats[q[0]]["cost"] for q in p.queue if q[0] in p.stats)
        tree = {}
        for t in A.TREE:
            if g.ages and A.status(g, p.id, t) == "open":
                c = A.cost(g, p.id, t); pay, res, extra = A.price(g, p.id, t); lack = sorted(k for k, v in c.items() if k != "res" and p.bank[k] < v)
                tree[t] = dict(cost=c, res_now=res, bought=extra, can_pay_now=p.res >= res, lacking=lack, days_of_net_income=round(res / net, 1) if net > 0 else None)
        return dict(res=round(p.res, 1), income=round(p.income, 1), upkeep_units=round(p.upkeep, 1), upkeep_works=round(p.maint, 1), net=round(net, 1),
                    days_left=round(p.res / -net, 1) if net < 0 else None, upkeep_share=round((p.upkeep + p.maint) / p.income, 3) if p.income > 0 else None,
                    earned=round(p.earned), spent={k: round(v) for k, v in p.spent.items()}, upkeep_by_kind={k: round(v, 1) for k, v in sorted(kinds.items())},
                    units=len(g.punits[p.id]), in_training=len(p.queue), res_in_training=tied, research=[r[0] for r in p.research],
                    stock=dict(p.bank), income_by=dict(p.inc), fuel_per_day=round(p.fuel, 2), open_discoveries=tree)

    def sea_view(self, around=None, steps=3):
        g, p = self.g, self.p; rz = g.searange[p.id]; blk = g.blockade[p.id]; out = {}
        zs = [i for i in p.explored if i >= g.sea0]
        if around is not None:
            near = set(g.provs[around].coast) if around < g.sea0 else {around}; fr = list(near)
            for _ in range(steps):
                fr = [b for a in fr for b in g.provs[a].nbrs if b not in near]; near.update(fr)
            zs = [i for i in zs if i in near]
        for i in sorted(zs):
            pr = g.provs[i]
            out[i] = dict(nbrs=list(pr.nbrs), coast=list(pr.coast), deep=pr.deep, x=pr.cx, y0=pr.cy, visible=i in p.visible, reach=rz.get(i), closed=i in blk,
                          mine=sum(1 for u in g.pos[i] if u.owner == p.id))
        return out

    def known_path(self, a, b):
        """Route using only land this player has explored (the destination may be the first unexplored step)."""
        g = self.g; ex = self.p.explored
        if a not in ex or (b not in ex and not any(c in ex for c in g.provs[b].nbrs)): return None
        r = g.path(a, b)
        if r and any(i not in ex for i in r[:-1]): r = g._path(a, b, None, None, ex)
        return r

    def region(self, start, steps):
        seen = {i: 0 for i in start}; q = list(start); k = 0; provs = self.g.provs
        while k < len(q):
            a = q[k]; k += 1
            if seen[a] >= steps: continue
            for b in provs[a].nbrs:
                if b not in seen: seen[b] = seen[a] + 1; q.append(b)
        return seen

    def tech_view(self):
        """Every upgrade line as this faction knows it: levels done, status, cost and time of the next level. No hidden data."""
        g = self.g; out = {}
        for line in g.tech_lines():
            if "." in line and line.split(".")[0] not in self.p.stats: continue
            lv, st = g.tech_status(self.pid, line)
            out[line] = dict(level=lv, status=st, cost=g.tech_cost(line, lv + 1) if st == "open" else None, hours=D.TECH_HOURS * (lv + 1) if st == "open" else 0)
        return out

    def _prov_row(self, i):
        pr = self.g.provs[i]
        return "%d %s%s%d %d/%d%s%s:%s" % (pr.id, pr.terrain[0], pr.biome[:1], pr.elev, pr.y, pr.mp, "c" if pr.city else "",
                                         "".join(" %s%d" % (D.DEP_CODE[k], getattr(pr, k)) for k in D.STRAT if getattr(pr, k)),
                                         ",".join(("~%d" % b if b in pr.sea else "=%d" % b if b in pr.river else str(b)) for b in pr.nbrs))

    def _near_cap(self):
        kc = self.p.known_caps
        if not kc: return None
        if len(kc) == 1: return next(iter(kc.values()))
        pc = self.g.provs[self.p.capital]
        return min(kc.values(), key=lambda c: (self.g.provs[c].cx - pc.cx) ** 2 + (self.g.provs[c].cy - pc.cy) ** 2)

    # ============================================================ observation
    def _lines(self):
        g, p, pid = self.g, self.p, self.pid; L = {}
        mine = [u for u in g.punits[pid].values()]
        own = [i for i in range(g.n) if g.owner[i] == pid]
        L["H"] = ("y%d %s " % (A.year(g.tick), A.ERAS[A.era_of(p)]) if g.ages else "") + "t%d res%d%+d mp%d%+d steel%d%+d oil%d%+d rare%d%+d coal%d%+d rubber%d%+d own%d units%d %s%s" % (
            g.tick, p.res, round(p.income - p.upkeep), p.mp, round(p.mp_income), p.bank["steel"], round(p.inc["steel"]), p.bank["oil"], round(p.inc["oil"] - p.fuel),
            p.bank["rare"], round(p.inc["rare"]), p.bank["coal"], round(p.inc["coal"]), p.bank["rubber"], round(p.inc["rubber"]), len(own), len(mine),
            D.SEASONS[g.season_at(g.tick, g.provs[p.capital].lat)], " NO-FUEL" if p.nofuel else "")
        old = {}
        for u in g.punits[self.pid].values():
            if u.st is not p.stats[u.type]: old[u.type] = old.get(u.type, 0) + 1
        if p.research or old:
            L["T"] = "T research " + (" | ".join("%s L%d %dh" % (r[0], r[1], r[2]) for r in p.research) or "none") + \
                     ("  old models: " + " ".join("%s %d" % kv for kv in sorted(old.items())) if old else "")
        dv = self.dip_view()
        if dv["pacts"] or dv["offers_in"] or dv["offers_out"] or dv["inbox"] or dv["deals"]:
            am = lambda d: " ".join((k if k.startswith("P") else "%d %s" % (v, k)) for k, v in sorted(d.items())) or "nothing"
            ot = lambda o: ("%s %s" % (o["kind"], "%dh" % o["hours"] if o["hours"] else "open-ended")) if o["kind"] in ("pact", "alliance") else "%s they give %s you give %s" % (
                "daily supply" if o["kind"] == "supply" else "trade", am(o["they_give"]), am(o["you_give"]))
            L["D"] = "D pacts: %s | offers to you: %s | your offers: %s | letters: %s" % (
                (" ".join("%s%s%s" % (k, "" if v["kind"] == "pact" else "[%s]" % v["kind"], "(ends t%d)" % v["ends"] if v["ends"] is not None else "") for k, v in sorted(dv["pacts"].items())) or "none") +
                ("  deliveries: " + "; ".join("#%d %s you give %s get %s" % (d["id"], d["with"], am(d["you_give"]), am(d["they_give"])) for d in dv["deals"]) if dv["deals"] else ""),
                "; ".join("#%d %s: %s" % (o["id"], o["frm"], ot(o)) for o in dv["offers_in"]) or "none",
                "; ".join("#%d to %s: %s" % (o["id"], o["to"], ot(o)) for o in dv["offers_out"]) or "none",
                " / ".join("t%d %s: %s" % (m["t"], m["frm"], m["text"]) for m in dv["inbox"][-3:]) or "none")
        L["O"] = "O " + _ids(own)
        fr = [i for i in self.front if i in g.units]
        ex = sum(1 for i in self.expand if i in g.units)
        if fr or ex: L["F"] = "F front order: %d units" % len(fr) + (", expand order: %d" % ex if ex else "")
        ek = {}
        for i, o in p.known_owner.items():
            if o >= 0 and o != pid: ek.setdefault(o, []).append(i)
        if ek: L["K"] = "K " + " | ".join("p%d %s%s" % (o, _ids(ek[o]), " cap P%d" % p.known_caps[o] if o in p.known_caps else "") for o in sorted(ek))
        # Units are reported per province, and only where it matters: border provinces, battles and marches you
        # ordered yourself. Everything else collapses into one 'rear' line, so the text stays small with 200 units.
        bd = self.border(); byp = {}
        for u in mine: byp.setdefault(u.prov, []).append(u)
        rear_n = rear_p = 0
        for prov in sorted(byp):
            us = byp[prov]
            hot = prov in bd or any(u.fighting or not u.supplied for u in us)
            if not hot: rear_n += len(us); rear_p += 1; continue
            t = "U P%d %du %d%% r%d x%d m%d st%d" % (prov, len(us), math.ceil(sum(u.str for u in us) / len(us) / 20) * 20,
                                              int(sum(u.rdy for u in us) / len(us) / 25) * 25, int(sum(u.xp for u in us) / len(us) / 20) * 20,
                                              int(sum(u.mor for u in us) / len(us) / 20) * 20, int(g.stock[prov] / 50) * 50)
            pl = {}
            for u in us:
                if u.plan_t >= 0 and u.fighting != 1: pl.setdefault(u.plan_t, []).append(u.plan_b)
            for k in sorted(pl): t += " prep>P%d %du +%d" % (k, len(pl[k]), int(sum(pl[k]) / len(pl[k]) / 10) * 10)
            mv = {}
            for u in us:
                if u.path and u.fighting == 1:
                    k = "atk>P%d" % u.path[0]; mv[k] = mv.get(k, 0) + 1
            for k in sorted(mv): t += " %s %du" % (k, mv[k])
            if any(u.dry for u in us): t += " dry"
            if any(not u.supplied for u in us): t += " nosup"
            if g.fort_level(prov): t += " f%d" % g.fort_level(prov)
            L["U%d" % prov] = t
        if rear_n: L["Ur"] = "U rear %du in %d provinces" % (rear_n, rear_p)
        for i in sorted(p.visible):
            if not g.pos[i]: continue
            est = g.estimate(pid, i)
            if not est or not est[3]: continue
            lvl, c, st, n = est
            sb = 50 if st <= 50 else int(round(st / 100.0)) * 100
            who = "p%d " % next(u.owner for u in g.pos[i] if u.owner != pid) if self.multi else ""
            L["E%d" % i] = (("E P%d %s%du s%d" % (i, who, n, sb)) if lvl == 2 else ("E P%d %s~%du s~%d" % (i, who, n, sb))) + \
                (" f%d" % g.fort_level(i) if g.fort_level(i) else "")
        if p.queue:
            c = {}
            for q in p.queue: c[q[0]] = c.get(q[0], 0) + 1
            L["R"] = "R training " + _counts(c)
        return L

    def _events(self):
        ev = self.p.events[self._ev:]; self._ev = len(self.p.events)
        if not ev: return None
        parts = []; took = []; lostp = []; agg = {}
        for (t, kind, text) in ev:
            if kind == "took": took.append(text)
            elif kind == "lostprov": lostp.append(text)
            elif kind in ("retreat", "broke", "nosupply", "fort"): agg.setdefault("n", {}); agg["n"][kind] = agg["n"].get(kind, 0) + 1
            elif kind in ("kill", "lost", "ready"):
                a = agg.setdefault(kind, {}); k = text.split("#")[0].split(" ")[0]; a[k] = a.get(k, 0) + 1
            else: parts.append("%d %s" % (t, text))
        if took: parts.append("took " + ",".join(took))
        if lostp: parts.append("lost province " + ",".join(lostp))
        if "n" in agg: parts.append(" ".join("%s×%d" % kv for kv in agg["n"].items()))
        for kind in ("ready", "lost", "kill"):
            if kind in agg: parts.append("%s %s" % ({"lost": "lost unit"}.get(kind, kind), " ".join("%s×%d" % kv for kv in agg[kind].items())))
        return "X " + " | ".join(parts)

    def pending_events(self, kinds=("battle", "lostprov", "cut", "retreat", "lost", "intel", "nosupply", "tech", "mail", "gift", "offer", "pact", "news")):
        return sum(1 for (t, k, x) in self.p.events[self._ev:] if k in kinds)

    def obs(self, mode="delta"):
        L = self._lines(); last = self._last; out = [L["H"]]
        if mode == "full" or not last:
            out += [v for k, v in L.items() if k != "H"]
        else:
            out += [v for k, v in L.items() if k not in ("H", "O", "K") and last.get(k) != v]   # O/K changes arrive as events
            gone = {"U": [], "E": []}
            for k in last:
                if k not in L and k[0] in "UE" and k != "Ur": gone[k[0]].append(k[1:])
            out += ["-%s %s" % (c, " ".join("P" + x for x in v)) for c, v in gone.items() if v]
            if "R" in last and "R" not in L: out.append("R none")
        ev = self._events()
        if ev: out.append(ev)
        if self.g.over:
            out.append("GAME OVER: " + ("draw" if self.g.winner is None else ("you win" if self.g.winner == self.pid else "you lose")))
        self._last = L
        return "\n".join(out)

    def obs_json(self):
        g, p, pid = self.g, self.p, self.pid
        return dict(tick=g.tick, manpower=round(p.mp, 1), manpower_per_day=p.mp_income, resources=round(p.res, 1), steel=round(p.bank["steel"]), oil=round(p.bank["oil"]), rare=round(p.bank["rare"]),
                    research=[list(r) for r in p.research], tech=dict(p.tech), dead_ends=sorted(p.dead), diplomacy=self.dip_view(), income_per_day=p.income, upkeep_per_day=p.upkeep, capital=p.capital,
                    provinces=[dict(id=i, owner=("me" if p.known_owner.get(i) == pid else "neutral" if p.known_owner.get(i, -1) < 0 else "enemy"), visible=i in p.visible, supplied=i in p.supplied,
                                    terrain=g.provs[i].terrain, city=g.provs[i].city, manpower=g.provs[i].mp,
                                    fort=p.known_fort.get(i, 0), **{"yield": g.provs[i].y})
                               for i in sorted(p.explored) if g.provs[i].terrain != "water"],
                    units=[dict(id=u.id, type=u.type, province=u.prov, strength=round(u.str, 1), path=list(u.path),
                                progress=round(u.prog, 2), fighting=bool(u.fighting), supplied=u.supplied, group=u.group)
                           for u in g.punits[pid].values()],
                    enemy=[dict(province=i, exact=e[0] == 2, types=e[1], strength=e[2], count=e[3])
                           for i in sorted(p.visible) if g.pos[i] for e in [g.estimate(pid, i)] if e and e[3]],
                    recruiting=[dict(type=q[0], province=q[1], hours_left=q[2]) for q in p.queue])

    # ============================================================ commands
    def _fac(self, tok):
        t = tok.lower().rstrip(":,")
        for q in self.g.players:
            if q.faction == t or t == "f%d" % q.id: return q.id
        raise CmdError("unknown faction '%s'" % tok)

    def _amounts(self, toks):
        d = {}
        while toks:
            if len(toks) >= 2 and toks[0].isdigit() and toks[1].lower() in D.GIVE: d[toks[1].lower()] = d.get(toks[1].lower(), 0) + int(toks[0]); del toks[:2]
            elif toks[0][:1] in "Pp" and toks[0][1:].isdigit(): d["P" + toks[0][1:]] = 1; del toks[:1]
            else: break
        return d

    def dip_view(self):
        """Everything this faction knows about its dealings: who it has met, pacts, open offers both ways, letters."""
        g, pid = self.g, self.pid; name = lambda i: g.players[i].faction
        pacts = {}
        for (a, b), pc in g.pacts.items():
            if pid in (a, b):
                end = [x for x in (pc["ends"], pc["until"]) if x is not None]
                pacts[name(b if a == pid else a)] = dict(since=pc["since"], ends=min(end) if end else None, broken_by=name(pc["by"]) if pc["by"] is not None else None,
                                                         kind="alliance" if pc.get("ally") else "truce" if pc.get("truce") else "pact")
        f = lambda o, mine: dict(id=o["id"], kind=o["kind"], hours=o["hours"], lapses=o["t"] + D.OFFER_HOURS,
                                 they_give=dict(o["want"] if mine else o["give"]), you_give=dict(o["give"] if mine else o["want"]), **({"to": name(o["to"])} if mine else {"frm": name(o["frm"])}))
        deals = [dict(id=d["id"], **{"with": name(d["b"] if d["a"] == pid else d["a"])}, you_give=dict(d["give"] if d["a"] == pid else d["want"]),
                      they_give=dict(d["want"] if d["a"] == pid else d["give"]), since=d["since"], until=d["until"]) for d in g.deals.values() if pid in (d["a"], d["b"])]
        return dict(met=sorted(name(i) for i in g.met(pid)), pacts=pacts, deals=deals,
                    offers_in=[f(o, False) for o in g.offers.values() if o["to"] == pid], offers_out=[f(o, True) for o in g.offers.values() if o["frm"] == pid],
                    inbox=[dict(t=m["t"], frm=name(m["frm"]), text=m["text"]) for m in self.p.mail[-20:]])

    def powers_view(self):
        """What this faction can tell about every faction it has met (and itself) from the land it has explored: how much land and how many
        cities it knows to be theirs and what the deposits on that land yield per day. Nothing here is beyond the fog."""
        g, p = self.g, self.p; out = {}; acc = {}
        for i, o in p.known_owner.items():
            if o < 0 or i not in p.explored: continue
            pr = g.provs[i]; a = acc.setdefault(o, dict(land=0, cities=0, deposits=dict.fromkeys(D.STRAT, 0)))
            a["land"] += 1; a["cities"] += 1 if pr.city else 0
            for k in D.STRAT: a["deposits"][k] += getattr(pr, k)
        for o in [p.id] + sorted(g.met(p.id)):
            a = acc.get(o, dict(land=0, cities=0, deposits=dict.fromkeys(D.STRAT, 0))); pc = g.pacts.get((min(o, p.id), max(o, p.id)))
            a["relation"] = "self" if o == p.id else "none" if pc is None else "alliance" if pc.get("ally") else "truce" if pc.get("truce") else "pact"
            a["deliveries"] = sum(1 for d in g.deals.values() if {d["a"], d["b"]} == {o, p.id})
            if o == p.id: a["me"] = True
            out[g.players[o].faction] = a
        return out

    def economy_view(self):
        """Your developed or road-built provinces (richest first), what is being built, upkeep, and who shares roads with you."""
        g, p = self.g, self.p; rows = []
        ct = lambda c: "%d res + %d %s" % (c[0], c[2], c[1]); cd = lambda c: {"res": c[0], c[1]: c[2]}
        can = lambda c: p.res >= c[0] and p.bank[c[1]] >= c[2]
        for i in g.owned[p.id]:
            if g.dev[i] > 0 or g.infra[i] > 0:
                rows.append(dict(prov=i, dev=round(g.dev[i], 2), room=g.room(i), infra=round(g.infra[i], 2), agg=round(g.agg[i], 3), yield_now=round(g.prod[i], 2), base=g.provs[i].y, city=g.provs[i].city,
                                 dev_cost=cd(g.dev_cost(i)) if g.dev[i] + 1 <= D.DEV_MAX else None, infra_cost=cd(g.infra_cost(i)) if g.infra[i] + 1 <= D.INFRA_MAX else None,
                                 dev_text=ct(g.dev_cost(i)) if g.dev[i] + 1 <= D.DEV_MAX else "top", infra_text=ct(g.infra_cost(i)) if g.infra[i] + 1 <= D.INFRA_MAX else "top",
                                 can_dev=g.dev[i] + 1 <= D.DEV_MAX and can(g.dev_cost(i)), can_infra=g.infra[i] + 1 <= D.INFRA_MAX and can(g.infra_cost(i))))
        rows.sort(key=lambda r: (-r["yield_now"], r["prov"]))
        return dict(income=round(p.income, 1), upkeep=round(p.upkeep, 1), maint=round(p.maint, 1), works=[list(w) for w in p.works],
                    roads=sum(1 for i in g.owned[p.id] for b, l in g.lk[i].items() if l == 1 and (b > i or g.owner[b] != p.id)), rails=sum(1 for i in g.owned[p.id] for b, l in g.lk[i].items() if l == 2 and (b > i or g.owner[b] != p.id)),
                    access=sorted(g.players[b].faction for a, b in g.access if a == p.id), provs=rows)

    def depot_view(self):
        """Your depots: share of the treasury held, wanted weight, hours until open, provinces served, load / capacity and output factor."""
        g, p = self.g, self.p; out = {}; served = {}
        for b, d in g.hub[p.id].items(): served[d] = served.get(d, 0) + 1
        for d in sorted(p.depots):
            cap = D.HUB_LOAD_CITY if g.provs[d].city else D.HUB_LOAD
            out[d] = dict(share=round(p.depots[d], 3), weight=p.depot_want.get(d, 0.0), opens_in=p.depot_build.get(d, 0), serves=served.get(d, 0),
                          load=round(g.load[p.id].get(d, 0.0), 1), capacity=cap, output=round(g.throttle[p.id].get(d, 1.0), 2), city=bool(g.provs[d].city))
        return out

    def army_view(self, level=0):
        """The state of this faction's own army and supply, at the detail asked for.
        0: one line of totals. 1: also by unit type, by standing order, and the front as a whole. 2: also every province that holds units."""
        g, p, pid = self.g, self.p, self.pid; us = list(g.punits[pid].values()); n = max(1, len(us)); own = g.owner
        sh = lambda k: round(k / n, 3)
        def cond(rows):
            m = max(1, len(rows))
            return dict(n=len(rows), rdy=round(sum(u.rdy for u in rows) / m, 1), mor=round(sum(u.mor for u in rows) / m, 1), str=round(sum(u.str for u in rows) / m, 1),
                        ready=round(sum(1 for u in rows if u.rdy >= 60) / m, 3), dry=round(sum(1 for u in rows if u.dry) / m, 3), moving=round(sum(1 for u in rows if u.path) / m, 3))
        out = cond(us); out.update(t=g.tick, spent=sh(sum(1 for u in us if u.rdy < 20)), contact=sh(sum(1 for u in us if u.contact)), fighting=sh(sum(1 for u in us if u.fighting)),
                                   unsupplied=sh(sum(1 for u in us if not u.supplied)), old_models=sum(1 for u in us if u.st is not p.stats[u.type]))
        if level < 1: return out
        use = lambda u: D.USE_ASSAULT if u.fighting == 1 else D.USE_DEFEND if u.fighting == 2 else D.USE_CONTACT if u.contact and not u.path else D.USE_IDLE
        order = lambda u: "front" if u.id in self.front else "expand" if u.id in self.expand else "explore" if u.id in self.explore else "direct"
        bt = {}; bo = {}; bp = {}
        for u in us: bt.setdefault(u.type, []).append(u); bo.setdefault(order(u), []).append(u); bp.setdefault(u.prov, []).append(u)
        out["by_type"] = {k: cond(v) for k, v in sorted(bt.items())}; out["by_order"] = {k: cond(v) for k, v in sorted(bo.items())}
        hops = g.hops[pid]; rows = []
        for i, v in sorted(bp.items()):
            mine = own[i] == pid; border = mine and any(own[b] >= 0 and own[b] != pid for b in g.provs[i].nbrs)
            inflow = D.STOCK_FLOW * p.mult["flow"] / (1.0 + g.stock_hop * hops[i]) * (0.5 if g.provs[i].biome else 1.0) if mine and i in hops else 0.0
            c = cond(v); c.update(prov=i, own=mine, border=border, stock=round(g.stock[i], 1) if mine else None, inflow=round(inflow, 2), burn=round(sum(use(u) for u in v), 2),
                                  hops=hops.get(i) if mine else None, fort=g.fort_level(i) if mine else None)
            rows.append(c)
        fr = [r for r in rows if r["border"]]; k = max(1, len(fr))
        out["front"] = dict(provinces=len(fr), units=sum(r["n"] for r in fr), units_per_province=round(sum(r["n"] for r in fr) / k, 1), rdy=round(sum(r["rdy"] * r["n"] for r in fr) / max(1, sum(r["n"] for r in fr)), 1),
                            stock_mean=round(sum(r["stock"] for r in fr) / k, 1), stock_empty=sum(1 for r in fr if r["stock"] < 1), inflow_per_h=round(sum(r["inflow"] for r in fr) / k, 2),
                            burn_per_h=round(sum(r["burn"] for r in fr) / k, 2), short=sum(1 for r in fr if r["burn"] > r["inflow"]))
        if level >= 2: out["provinces"] = rows
        return out

    def _prov(self, tok):
        t = tok.lstrip("Pp")
        if tok == "capital": return self.p.capital
        if tok == "enemy":
            if not self.p.known_caps: raise CmdError("enemy capital not found yet")
            return self._near_cap()
        if not t.isdigit() or int(t) >= self.g.n: raise CmdError("bad province '%s'" % tok)
        i = int(t); ex = self.p.explored
        if i not in ex and not any(b in ex for b in self.g.nb2[i]): raise CmdError("P%d is unexplored" % i)
        return i

    def _sel(self, tok):
        g, pid = self.g, self.pid; ids = []
        mine = [u for u in g.punits[pid].values()]
        for part in tok.split(","):
            part = part.strip().lstrip("#")
            if not part: continue
            if part.isdigit(): ids.append(int(part))
            elif "-" in part and all(x.isdigit() for x in part.split("-", 1)):
                a, b = part.split("-", 1); ids += list(range(int(a), int(b) + 1))
            elif part in CODES: ids += [u.id for u in mine if u.type == part]
            elif part == "all": ids += [u.id for u in mine]
            elif part in ("land", "sea", "air"): ids += [u.id for u in mine if u.st["dom"] == ("land", "sea", "air").index(part)]
            elif part == "old": ids += [u.id for u in mine if u.st is not self.p.stats[u.type]]
            elif part[:4] == "old:" and part[4:] in CODES: ids += [u.id for u in mine if u.type == part[4:] and u.st is not self.p.stats[u.type]]
            elif part[0] == "@": pv = self._prov(part[1:]); ids += [u.id for u in mine if u.prov == pv]
            elif part in self.p.groups: ids += list(self.p.groups[part])
            else: raise CmdError("bad selector '%s'" % part)
        ids = [i for i in dict.fromkeys(ids) if i in g.units and g.units[i].owner == pid]
        if not ids: raise CmdError("selector '%s' matches nothing" % tok)
        return ids

    def act(self, text):
        ok = 0; out = []; n = 0
        for raw in text.replace(";", "\n").split("\n"):
            line = raw.strip().strip("`").strip()
            if not line or line.startswith(("#", "//")): continue
            n += 1; self.stats["cmds"] += 1; vb = line.split()[0].lower()
            if vb != "q": self.verbs[vb] = self.verbs.get(vb, 0) + 1
            try:
                r = self._one(line)
                if r: out.append(r)
                else: ok += 1
            except CmdError as ex:
                self.stats["errors"] += 1; out.append("E%d %s: %s" % (n, line.split()[0], ex))
                key = "%s: %s" % (vb, re.sub(r"\d+", "N", str(ex)))[:90]
                if key in self.rejects or len(self.rejects) < 200: self.rejects[key] = self.rejects.get(key, 0) + 1
            except Exception as ex:
                self.stats["errors"] += 1; out.append("E%d %s: bad syntax (%s)" % (n, line.split()[0], type(ex).__name__))
        return "\n".join((["ok %d" % ok] if ok else []) + out) or "no commands"

    def _one(self, line):
        g, pid = self.g, self.pid
        toks = line.split(); verb = toks.pop(0).lower()
        if verb == "q": return self.query(" ".join(toks))
        if verb in ("expand", "explore", "front") and toks:
            ids = [i for i in self._sel(toks[0]) if not g.units[i].st["dom"] and g.units[i].prov < g.sea0]
            if not ids: raise CmdError("ships, aircraft and troops at sea take no standing orders")
            toks[0] = ",".join(str(i) for i in ids)
        if verb == "declare": return g.order_declare(pid, self._fac(toks.pop(0)))
        if verb == "strike": return g.order_strike(pid, self._prov(toks.pop(0)))
        if verb in ("move", "attack", "atk"):
            ids = self._sel(toks.pop(0)); err = g.order_move(pid, ids, self._prov(toks.pop(0)), known=self.p.explored)
            self.front.difference_update(ids); self.expand.difference_update(ids); self.explore.difference_update(ids)
        elif verb in ("hold", "stop"):
            ids = self._sel(toks.pop(0)); err = g.order_hold(pid, ids); self.front.difference_update(ids); self.expand.difference_update(ids); self.explore.difference_update(ids)
        elif verb in ("prepare", "prep"):
            ids = self._sel(toks.pop(0)); err = g.order_prepare(pid, ids, self._prov(toks.pop(0))); self.front.difference_update(ids); self.expand.difference_update(ids); self.explore.difference_update(ids)
        elif verb in ("fortify", "dig"):
            ids = self._sel(toks.pop(0)); err = g.order_fortify(pid, ids)
        elif verb == "expand":
            ids = self._sel(toks.pop(0)); to = self._prov(toks.pop(0)) if toks and not toks[0].startswith("x") else None
            if toks and toks[0].startswith("x"): self.expand_x = max(0.5, min(20.0, float(toks.pop(0)[1:])))
            g.order_hold(pid, ids); self.front.difference_update(ids); self.explore.difference_update(ids)
            sc = [i for i in ids if g.units[i].type == "rec"]; ids = [i for i in ids if g.units[i].type != "rec"]
            self.expand.update(ids)
            for i in ids:
                if to is None: self.expand_to.pop(i, None)
                else: self.expand_to[i] = to
            self._run_expand(); err = None
            if sc:
                self.explore.update(sc); self._run_explore()
                if not ids: return "ok (scouts cannot take land: %d rec sent to explore instead)" % len(sc)
        elif verb == "explore":
            ids = self._sel(toks.pop(0)); g.order_hold(pid, ids); self.front.difference_update(ids); self.expand.difference_update(ids)
            self.explore.update(ids); self._run_explore(); err = None
        elif verb == "front":
            ids = self._sel(toks.pop(0)); self.expand.difference_update(ids); self.explore.difference_update(ids); self.front.update(ids); self._run_front(); err = None
        elif verb == "research":
            err = g.order_research(pid, toks.pop(0))
        elif verb == "say":
            to = self._fac(toks.pop(0)); err = g.order_say(pid, to, line.split(None, 2)[2] if len(line.split(None, 2)) > 2 else "")
        elif verb == "give":
            to = self._fac(toks.pop(0)); n = int(toks.pop(0)); err = g.order_give(pid, to, toks.pop(0).lower(), n)
        elif verb == "offer":
            to = self._fac(toks.pop(0)); kind = toks.pop(0).lower()
            if kind in ("pact", "alliance"): err, oid = g.order_offer(pid, to, kind, hours=int(toks[0]) if toks and toks[0].isdigit() else 0)
            elif kind == "access": err, oid = g.order_offer(pid, to, kind)
            elif kind in ("trade", "supply"):
                give = self._amounts(toks)
                if toks and toks[0].lower() == "for": toks.pop(0)
                want = self._amounts(toks)
                err, oid = g.order_offer(pid, to, kind, give=give, want=want, hours=int(toks[0]) if kind == "supply" and toks and toks[0].isdigit() else 0)
            else: raise CmdError("offer <faction> pact|alliance [hours] | offer <faction> trade <n> <what>|P<id> .. for <n> <what>|P<id> .. | offer <faction> supply <n> <what> .. for <n> <what> .. [hours]")
            if not err: return "ok (offer %d sent)" % oid
        elif verb in ("accept", "reject"):
            err = g.order_answer(pid, int(toks.pop(0).lstrip("#")), verb == "accept")
        elif verb == "break":
            err = g.order_break(pid, self._fac(toks.pop(0)))
        elif verb == "cancel":
            err = g.order_cancel(pid, int(toks.pop(0).lstrip("#")))
        elif verb in ("develop", "build"):
            err = g.order_develop(pid, self._prov(toks.pop(0)), "dev" if verb == "develop" else "infra")
        elif verb in ("road", "rail"):
            a_ = self._prov(toks.pop(0)); b_ = self._prov(toks.pop(0)); err = g.order_link(pid, a_, b_, verb)
            if not err: return "ok (%s)" % g._note
        elif verb == "revoke":
            err = g.order_revoke(pid, self._fac(toks.pop(0)))
        elif verb == "depot":
            pv = self._prov(toks.pop(0)); err = g.order_depot(pid, pv, float(toks.pop(0)) if toks else 1.0)
        elif verb == "refit":
            ids = self._sel(toks.pop(0)); done = 0; err = None; skip = 0
            for i in sorted(ids):
                e = g.order_refit(pid, i)
                if e is None: done += 1
                elif "already" in e: skip += 1
                else: err = err or e
            if done or (skip and not err): return "ok (%d refitted%s%s)" % (done, ", %d already current" % skip if skip else "", "; stopped: " + err if err else "")
        elif verb == "recruit":
            code = toks.pop(0); n = 1; prov = None
            for t in toks:
                if t.isdigit(): n = int(t)
                else: prov = self._prov(t)
            err = None; done = 0
            for _ in range(n):
                err = g.order_recruit(pid, code, prov)
                if err: break
                done += 1
            if err and done: err = "%d/%d ordered, then: %s" % (done, n, err)
        elif verb == "group":
            name = toks.pop(0); add = False
            if toks and toks[0] in ("+", "="): add = toks.pop(0) == "+"
            if not name.isalpha() or name in CODES + ("all",): raise CmdError("bad group name")
            ids = self._sel(",".join(toks))
            for s in self.p.groups.values(): s.difference_update(ids)
            cur = self.p.groups.setdefault(name, set()); old = set(i for i in cur if i in g.units)
            if not add:
                for i in cur:
                    if i in g.units: g.units[i].group = ""
                cur.clear()
            cur.intersection_update(g.units.keys()); cur.update(ids)
            for i in ids: g.units[i].group = name
            fx = self.p.fxp                                     # newcomers have not fought with this formation: its experience is diluted
            if name in fx: fx[name] = fx[name] * len(old & cur) / max(1, len(cur))
            err = None
        elif verb == "trial":
            from .wargame import trial
            hours = int(toks.pop(0)) if toks and toks[0].isdigit() else 48
            if not toks: raise CmdError("usage: trial <hours> <name> [<name>...]")
            return trial(self, toks, hours)
        elif verb == "adopt":
            src = self.source(toks[0])
            if src is None: raise CmdError("no such candidate or library policy")
            r = self.set_policy("main", src[0], src[1])
            return "adopted %s: %s" % (toks[0], r)
        else:
            raise CmdError("unknown command")
        if err: raise CmdError(err)
        return None

    # ============================================================ queries
    def query(self, text):
        g, p, pid = self.g, self.p, self.pid
        toks = text.split()
        if not toks: return "q front|prov|path|unit|map|enemy"
        k = toks.pop(0)
        try:
            if k == "front":
                out = []
                for i in range(g.n):
                    if g.owner[i] != pid: continue
                    en = [b for b in g.provs[i].nbrs if p.known_owner.get(b, -1) not in (-1, pid)]
                    ne = [b for b in g.provs[i].nbrs if p.known_owner.get(b, -1) == -1]
                    if not en and not ne: continue
                    my = sum(u.str for u in g.pos[i] if u.owner == pid)
                    s = "P%d(%s y%d) mine s%d" % (i, g.provs[i].terrain, g.provs[i].y, my)
                    if en:
                        s += " | enemy " + " ".join("P%d%s" % (b, self._est_str(b)) for b in en)
                    if ne: s += " | neutral " + " ".join("P%d(y%d)" % (b, g.provs[b].y) for b in ne)
                    out.append(s)
                return "front:\n" + "\n".join(out) if out else "front: none"
            if k == "prov":
                i = self._prov(toks[0]); pr = g.provs[i]; ko = p.known_owner.get(i)
                if i not in p.explored: return "P%d: unexplored (send a unit to look)" % i
                s = "P%d %s elev%d y%d mp%d fort%d%s%s owner=%s %s" % (i, pr.terrain, pr.elev, pr.y, pr.mp, p.known_fort.get(i, 0),
                                                        " stock%d +%.1f/h" % (g.stock[i], g.stock_flow(pid, i)) if g.owner[i] == pid else "", " city" if pr.city else "",
                                                        "you" if ko == pid else "neutral" if ko is None or ko < 0 else "enemy P%d" % ko,
                                                        "visible" if i in p.visible else "not visible")
                if g.owner[i] == pid: s += " supplied" if i in p.supplied else " CUT OFF"
                us = [u for u in g.pos[i] if u.owner == pid]; c = {}
                for u in us: c[u.type] = c.get(u.type, 0) + 1
                if pr.biome: s += " " + pr.biome
                if pr.sea: s += " sea links to " + ",".join("P%d" % b for b in pr.sea)
                if us: s += " | yours: %s s%d xp%d morale%d" % (_counts(c), sum(u.str for u in us), sum(u.xp for u in us) / len(us), sum(u.mor for u in us) / len(us))
                return s + (" | enemy:" + self._est_str(i) if self._est_str(i) else "")
            if k == "path":
                a, b = self._prov(toks[0]), self._prov(toks[1]); path = self.known_path(a, b)
                if path is None: return "path: no land route"
                return "path P%d>%s  hours: %s" % (a, ">".join("P%d" % i for i in path), " ".join(
                    "%s %d" % (c, sum(g.provs[i].cost / p.stats[c]["spd"] * (p.stats[c]["climb"] if g.provs[i].terrain in D.HIGH else 1)
                                      for i in path)) for c in ("inf", "mot", "art")))
            if k == "unit":
                u = g.units.get(int(toks[0].lstrip("#")))
                if u is None or u.owner != pid: return "unit: not yours"
                return "%s#%d P%d s%d %s%s%s | %s, xp %d (%s), morale %d, suppression %d, readiness %d, %d h in combat%s%s" % (
                    u.type, u.id, u.prov, u.str, "path " + ">".join(map(str, u.path)) if u.path else "hold",
                    " fighting" if u.fighting else "", "" if u.supplied else " nosup", g.state(u), u.xp, D.XP_LEVELS[min(4, int(u.xp // 20))],
                    u.mor, u.sup, u.rdy, u.hours, ", mark %d of %d" % (u.st["mark"], p.stats[u.type]["mark"]), ", formation %s fxp %d" % (u.group, p.fxp.get(u.group, 0)) if u.group else "")
            if k == "near":
                rows = [self._prov_row(i) for i in sorted(self.region([self._prov(toks[0])], int(toks[1]) if len(toks) > 1 else 2)) if i in p.explored and g.provs[i].terrain != "water"]
                return "\n".join(rows) if rows else "near: nothing explored there"
            if k == "map":
                return "map (one char per cell = province id in base 36, ~ water; ids above 35 wrap)\n" + ascii_map(g.map, {i: "?" for i in range(g.n) if i not in p.explored})
            if k == "army":
                import json as _j
                return _j.dumps(self.army_view(int(toks[0]) if toks and toks[0].isdigit() else 0), ensure_ascii=False)
            if k in ("roads", "rails", "links"):
                mine = sorted((a_, b_, l_) for (a_, b_), l_ in self.p.known_link.items() if g.owner[a_] == pid or g.owner[b_] == pid)
                wk = [w for w in self.p.works if w[0] in ("road", "rail")]
                return "\n".join(["ROADS AND RAILWAYS of yours: %d road, %d rail stretches; being built: %s" % (sum(1 for x in mine if x[2] == 1), sum(1 for x in mine if x[2] == 2), ", ".join("%s P%d-P%d %dh" % (w[0], w[1], w[3], w[2]) for w in wk) or "nothing")] +
                                 ["%s P%d-P%d" % ("rail" if l_ == 2 else "road", a_, b_) for a_, b_, l_ in mine[:200]])
            if k in ("economy", "eco"):
                v = self.economy_view()
                return "\n".join(["ECONOMY income %.1f/day, unit upkeep %.1f, city and road upkeep %.1f; roads open with: %s" % (v["income"], v["upkeep"], v["maint"], " ".join(v["access"]) or "nobody"),
                                  "building: " + (" ".join("%s P%d (%d h)" % (w[0], w[1], w[2]) for w in v["works"]) or "nothing"),
                                  "prov dev/room infra agg yield/day  next dev cost | next infra cost"] +
                                 ["P%d %.1f/%.1f %.1f x%.2f %.1f  %s | %s" % (r["prov"], r["dev"], r["room"], r["infra"], r["agg"], r["yield_now"], r["dev_text"], r["infra_text"]) for r in v["provs"][:40]])
            if k in ("depots", "depot"):
                return "\n".join(["DEPOTS prov share weight serves load/capacity output  (new one: %d res, %d h)" % (D.DEPOT_COST, D.DEPOT_HOURS)] +
                                 ["P%d %d%% w%g serves %d load %.1f/%g output x%.2f%s" % (d, round(v["share"] * 100), v["weight"], v["serves"], v["load"], v["capacity"], v["output"], " (opens in %d h)" % v["opens_in"] if v["opens_in"] else "") for d, v in self.depot_view().items()] +
                                 ["enemy depots seen: " + (" ".join("P%d(%s)" % (d, self.g.players[o].faction) for d, o in sorted(self.p.known_depots.items())) or "none")])
            if k == "env":
                la = g.provs[p.capital].lat; t = g.tick; sd = 24 * D.SEASON_DAYS; own_ = g.owned[self.pid]
                return "season %s (day %d of %d), next season in %d h; your faction: %s, %s\nfrozen now in your land: %s\nfreezes in winter: %s\njungle you know: %s" % (
                    D.SEASONS[g.season_at(t, la)], (t % sd) // 24 + 1, D.SEASON_DAYS, sd - t % sd, "winter-hardened" if p.hardy else "not winter-hardened", "tropical" if p.tropic else "not tropical",
                    _ids(sorted(i for i in own_ if i in g.cold)) or "none", _ids(sorted(i for i in own_ if g.freezes(i, 3))) or "none", _ids(sorted(i for i in p.explored if i in g.jungle)) or "none")
            if k in ("powers", "power"):
                rows = ["POWERS as far as you have seen: faction relation land cities deposits/day(steel oil rare coal rubber) on the land you know to be theirs"]
                for n_, v in self.powers_view().items():
                    rows.append("%s %s land %d cities %d deposits %s%s" % (n_, v["relation"], v["land"], v["cities"], " ".join("%s %d" % (k_, v["deposits"][k_]) for k_ in D.STRAT), " (you)" if v.get("me") else ""))
                return "\n".join(rows)
            if k in ("dip", "diplomacy"):
                import json as _j
                return _j.dumps(self.dip_view(), ensure_ascii=False)
            if k == "tech":
                rows = []
                for line, t in self.tech_view().items():
                    if toks and not line.startswith(toks[0]): continue
                    rows.append("%s L%d %s%s" % (line, t["level"], t["status"], " next: " + _cost(t["cost"]) + " %dh" % t["hours"] if t["cost"] else ""))
                return "\n".join(rows + ["results so far: " + ("; ".join(x["text"] for x in p.tech_log) or "none")])
            if k == "budget":
                import json as _j
                return _j.dumps(self.budget_view(), ensure_ascii=False)
            if k == "tree":
                rows = ["year %d, your age: %s. discovery [age] status, your price now, hours; (n) = factions you have met that have it" % (A.year(g.tick), A.ERAS[A.era_of(p)])]
                for t, v in self.tree_view().items():
                    if toks and toks[0] not in (v["status"], v["age"]) and not t.startswith(toks[0]): continue
                    rows.append("%s [%s] %s%s%s (%d)" % (t, v["age"], v["status"], " needs " + ",".join(v["missing"]) if v["missing"] else "", " %s (now %d res) %dh" % (_cost(v["cost"]), v["res_now"], v["hours"]) if v["cost"] and v["status"] != "researching" else "", v["known_to_met"]))
                return "\n".join(rows)
            if k == "sea":
                v = self.sea_view(self._prov(toks[0]) if toks else None)
                return "\n".join(["SEA ZONES you know: id deep? reach(zones from your coast, - = out of reach) closed? : neighbouring zones | shore provinces"] +
                                 ["%d%s reach %s%s%s : %s | %s" % (i, " deep" if z["deep"] else "", z["reach"] if z["reach"] else "-", " CLOSED" if z["closed"] else "", " yours %d" % z["mine"] if z["mine"] else "",
                                                               ",".join(map(str, z["nbrs"])), ",".join(map(str, z["coast"][:12]))) for i, z in list(v.items())[:120]])
            if k == "enemy":
                out = ["P%d%s" % (i, self._est_str(i)) for i in sorted(p.visible) if self._est_str(i)]
                return "enemy seen: " + (" ".join(out) if out else "none")
        except CmdError as ex: return "q %s: %s" % (k, ex)
        except (IndexError, ValueError, KeyError): return "q %s: bad arguments" % k
        return "q: unknown query '%s'" % k

    def _est_str(self, prov):
        e = self.g.estimate(self.pid, prov)
        if not e or not e[3]: return ""
        return "[%s s%d]" % (_counts(e[1]), e[2]) if e[0] == 2 else "[?×%d s~%d]" % (e[3], e[2])

    # ============================================================ policies (standing-order programs)
    def set_policy(self, name, code, every=6):
        """Install python source defining tick(api); it runs inside the engine every `every` hours.
        Empty code removes it. See PolicyApi for what it can see and do."""
        if not code or not code.strip():
            self.policies.pop(name, None); self.sources.pop(name, None); return "policy %s removed" % name
        bi = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
        safe = {k: bi[k] for k in ("abs", "all", "any", "bool", "dict", "enumerate", "filter", "float", "int", "len", "list",
                                   "map", "max", "min", "range", "reversed", "round", "set", "sorted", "str", "sum", "tuple",
                                   "zip", "isinstance", "print", "next", "iter", "Exception", "ValueError", "KeyError",
                                   "IndexError", "TypeError", "ZeroDivisionError", "AttributeError", "frozenset", "divmod", "pow")}
        env = {"__builtins__": safe, "math": math}
        try:
            import ast
            if any(isinstance(x, (ast.Import, ast.ImportFrom)) for x in ast.walk(ast.parse(code))): return "policy error: ImportError: __import__ not found"      # the same on every interpreter
            exec(compile(code, "<policy %s>" % name, "exec"), env)
        except Exception as ex: return "policy error: %s: %s" % (type(ex).__name__, ex)
        if not callable(env.get("tick")): return "policy error: define tick(api)"
        self.sources[name] = (code, max(1, int(every)))
        self.policies[name] = dict(fn=env["tick"], every=max(1, int(every)), mem={}, ms=0.0, calls=0, err=None)
        return "policy %s installed (every %d h)" % (name, every)

    def set_candidate(self, name, code, every=6):
        """Store a strategy for trials without running it. `trial` compares candidates; `adopt` installs one."""
        if not name.replace("_", "").isalnum() or name == "current": return "candidate error: bad name"
        try: compile(code, "<candidate %s>" % name, "exec")
        except SyntaxError as ex: return "candidate error: %s" % ex
        if len(self.candidates) >= 8 and name not in self.candidates: self.candidates.pop(next(iter(self.candidates)))
        self.candidates[name] = (code, max(1, int(every)))
        return "candidate %s stored" % name

    def source(self, name):
        from .wargame import library
        if name == "current": return self.sources.get("main")
        if name in self.candidates: return self.candidates[name]
        code = library(name)
        return (code, 6) if code else None

    def border(self):
        """Your provinces that touch enemy land (or, before contact, neutral land) -> weight."""
        g, p, pid = self.g, self.p, self.pid; en = {}; ne = {}
        for i in range(g.n):
            if g.owner[i] != pid: continue
            w = 0.0; hit = False; neu = False
            for b in g.provs[i].nbrs:
                ko = p.known_owner.get(b, -1)
                if ko >= 0 and ko != pid:
                    hit = True; e = g.estimate(pid, b)
                    if e and e[3]: w += e[2] / 100.0
                elif ko == -1 and g.owner[b] != pid: neu = True
            if hit: en[i] = 1.0 + w + (1.0 if i == p.capital or g.provs[i].city else 0.0)
            if neu: ne[i] = 1.0
        self.neutral_border = sorted(ne)
        return en or ne

    def _run_expand(self):
        """Standing order 'expand': each unit walks to a neutral province nobody else is heading for, takes its key
        point, and goes on to the next. Without a target it is the nearest one; with 'expand <sel> P<id>' it is the
        reachable one closest to the province the commander picked. It keeps away from provinces where enemy units
        are seen. When no neutral land is left within reach the unit joins the front order."""
        g = self.g; pid = self.pid; ko = self.p.known_owner; provs = g.provs; ex = self.p.explored; vis = self.p.visible
        self.expand = set(i for i in self.expand if i in g.units)
        if not self.expand: return
        com = {}; kloc = self.p.known_local; X = self.expand_x          # strength already committed to each free province
        for i in self.expand:
            u = g.units[i]; t_ = u.path[-1] if u.path else (u.prov if g.owner[u.prov] < 0 else None)
            if t_ is not None: com[t_] = com.get(t_, 0.0) + u.str
        taken = set(t_ for t_, v_ in com.items() if v_ >= max(1.0, X * kloc.get(t_, 0.0)))
        for i in sorted(self.expand):
            u = g.units[i]
            if u.path or u.fighting or u.rout: continue
            if g.owner[u.prov] < 0 and g.local[u.prov] > 0 and u.str >= 40: continue      # still facing the locals here
            if u.str < 40:
                if g.owner[u.prov] != pid: g._retreat(u)
                continue
            to = self.expand_to.get(i); tp = provs[to] if to is not None else None
            seen = {u.prov}; q = [u.prov]; k = 0; goal = -1; best = None
            while k < len(q) and k < 400:
                a = q[k]; k += 1
                for b in provs[a].nbrs:
                    if b in seen: continue
                    seen.add(b); o = ko.get(b, -1) if g.owner[b] != pid else pid
                    if o == pid: q.append(b)
                    elif o == -1 and b in ex and provs[b].terrain != "water" and b not in taken and not (b in vis and g.enemy_at(b, pid)) and not any(
                            ko.get(c, -1) not in (-1, pid) for c in provs[b].nbrs):
                        if tp is None: goal = b; break
                        d = (provs[b].cx - tp.cx) ** 2 + (provs[b].cy - tp.cy) ** 2
                        if best is None or d < best: best = d; goal = b
                if goal >= 0 and tp is None: break
            if goal >= 0:
                com[goal] = com.get(goal, 0.0) + u.str
                if com[goal] >= max(1.0, X * kloc.get(goal, 0.0)): taken.add(goal)
                g.order_move(pid, [i], goal, known=ex)
            else: self.expand.discard(i); self.expand_to.pop(i, None); self.front.add(i)

    def _run_explore(self):
        """Standing order 'explore': each unit walks to the nearest province its side has never seen (through land
        it knows), looks, and goes on. It turns away from provinces where enemy units are seen. When nothing
        unexplored is in reach the order ends and the unit holds."""
        g = self.g; pid = self.pid; provs = g.provs; ex = self.p.explored; vis = self.p.visible
        self.explore = set(i for i in self.explore if i in g.units)
        if not self.explore: return
        taken = set(g.units[i].path[-1] for i in self.explore if g.units[i].path)
        fail = self.__dict__.setdefault("_ex_fail", {}); foe = {}; nex = len(ex); tick = g.tick
        for i in sorted(self.explore):
            u = g.units[i]
            if u.rout: continue
            if u.path:
                if u.path[-1] in ex or (u.path[0] in vis and g.enemy_at(u.path[0], pid)): g.order_hold(pid, [i])     # already seen from afar, or enemy ahead
                else: continue
            fk = fail.get(u.prov)
            if fk is not None and fk[0] == nex and tick - fk[1] < 12: self.explore.discard(i); continue      # just searched from here: nothing in reach
            seen = {u.prov}; q = [u.prov]; k = 0; goal = -1
            while k < len(q) and k < 1500 and goal < 0:
                a = q[k]; k += 1
                for b in provs[a].nbrs:
                    if b in seen: continue
                    seen.add(b)
                    if b not in ex:
                        if b not in taken and b not in self.no_go: goal = b; break
                    elif provs[b].terrain != "water":
                        e = foe.get(b)
                        if e is None: e = foe[b] = b in vis and g.enemy_at(b, pid)
                        if not e: q.append(b)
            if goal < 0: fail[u.prov] = (nex, tick); self.explore.discard(i); continue
            if g.order_move(pid, [i], goal, known=ex): self.no_go.add(goal)        # water or no way in
            else: taken.add(goal)

    def _run_front(self):
        """Spread the front-order units along the border, more where more enemy is seen. Units in battle stay."""
        g = self.g
        self.front = set(i for i in self.front if i in g.units)
        if not self.front: return
        bd = self.border()
        if not bd: return
        us = []
        for i in sorted(self.front):                          # rotation: worn units rest behind the line, then return
            u = g.units[i]
            if u.str < 40 and not u.fighting: self.resting.add(i)
            elif u.str >= 85: self.resting.discard(i)
            if u.plan_t >= 0: continue
            if i in self.resting:
                if u.contact or u.prov in bd:
                    rear = [b for b in g.provs[u.prov].nbrs if g.owner[b] == self.pid and b not in bd and b in self.p.supplied]
                    if rear and not u.path: g.order_move(self.pid, [u.id], rear[0], own_only=True)
                continue
            us.append(u)
        if not us: return
        tot = sum(bd.values()); n = len(us)
        want = {b: max(1 if n >= len(bd) else 0, int(n * w / tot)) for b, w in bd.items()}
        have = {b: [] for b in bd}; spare = []
        for u in us:
            d = u.path[-1] if u.path else u.prov
            if d in have and (len(have[d]) < want[d] * 1.5 + 2 or u.fighting):     # a unit in the line stays there: only a clear surplus is moved on
                have[d].append(u)
                if not u.path and not u.dig and g.fort_level(d) < D.FORT_MAX and g.owner[d] == self.pid: u.dig = True
            elif not u.fighting: spare.append(u)
        need = sorted(((want[b] - len(have[b])) / max(1.0, want[b]), b) for b in bd if len(have[b]) < 0.75 * want[b] or not have[b])
        need.reverse()
        P = g.provs
        for frac, b in need:
            bx, by = P[b].cx, P[b].cy
            for _ in range(want[b] - len(have[b])):
                if not spare: return
                u = min(spare, key=lambda x: ((P[x.prov].cx - bx) ** 2 + (P[x.prov].cy - by) ** 2, x.id)); spare.remove(u)
                if u.prov != b: g.order_move(self.pid, [u.id], b, own_only=True)
                else: g.order_hold(self.pid, [u.id])
        for u in spare:                       # leftovers: stop wandering once they are on any border province
            d = u.path[-1] if u.path else u.prov
            if d not in bd:
                ux, uy = P[u.prov].cx, P[u.prov].cy
                b = min(bd, key=lambda b: ((P[b].cx - ux) ** 2 + (P[b].cy - uy) ** 2, b)); g.order_move(self.pid, [u.id], b, own_only=True)

    def pre_tick(self):
        g = self.g
        if g.over or not self.p.alive: return
        if g.tick % 6 == 3: self._run_front(); self._run_expand()
        if g.tick % 2 == 1: self._run_explore()
        for name, sc in list(self.policies.items()):
            if g.tick % sc["every"]: continue
            api = PolicyApi(self, sc["mem"]); t0 = time.perf_counter()
            try: sc["fn"](api)
            except Exception as ex:
                sc["err"] = "%s: %s" % (type(ex).__name__, ex)
                g.event(self.pid, "warn", "policy %s crashed: %s" % (name, sc["err"]), key=("pol", name), gap=240)
            sc["ms"] += (time.perf_counter() - t0) * 1000; sc["calls"] += 1
            if sc["calls"] > 20 and sc["ms"] / sc["calls"] > self.policy_budget_ms + 0.2 * self.p.n_units:    # budget grows with the army
                del self.policies[name]
                g.event(self.pid, "warn", "policy %s removed: over time budget" % name)


class PolicyApi:
    """Snapshot handed to a policy's tick(api). Plain data only; orders go through api.cmd().

    (tick(api) is called only when the hour is a multiple of 6, so api.t is always 0, 6, 12, ...; a test like api.t % 24 == 3 never fires)
    api.t                 tick (hours)              api.res      bank       api.mp  manpower pool
    api.costs             {type: (res cost, manpower cost)}       api.unit_costs  {type: dict(res, mp, steel, oil, rare, hours)}
    api.stock             dict(res, steel, oil, rare, coal, rubber): your stockpiles      api.income_by  dict(res (net of upkeep), steel, oil (net of fuel), rare, coal, rubber, mp) per day
    api.stats             {type: dict(atk, dfn, spd, range, hard, ap, ...)}  your CURRENT unit values, upgrades included
    api.tech              {line: dict(level (levels done), status 'open'|'researching'|'dead end'|'complete', cost (dict for the next level, or None), hours)}
    api.tech_log          [dict(t, line, level, ok, gain, text)]  every result so far; whether a line goes further is unknown until tried
    api.research          [[line, level, hours left]]  projects under way (at most 2)
    api.army(level=0)     dict: condition of your own army and supply, at the detail you choose (same as `q army`): 0 totals {n, rdy, mor, str, ready, spent,
                          dry, moving, contact, fighting, unsupplied}; 1 adds by_type, by_order, front {units_per_province, stock_mean, stock_empty, inflow_per_h,
                          burn_per_h, short}; 2 adds provinces [{prov, n, rdy, mor, dry, moving, stock, inflow, burn, hops, fort, border}]
    api.count(name, n=1)  add to a tally of your own (up to 60 names). It changes nothing in the war; your tallies are shown to you in the review afterwards,
                          e.g. to see how often a condition in your orders was met or not
    api.me                your faction's name
    api.met               [names of factions you have come across]   the only ones you can deal with
    api.pacts             {faction: dict(since, ends (hour or None), broken_by, kind 'pact'|'alliance'|'truce')}
    api.deals             [dict(id, with, you_give {what: n}, they_give {what: n}, since, until)]   standing daily deliveries; stop one with `cancel <id>`
    api.powers            {faction (you and everyone you met): dict(relation, land, cities, deposits {kind: per day}, deliveries)}   only from land you have explored
    api.season            dict(name, day, days, next_in_hours, hardy, tropic)     api.no_fuel  True while your oil stock is empty; api.fuel_per_day
                          api.provs[id] also has lat, cold (frozen now), freezes (in winter), jungle, coal, rubber
    api.offers_in         [dict(id, frm, kind 'pact'|'alliance'|'trade'|'supply', hours, they_give {what: n}, you_give {what: n}, lapses)]   answer with accept/reject <id>
                          they_give / you_give are always seen from YOUR side, in offers_in, offers_out and deals alike: you_give is what leaves your bank.
                          `offer <f> trade <A> for <B>` means YOU give A and get B.
    api.offers_out        [the same with `to`]         api.inbox  [dict(t, frm, text)] the last 20 letters you received
    api.owner_name        {province you know to be someone's: faction name}   whose land is where, as far as you have seen
    api.marks             {type: current model number}; a unit with u.old True is an older model (u.mark) and fights with its old values
    api.links             [[a, b, level]] every road (level 1) and railway (2) between two provinces that you have seen (your own always current); api.link_rules = the numbers; api.link_cost(a, b, 'road'|'rail') = dict(res[, steel], hours) for that one stretch
                          works of roads and railways are 4-item lists [kind 'road'|'rail', province, hours left, other province]; economy also has roads, rails (stretches you hold)
    api.economy           dict(income, upkeep, maint, works [[kind 'dev'|'infra', province, hours left]], access [factions sharing roads with you],
                          provs [dict(prov, dev, room, infra, agg, yield_now, base, city, dev_cost, infra_cost, can_dev, can_infra)] richest first)   see ECONOMY
                          provs is a LIST of dicts and holds only your provinces with dev > 0 or infra > 0 (others: api.provs[id]). prov = province id; room = the
                          development level up to which levels count in full (a number of levels, not a share); dev_cost / infra_cost = price of the NEXT level as a
                          dict, e.g. {"res": 150, "coal": 24} / {"res": 60, "steel": 12}, or None at the top level; can_dev / can_infra = True if you can pay it now.
                          works is a list of 3-item lists, e.g. [["dev", 1458, 40], ["infra", 1460, 12]]. Example: for r in api.economy["provs"]:
                          if r["can_dev"] and r["dev"] + 1 <= r["room"]: api.cmd("develop P%d" % r["prov"])
    api.depots            {province: dict(share, weight, opens_in, serves, load, capacity, output, city)}  your depots (see DEPOTS); api.depot_cost; api.enemy_depots {province: faction} seen so far
    api.refit_cost        {type: dict(res, steel, oil, rare)}  price of `refit` per unit of that type; api.old_units = number of your units not on the current model
    api.income            net income per day        api.capital  your capital province id
    api.provs             {id: dict(terrain, elev (0-3), y, mp, fort (last seen), stock, flow (supplies/h), city, nbrs, owner 'me'|'enemy'|'neutral' (last known),
                          who (owner's player id or -1), visible, supplied, steel, oil, rare (deposit yield per day, 0 if none), harsh (desert/tundra), sea (neighbours across water), river (neighbours on the far bank of a great river), x, y0 (key point, map cells))}   ONLY provinces you have explored (seen at least once); use .get() for anything else
    api.me, api.players   your player id, number of factions (all others are enemies)
    api.units             [dict(id, type, prov, str, rdy, plan (target or -1), bonus, dry, path, fighting, supplied, group, front (under the front
                          or the expand standing order), expand, explore, xp (experience 0-100), mor (morale 0-100), sup (suppression 0-100), mark (model number), old (True: outdated model, see api.marks),
                          state ('ready' 'moving' 'assault' 'defending' 'pinned' 'routing' 'shaken' 'preparing' 'digging' 'refitting'))]
    api.formations        {group name: formation experience 0-100}
    api.border            {your province touching enemy land: weight}  (before any contact: provinces touching neutral land)
    api.neutral_border    [your provinces touching neutral land]   free land to take lies next to these
    api.unexplored        [explored provinces with a neighbour you have never seen]   the edge of your map knowledge
    api.enemy             {prov: dict(n, str, exact, types, who)}   enemy units you can currently see
    api.enemy_capital     nearest known enemy capital (province id or None)      api.enemy_capitals  {player id: province}
    api.year, api.age     the calendar year (0-2000) and the age of your latest discovery      api.can_raise  [unit kinds you can raise now]; api.stats / api.costs / api.unit_costs hold only those
    api.tree              {discovery: dict(status 'known'|'researching'|'open'|'locked', age, needs [..], missing [..], opens [kinds], new_models [kinds], effect, cost (dict, your price now), res_now (res it takes in all if started now, buying what you lack), hours (still needed), seeped (0..1 share already come in from abroad), known_to_met)}
                          api.known = [discoveries you have]; start one with api.cmd("research <discovery>"). api.fort_cap = highest fort level you can build.
    api.budget            dict(res, income, upkeep_units, upkeep_works, net (per day), days_left (None unless net < 0), upkeep_share (upkeep / income), earned, spent {units, research, works, refit, depots, missiles},
                          upkeep_by_kind {kind: res per day}, units, in_training, res_in_training, research, stock, income_by, fuel_per_day,
                          open_discoveries {discovery: dict(cost, res_now, bought (res of it that buys lacking resources), can_pay_now, lacking [resources], days_of_net_income)})      see CAPITAL
    api.sea               {sea zone id: dict(nbrs [zones], coast [land provinces on its shore], deep, x, y0, visible, reach (zones from your coast, None = beyond your shipping), closed (an enemy fleet shuts it to you), mine (your units there))}
                          only zones you have seen. api.provs[id]['coast'] = the zones a land province touches. api.transport_speed (0 = your troops cannot go by sea), api.overseas = {id: zones away} coastal provinces not yours that your shipping reaches (see PREPARED ATTACK), api.sea_reach, api.ocean
    api.wars              [factions you are at war with now]      api.missiles, api.satellites (True/False), api.strike_cost
                          api.units rows also have dom (0 land, 1 sea, 2 air), base (aircraft: its base province), at_sea (True for ships and for troops on transports; their prov is then a sea zone id, which is in api.sea, not in api.provs)
    api.mem               dict kept between calls
    api.model             learned parameters loaded from a JSON file for this side ({} if none); see tools/fit_battle_model.py
    api.cmd(line)         run a command line, returns the result text
    api.q(text)           run a query            api.path(a, b)  list of provinces or None
    """

    def __init__(self, sess, mem):
        g = sess.g; p = sess.p; pid = sess.pid; self._s = sess; self.mem = mem
        self.t = g.tick; self.res = p.res; self.income = p.income - p.upkeep; self.capital = p.capital
        self.model = sess.model
        self.mp = p.mp; self.mp_income = p.mp_income; self.costs = {c: (s["cost"], s["mp"]) for c, s in p.stats.items()}
        self.unit_costs = {c: dict(res=s["cost"], mp=s["mp"], steel=s["steel"], oil=s["oil"], rare=s["rare"], hours=s["time"]) for c, s in p.stats.items()}
        self.stock = dict(res=p.res, **p.bank)
        self.income_by = dict(res=p.income - p.upkeep, mp=p.mp_income, **p.inc); self.income_by["oil"] -= p.fuel
        self.stats = {c: dict(s) for c, s in p.stats.items()}
        self.deals = sess.dip_view()["deals"]; self.powers = sess.powers_view(); self.no_fuel = p.nofuel; self.fuel_per_day = p.fuel
        _sd = 24 * D.SEASON_DAYS; self.season = dict(name=D.SEASONS[g.season_at(g.tick, g.provs[p.capital].lat)], day=(g.tick % _sd) // 24 + 1, days=D.SEASON_DAYS, next_in_hours=_sd - g.tick % _sd, hardy=p.hardy, tropic=p.tropic)
        dv = sess.dip_view(); self.me = p.faction; self.met = dv["met"]; self.pacts = dv["pacts"]; self.offers_in = dv["offers_in"]; self.offers_out = dv["offers_out"]; self.inbox = dv["inbox"]
        self.owner_name = {i: g.players[o].faction for i, o in p.known_owner.items() if o >= 0 and o != p.id}
        self.marks = {c: s["mark"] for c, s in p.stats.items()}; self.refit_cost = {c: g.refit_cost(p.id, c) for c in p.stats}
        self.old_units = sum(1 for u in g.punits[p.id].values() if u.st is not p.stats[u.type])
        self.economy = sess.economy_view(); kd = p.known_dev
        self.links = [[a_, b_, l_] for (a_, b_), l_ in sorted(p.known_link.items())]; self.link_rules = dict(road=dict(res=D.ROAD_COST, hours=D.ROAD_HOURS, speed=D.ROAD_MOVE, supply_step=D.ROAD_HOP, keep=D.ROAD_KEEP, needs=D.LINK_NEED["road"]), rail=dict(res=D.RAIL_COST, steel=D.RAIL_NEED[1], hours=D.RAIL_HOURS, speed=D.RAIL_MOVE, supply_step=D.RAIL_HOP, keep=D.RAIL_KEEP, needs=D.LINK_NEED["rail"]), river_factor=D.LINK_RIVER)
        self.depots = sess.depot_view(); self.depot_cost = D.DEPOT_COST; self.enemy_depots = {d: g.players[o].faction for d, o in p.known_depots.items()}
        self.tree = sess.tree_view(); self.known = sorted(p.known); self.year = A.year(g.tick); self.age = A.ERAS[A.era_of(p)]; self.can_raise = sorted(p.stats)
        self.budget = sess.budget_view(); self.sea = sess.sea_view(); self.wars = sorted(e.faction for e in g.players if e.id != pid and e.alive and g.war(pid, e.id))
        self.overseas = {}
        if p.sail > 0:
            rz = g.searange[pid]; blk = g.blockade[pid]; ex = p.explored; ow = g.owner
            for z, d in rz.items():
                if z in blk: continue
                for i in g.provs[z].coast:
                    if ow[i] != pid and i in ex and d < self.overseas.get(i, 99): self.overseas[i] = d
        self.fort_cap = p.fort_cap; self.transport_speed = p.sail; self.sea_reach = p.sea_reach; self.ocean = p.ocean; self.missiles = p.missile; self.satellites = p.sat; self.strike_cost = dict(D.STRIKE)
        self.tech = sess.tech_view(); self.tech_log = [dict(x) for x in p.tech_log]; self.research = [list(r) for r in p.research]
        self.enemy_capitals = dict(p.known_caps); self.enemy_capital = sess._near_cap()
        ko = p.known_owner; rel = p.explored
        self.players = len(g.players); self.me = pid
        self.provs = {pr.id: dict(terrain=pr.terrain, elev=pr.elev, y=pr.y, mp=pr.mp, city=pr.city, nbrs=pr.nbrs,
                                  fort=p.known_fort.get(pr.id, 0), stock=g.stock[pr.id] if g.owner[pr.id] == pid else 0,
                                  flow=g.stock_flow(pid, pr.id),
                                  owner="me" if ko.get(pr.id, -1) == pid else "neutral" if ko.get(pr.id, -1) < 0 else "enemy",
                                  who=ko.get(pr.id, -1), visible=pr.id in p.visible, harsh=bool(pr.biome), sea=pr.sea, river=sorted(pr.river), coast=list(pr.coast), x=pr.cx, y0=pr.cy, steel=pr.steel, oil=pr.oil, rare=pr.rare, coal=pr.coal, rubber=pr.rubber, lat=pr.lat, cold=pr.id in g.cold, freezes=g.freezes(pr.id, 3), jungle=pr.id in g.jungle,
                                  dev=g.dev[pr.id] if g.owner[pr.id] == pid else kd.get(pr.id, (0.0, 0.0))[0], infra=g.infra[pr.id] if g.owner[pr.id] == pid else kd.get(pr.id, (0.0, 0.0))[1],
                                  agg=g.agg[pr.id] if g.owner[pr.id] == pid else None, yield_now=g.prod[pr.id] if g.owner[pr.id] == pid else None, room=g.room(pr.id) if g.owner[pr.id] == pid else None,
                                  locals=p.known_local.get(pr.id, 0),
                                  links={b_: p.known_link.get((pr.id, b_) if pr.id < b_ else (b_, pr.id), 0) for b_ in g.lk[pr.id]} if g.lk[pr.id] else {},
                                  supplied=pr.id in p.supplied) for pr in (g.provs[i] for i in sorted(rel)) if pr.terrain != "water"}
        self.units = [dict(id=u.id, type=u.type, prov=u.prov, str=u.str, path=list(u.path), fighting=bool(u.fighting),
                           supplied=u.supplied, group=u.group, front=u.id in sess.front or u.id in sess.expand, expand=u.id in sess.expand, explore=u.id in sess.explore, rdy=u.rdy, plan=u.plan_t, dom=u.st["dom"], base=u.base, at_sea=u.prov >= g.sea0, xp=u.xp, mor=u.mor, sup=u.sup, state=g.state(u), mark=u.st["mark"], old=u.st is not p.stats[u.type],
                           bonus=u.plan_b, dry=u.dry)
                      for u in g.punits[pid].values()]
        self.formations = dict(p.fxp)
        self.border = sess.border(); self.neutral_border = list(sess.neutral_border)
        self.unexplored = [i for i in sorted(rel) if g.provs[i].terrain != "water" and any(b not in rel for b in g.provs[i].nbrs)]
        self.enemy = {}
        for i in p.visible:
            if not g.pos[i]: continue
            e = g.estimate(pid, i)
            if e and e[3]: self.enemy[i] = dict(n=e[3], str=e[2], exact=e[0] == 2, types=e[1], who=next(u.owner for u in g.pos[i] if u.owner != pid))

    def army(self, level=0): return self._s.army_view(level)
    def count(self, name, n=1):
        c = self._s.counters; name = str(name)[:40]
        if name in c or len(c) < 60: c[name] = c.get(name, 0) + n
    def cmd(self, line): return self._s.act(line)
    def q(self, text): return self._s.query(text)
    def path(self, a, b): return self._s.known_path(a, b)

    def link_cost(self, a, b, kind="road"):
        """Price of one stretch of road or railway between two neighbouring provinces."""
        res, k, n, h = self._s.g.link_cost(int(a), int(b), kind); out = dict(res=res, hours=h)
        if k: out[k] = n
        return out
