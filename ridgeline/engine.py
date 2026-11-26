"""Ridgeline v2 engine: provinces, divisions, territory income, manpower, supply lines, forts, fog.

1 tick = 1 game hour. Deterministic per seed. The engine knows nothing about drawing or about LLMs:
render.py turns state into plain scene/frame data, iface.py turns it into text for agents.
"""
import heapq
import math
import random

from . import data as D
from .mapgen import gen_map


class Unit:
    __slots__ = ("id", "owner", "type", "st", "prov", "path", "prog", "str", "group", "fighting", "supplied", "born",
                 "contact", "dig", "rdy", "plan_t", "plan_b", "dry", "x", "y", "ox", "oy", "last", "rout",
                 "xp", "mor", "sup", "settled", "bk", "hours")

    def __init__(self, id, owner, type, st, prov):
        self.id = id; self.owner = owner; self.type = type; self.st = st; self.prov = prov
        self.path = []; self.prog = 0.0; self.str = 100.0; self.group = ""; self.fighting = 0; self.supplied = True
        self.born = 0; self.contact = False; self.dig = False
        self.rdy = 100.0; self.plan_t = -1; self.plan_b = 0.0; self.dry = False
        self.x = self.y = 0.0; self.ox = self.oy = 0.0     # position in map cells; offset of its place in the formation
        self.last = prov; self.rout = False                # province it came from; True while falling back (does not fight)
        self.xp = float(st.get("xp0", 10))                 # experience 0-100: green, trained, regular, veteran, elite
        self.mor = float(D.MOR_NEW)                        # morale 0-100: breaks and runs when it gets too low
        self.sup = 0.0                                     # suppression 0-100: pinned down by incoming fire, shoots less
        self.settled = True; self.bk = None; self.hours = 0     # standing on its spot; grid bucket; hours spent in combat


class Player:
    @property
    def capital(self): return self._cap

    @capital.setter
    def capital(self, v):
        # the capital is simply the faction's principal depot. A faction starts with everything in one place; that is a starting point, not a rule
        old = self._cap; self._cap = v
        if v is not None and v >= 0 and (not self.depots or list(self.depots) == [old]): self.depots = {v: 1.0}; self.depot_want = {v: 1.0}

    def all_stats(self): return [st for v in self.marks.values() for st in v]

    def __init__(self, pid, faction):
        self.id = pid; self.faction = faction; self.stats = D.stats_for(faction)
        for st in self.stats.values(): st["mark"] = 1
        self.marks = {c: [st] for c, st in self.stats.items()}   # every version of every type; old units keep their old one until refitted
        self.depots = {}; self.depot_want = {}; self.depot_build = {}      # depot province -> share of the treasury held there / wanted weight / hours until a new one opens
        self.known_depots = {}                                             # other factions' depots seen so far {prov: pid}
        self._cap = -1; self.hardy = False; self.tropic = True      # set from where the capital lies (world map)
        self.res = 0.0; self.mp = 0.0; self.capital = -1; self.queue = []     # [type, prov, hours_left]
        self.visible = set(); self.known_owner = {}; self.known_fort = {}
        self.met = set(); self._met_t = -99; self.mail = []     # factions come across so far; letters received
        self.events = []; self.throttle = {}; self.groups = {}
        self.supplied = set(); self.income = 0.0; self.upkeep = 0.0; self.mp_income = 0.0
        self.kills = 0; self.losses = 0; self.n_units = 0
        self.explored = set()                        # provinces ever seen: the only part of the map this player knows
        self.alive = True; self.known_caps = {}      # other players' capitals found so far {pid: prov}
        self.bank = {k: 0.0 for k in D.STRAT}      # stockpiles of the special resources (res stays in self.res)
        self.inc = {k: 0.0 for k in D.STRAT}; self.fuel = 0.0; self.nofuel = False   # oil burned per day by engines; True while the oil stock is empty       # their income per day
        self.tech = {}; self.dead = set(); self.research = []; self.tech_log = []   # line -> levels done; closed lines; [line, level, hours left]; results
        self.mult = dict(res=1.0, steel=1.0, oil=1.0, rare=1.0, mp=1.0, flow=1.0, heal=1.0, plan=1.0, rest=1.0); self.mor0 = 0.0
        self._depth = {}; self._size = {}                   # HIDDEN: how far each line goes for this faction, and what each level is worth
        self.works = []; self.maint = 0.0; self.known_dev = {}   # [kind, prov, hours left] being built; res a day spent on keeping up cities and roads; {prov: (dev, infra)} last seen
        self.fxp = {}                                # formation experience per group name (0-100): units that fight together


class Game:
    def __init__(self, factions=("aurum", "sable", "cinder"), seed=0, gmap=None, max_ticks=4800):
        """Any number of factions (free-for-all). Game(factions=("aurum", "sable"), gmap=gen_map(s, 126, 78, 22, 14, 2)) is
        the old small two-sided game."""
        if gmap is None and factions == "world":
            from .worldgen import gen_world
            gmap = gen_world(seed)
        if getattr(gmap, "world", False) and (factions == "world" or factions is None): factions = tuple(gmap.names)
        self.map = m = gmap or gen_map(seed, players=len(factions))
        self.seed = seed; self.rng = random.Random(seed * 7919 + 13)
        self.provs = m.provs; self.n = len(m.provs)
        self.stock_hop = D.STOCK_HOP / m.scale          # bigger maps: supply reaches proportionally further
        self.tick = 0; self.max_ticks = max_ticks; self.over = False; self.winner = None
        self.owner = [-1] * self.n
        self.cold = set(); self.jungle = set(i for i, pr in enumerate(self.provs) if pr.terrain == "forest" and abs(pr.lat) < D.JUNGLE_LAT and getattr(m, "world", False))
        self.hub = [{} for _ in factions]; self.throttle = [{} for _ in factions]; self.load = [{} for _ in factions]   # nearest depot per province; each depot's output factor and load
        self.stock = [0.0] * self.n; self.hops = [{} for _ in factions]       # supplies per province; distance from each capital
        self.fort = [0.0] * self.n                   # fort level 0..FORT_MAX (fractional while under construction)
        self.players = [Player(i, f) for i, f in enumerate(factions)]
        self.units = {}; self.next_id = 1
        self.pos = [[] for _ in range(self.n)]       # units standing in each province (one owner at a time)
        self.battles = {}; self.contacts = []
        self.assaults = {}; self.battle_log = []     # open assault episodes; finished ones (training data)
        self._sight = {}
        self.dev = [0.0] * self.n; self.infra = [0.0] * self.n; self.access = set()    # development and infrastructure per province; ordered pairs of factions that opened their roads to each other
        self.prod = [float(pr.y) for pr in self.provs]; self.prod_mp = [float(pr.mp) for pr in self.provs]; self.agg = [1.0] * self.n   # what each province yields now
        self.deals = {}; self.allies = set()         # standing deliveries {id: ...}; ordered pairs of allied factions
        self.pacts = {}; self.peace = set(); self.offers = {}; self.next_offer = 1; self.dip_log = []   # diplomacy: see the block of order_* below
        self._pfree = {}; self._pown = {}            # route caches: any land / own land only (cleared when borders move)
        self._index()
        for p in self.players:
            p.capital = m.capitals[p.id]; p.res = float(m.start_res[p.id]); p.mp = float(m.start_mp[p.id])
            for i in m.start_provs[p.id]: self.owner[i] = p.id; self.stock[i] = self.stock_cap(i) * 0.5
        self._own_dirty = True
        bank = getattr(m, "start_bank", None)
        for p in self.players:
            if bank: p.bank = {k: float(bank[p.id].get(k, 0)) for k in D.STRAT}
            la = abs(self.provs[p.capital].lat); p.hardy = la >= D.HARDY_LAT or self.provs[p.capital].biome == "tundra"; p.tropic = la < D.TROPIC_LAT or not getattr(m, "world", False)
            self.hide_tech(p, seed * 9973 + p.id * 101 + 17)
        for i, pr in enumerate(self.provs):
            if pr.city: self.dev[i] = D.DEV_START_CITY
        for p in self.players: self.dev[p.capital] = D.DEV_START_CAPITAL
        self._wealth()
        r = random.Random(seed * 31 + 5)
        for p in self.players:
            for (t, at) in m.start_units[p.id]:
                u = self.spawn(p.id, t, at); u.xp = min(60.0, u.xp + r.uniform(0, 30)); u.mor = r.uniform(60, 80)   # armies start uneven
        self._supply(); self._vision()

    # ---------------------------------------------------------------- indexes (what makes many units affordable)
    def _index(self):
        """Indexes kept up to date as things change, so one hour costs about (units doing something) + (all units)/8:
        units per player, a spatial grid, the set of units that need attention every hour, the provinces each
        player owns, and where each player has eyes."""
        n = len(self.players)
        self.punits = [dict() for _ in range(n)]           # units per player
        self.grid = {}; self.gown = {}                     # spatial hash: bucket -> units, bucket -> {owner: count}
        self.active = set()                                # ids that are moving, fighting, in contact, digging, preparing
        self.slices = [set() for _ in range(D.SLICES)]     # every unit by id % SLICES: the calm ones are served one slice per hour
        self.owned = [set() for _ in range(n)]             # provinces per player
        self.occ = [dict() for _ in range(n)]              # (province, sight range) -> units looking out from there
        self.vdirty = [True] * n; self.sdirty = [True] * n; self.ownvis = [set() for _ in range(n)]
        self._hot = []; self._odirty = True; self._tf = getattr(self, "_tf", {})
        for u in self.units.values(): self._add(u)

    @property
    def _own_dirty(self): return self._odirty

    @_own_dirty.setter
    def _own_dirty(self, v):
        """Set after editing self.owner by hand (tests, scenario tools): every ownership index is rebuilt."""
        self._odirty = bool(v)

    def _add(self, u):
        self.units[u.id] = u; self.punits[u.owner][u.id] = u; self.slices[u.id % D.SLICES].add(u.id)
        k = (int(u.x / D.BUCKET), int(u.y / D.BUCKET)); u.bk = k
        l = self.grid.get(k)
        if l is None: self.grid[k] = [u]; self.gown[k] = {u.owner: 1}
        else: l.append(u); c = self.gown[k]; c[u.owner] = c.get(u.owner, 0) + 1
        self._look(u, 1)

    def _look(self, u, d):
        o = self.occ[u.owner]; k = (u.prov, u.st["sight"] + self.provs[u.prov].elev); v = o.get(k, 0) + d
        if v <= 0: o.pop(k, None)
        else: o[k] = v
        if v == d or v <= 0: self.vdirty[u.owner] = True

    def _rebucket(self, u):
        k = (int(u.x / D.BUCKET), int(u.y / D.BUCKET))
        if k == u.bk: return
        old = u.bk; self.grid[old].remove(u); c = self.gown[old]
        if c[u.owner] <= 1:
            del c[u.owner]
            if not c: del self.grid[old]; del self.gown[old]
        else: c[u.owner] -= 1
        u.bk = k; l = self.grid.get(k)
        if l is None: self.grid[k] = [u]; self.gown[k] = {u.owner: 1}
        else: l.append(u); c = self.gown[k]; c[u.owner] = c.get(u.owner, 0) + 1

    def _enter(self, u, prov):
        """Unit u steps into another province."""
        self._look(u, -1); self.pos[u.prov].remove(u); self.pos[prov].append(u); u.last = u.prov; u.prov = prov; self._look(u, 1)

    def _set_owner(self, q, new):
        old = self.owner[q]
        if old == new: return
        self.owner[q] = new
        for o in (old, new):
            if o >= 0: self.sdirty[o] = True; self.vdirty[o] = True; self.ownvis[o] = None
        for a, b in self.access:
            if a == old or a == new: self.sdirty[b] = True
        if old >= 0: self.owned[old].discard(q)
        if new >= 0: self.owned[new].add(q)
        self._pown.clear()
        for p in self.players:
            if q in p.visible: p.known_owner[q] = new

    def state(self, u):
        """One word for what the unit is doing (for observations and front ends)."""
        if u.rout: return "routing"
        if u.fighting == 1: return "assault"
        if u.fighting == 2: return "pinned" if u.sup >= 50 else "defending"
        if u.path: return "moving"
        if u.mor < D.MOR_SHAKEN: return "shaken"
        if u.plan_t >= 0: return "preparing"
        if u.dig: return "digging"
        if u.str < 60 or u.rdy < 40: return "refitting"
        return "ready"

    # ---------------------------------------------------------------- basics
    def spawn(self, pid, code, prov):
        u = Unit(self.next_id, pid, code, self.players[pid].stats[code], prov); self.next_id += 1
        u.born = self.tick
        self._slot(u, sum(1 for o in self.pos[prov] if o.owner == pid)); self.pos[prov].append(u)
        pr = self.provs[prov]; u.x = pr.cx + u.ox; u.y = pr.cy + u.oy
        self._add(u); p = self.players[pid]; p.upkeep += u.st["upkeep"]; p.n_units += 1
        return u

    def _slot(self, u, k):
        """Place k in a sunflower spiral around the point the unit is sent to: groups occupy real space."""
        r = D.SLOT * k ** 0.5; a = k * 2.399963
        u.ox = r * math.cos(a); u.oy = r * math.sin(a)

    def enemy_at(self, prov, owner):
        for u in self.pos[prov]:
            if u.owner != owner and (u.owner, owner) not in self.peace: return True
        return False

    def event(self, pid, kind, text, key=None, gap=48):
        p = self.players[pid]
        if key is not None:
            if self.tick - p.throttle.get(key, -10 ** 9) < gap: return
            p.throttle[key] = self.tick
        p.events.append((self.tick, kind, text))

    def move_cost(self, u, prov):
        pr = self.provs[prov]
        return pr.cost / u.st["spd"] * (u.st["climb"] if pr.terrain in D.HIGH else 1.0) * (D.COLD_MOVE if prov in self.cold else 1.0) / (1.0 + D.INFRA_MOVE * self.infra[prov])

    def season_at(self, tick, lat=1.0):
        """Index into D.SEASONS for a latitude at a game hour (the south has the opposite season)."""
        return (tick // (24 * D.SEASON_DAYS) + (2 if lat < 0 else 0)) % 4

    def freezes(self, prov, season):
        """Would this province be frozen in the given local season (0 spring .. 3 winter)?"""
        pr = self.provs[prov]
        if pr.terrain == "water": return False
        if pr.biome == "tundra": return season != 1
        return season == 3 and (abs(pr.lat) >= D.COLD_LAT or (pr.elev >= 3 and abs(pr.lat) >= 25.0))

    def _seasons(self):
        """Once a day: which land is frozen now. Frozen ground changes every route, so the route caches go."""
        cold = set(i for i, pr in enumerate(self.provs) if self.freezes(i, self.season_at(self.tick, pr.lat)))
        if cold != self.cold:
            self.cold = cold; self._pfree.clear(); self._pown.clear()
            for p in self.players: self.sdirty[p.id] = True

    def path(self, src, dst, unit=None, own=None):
        """Fastest land route as a list of provinces after src; None if unreachable. own=pid: only through that
        player's provinces (redeployment behind the line must never wander into the enemy)."""
        if src == dst: return []
        ck = (src, dst, unit.type if unit else None, unit.owner if unit else -1)
        cache = self._pfree if own is None else self._pown
        if ck in cache:
            r = cache[ck]; return None if r is None else list(r)
        r = self._path(src, dst, unit, own)
        if len(cache) > 300000: cache.clear()
        cache[ck] = r
        return None if r is None else list(r)

    def _path(self, src, dst, unit, own, known=None):
        dist = {src: 0.0}; prev = {}; provs = self.provs; done = set()
        tx, ty = provs[dst].cx, provs[dst].cy; k = 2.2 / (unit.st["spd"] if unit else 1.0)     # A*: hours per cell on the cheapest ground (close to admissible)
        heap = [(0.0, src)]
        while heap:
            f, a = heapq.heappop(heap)
            if a == dst: break
            if a in done: continue
            done.add(a); d = dist[a]
            for b in provs[a].nbrs:
                if own is not None and self.owner[b] != own: continue
                if known is not None and b not in known and b != dst: continue
                nd = d + (self.move_cost(unit, b) if unit else provs[b].cost)
                if nd < dist.get(b, 1e18):
                    dist[b] = nd; prev[b] = a; pb = provs[b]
                    heapq.heappush(heap, (nd + k * ((pb.cx - tx) ** 2 + (pb.cy - ty) ** 2) ** 0.5, b))
        if dst not in prev: return None
        out = [dst]
        while out[-1] != src: out.append(prev[out[-1]])
        out.pop(); out.reverse()
        return out

    def fort_level(self, prov): return int(self.fort[prov] + 1e-6)

    def stock_cap(self, prov): return D.STOCK_CAP_CITY if self.provs[prov].city else D.STOCK_CAP

    def stock_flow(self, pid, prov):
        """Supplies arriving per hour: slower the further the province is from its nearest depot, and less when that depot serves more than it can handle."""
        h = self.hops[pid].get(prov)
        if h is None: return 0.0
        return D.STOCK_FLOW * self.players[pid].mult["flow"] / (1.0 + self.stock_hop * h) * self.throttle[pid].get(self.hub[pid].get(prov), 1.0) * (0.5 if self.provs[prov].biome else 1.0) * (D.COLD_FLOW if prov in self.cold else 1.0)

    def depot(self, u):
        """Province whose stock feeds this unit: where it stands if that is home, else the best adjacent home province."""
        if self.owner[u.prov] == u.owner: return u.prov
        best = -1; bs = 0.0
        for b in self.provs[u.prov].nbrs:
            if self.owner[b] == u.owner and self.stock[b] > bs: bs = self.stock[b]; best = b
        return best

    # ---------------------------------------------------------------- orders
    def _mine(self, pid, ids):
        return [self.units[i] for i in ids if i in self.units and self.units[i].owner == pid]

    def order_move(self, pid, ids, dst, own_only=False, known=None):
        """known: the set of provinces the player has explored; routes then use only those (plus the destination)."""
        us = self._mine(pid, ids)
        if not us: return "no units selected"
        if not (0 <= dst < self.n) or self.provs[dst].terrain == "water": return "P%d is not land" % dst
        bad = 0; cache = {}; k = sum(1 for o in self.pos[dst] if o.owner == pid and not o.path)
        for u in us:
            start = u.prov
            key = (start, u.type)
            if key not in cache:
                r = self.path(start, dst, u, pid if own_only else None)
                if r and known is not None and any(i not in known for i in r[:-1]):
                    r = self._path(start, dst, u, pid if own_only else None, known)      # the short cut crosses land never seen
                cache[key] = r
            p = cache[key]
            if p is None: bad += 1; continue
            if not p and u.prov == dst: p = [dst]            # already there: walk back to the key point
            u.path = list(p); u.dig = False; u.rout = False; u.settled = False; self.active.add(u.id)
            if not (u.prov == dst and not u.fighting): self._slot(u, k); k += 1
            if not (u.plan_t == dst and len(p) == 1): u.plan_t = -1; u.plan_b = 0.0     # a prepared attack only fits its target
        return "%d unit(s) cannot reach P%d" % (bad, dst) if bad else None

    def order_prepare(self, pid, ids, target):
        """Plan an attack on an adjacent province: the bonus builds while the units wait in place."""
        us = self._mine(pid, ids)
        if not us: return "no units selected"
        n = 0
        if (pid, self.owner[target]) in self.peace: return "P%d belongs to a faction you have a pact with (break it first)" % target
        for u in us:
            if target not in self.provs[u.prov].nbrs: continue
            u.path = []; u.prog = 0.0; u.rout = False; u.settled = False; self.active.add(u.id)
            if u.plan_t != target: u.plan_t = target; u.plan_b = 0.0
            n += 1
        return None if n else "units must stand next to P%d to prepare an attack on it" % target

    def order_hold(self, pid, ids):
        us = self._mine(pid, ids)
        if not us: return "no units selected"
        for u in us:
            if u.path: u.settled = False; self.active.add(u.id)
            u.path = []; u.prog = 0.0; u.dig = False; u.plan_t = -1; u.plan_b = 0.0; u.rout = False
        return None

    def order_fortify(self, pid, ids):
        us = self._mine(pid, ids)
        if not us: return "no units selected"
        n = 0
        for u in us:
            if self.owner[u.prov] != pid: continue
            u.path = []; u.prog = 0.0; u.dig = True; n += 1
        return None if n else "units must stand in your own province to fortify"

    # ---------------------------------------------------------------- upgrades
    def hide_tech(self, p, seed):
        """Draw the faction's hidden research table. Nothing outside the engine reads it."""
        r = random.Random(seed); p._depth = {}; p._size = {}
        for line in self.tech_lines():
            x = r.random(); d = 0; acc = 0.0
            for k, pr in enumerate(D.TECH_DEPTH):
                acc += pr
                if x < acc: d = k; break
            p._depth[line] = d; p._size[line] = [round(r.uniform(*D.TECH_SIZE), 3) for _ in range(D.TECH_LEVELS)]

    @staticmethod
    def tech_lines():
        return ["%s.%s" % (c, k) for c in D.UNITS for k in D.TECH_UNIT] + list(D.TECH_GENERAL)

    @staticmethod
    def tech_cost(line, level):
        d = D.TECH_UNIT[line.split(".")[1]] if "." in line else D.TECH_GENERAL[line]
        c = {k: v * level for k, v in d["cost"].items()}
        for k, v in d["needs"][:level]: c[k] = v * level
        return c

    def tech_status(self, pid, line):
        """What the faction itself can know about a line: (levels done, 'open' | 'researching' | 'dead end' | 'complete')."""
        p = self.players[pid]; lv = p.tech.get(line, 0)
        if any(r[0] == line for r in p.research): return lv, "researching"
        if line in p.dead: return lv, "dead end"
        return lv, "complete" if lv >= D.TECH_LEVELS else "open"

    def order_research(self, pid, line):
        p = self.players[pid]
        if line not in p._depth: return "unknown line '%s' (see 'q tech')" % line
        lv, st = self.tech_status(pid, line)
        if st != "open": return "%s is %s" % (line, "already being researched" if st == "researching" else st)
        if len(p.research) >= D.TECH_SLOTS: return "all %d research slots are busy" % D.TECH_SLOTS
        cost = self.tech_cost(line, lv + 1)
        for k, v in cost.items():
            have = p.res if k == "res" else p.bank[k]
            if have < v: return "need %d %s (have %d)" % (v, k, have)
        for k, v in cost.items():
            if k == "res": p.res -= v
            else: p.bank[k] -= v
        p.research.append([line, lv + 1, D.TECH_HOURS * (lv + 1)])
        return None

    def _finish_research(self, p, line, level):
        """The moment of truth: only now does the faction learn whether the line went any further."""
        if level > p._depth[line]:
            p.dead.add(line); text = "%s level %d: DEAD END, nothing gained, the line is closed" % (line, level)
            p.tech_log.append(dict(t=self.tick, line=line, level=level, ok=False, gain=0.0, text=text)); self.event(p.id, "tech", text); return
        x = p._size[line][level - 1]; p.tech[line] = level
        if "." in line:
            code, kind = line.split("."); stat = D.TECH_UNIT[kind]["stat"]
            st = dict(p.stats[code]); st["mark"] += 1; p.stats[code] = st; p.marks[code].append(st)   # a new model: units already in the field stay as they are
            st[stat] = round(st[stat] * (1.0 + x), 3); what = "%s %s +%d%%" % (code, stat, round(x * 100))
            if stat == "spd": self._pfree.clear(); self._pown.clear()
        elif line == "farming": p.mult["res"] *= 1 + x; what = "res yield +%d%%" % round(x * 100)
        elif line == "mining": p.mult["steel"] *= 1 + x; what = "steel yield +%d%%" % round(x * 100)
        elif line == "drilling": p.mult["oil"] *= 1 + x; what = "oil yield +%d%%" % round(x * 100)
        elif line == "refining": p.mult["rare"] *= 1 + x; what = "rare yield +%d%%" % round(x * 100)
        elif line == "conscription": p.mult["mp"] *= 1 + x; what = "manpower yield +%d%%" % round(x * 100)
        elif line == "logistics": p.mult["flow"] *= 1 + 2 * x; what = "supply inflow +%d%%" % round(200 * x)
        elif line == "medicine": p.mult["heal"] *= 1 + 3 * x; what = "strength recovery +%d%%" % round(300 * x)
        elif line == "staffwork": p.mult["plan"] *= 1 + 3 * x; what = "prepared-attack build-up +%d%%" % round(300 * x)
        elif line == "drill":
            for st in p.all_stats(): st["xp0"] += round(x * 100)
            what = "new units start with +%d experience" % round(x * 100)
        elif line == "fieldworks":
            for st in p.all_stats(): st["dig"] = round(st["dig"] * (1 + 3 * x), 3)
            what = "fort building +%d%%" % round(300 * x)
        elif line == "discipline": p.mor0 += round(x * 100); p.mult["rest"] *= 1 + 2 * x; what = "new units +%d morale, morale recovery +%d%%" % (round(x * 100), round(200 * x))
        elif line == "industry":
            for st in p.all_stats(): st["cost"] = max(1, int(round(st["cost"] * (1 - x))))
            what = "unit res cost -%d%%" % round(x * 100)
        else: what = "?"
        text = "%s level %d: BREAKTHROUGH, %s" % (line, level, what)
        p.tech_log.append(dict(t=self.tick, line=line, level=level, ok=True, gain=x, text=text)); self.event(p.id, "tech", text)

    # ---------------------------------------------------------------- diplomacy
    # Mechanics only. A pact stops the two sides' units firing at each other and taking each other's land; everything else
    # (whom to talk to, what to offer, when to break) is up to the factions.
    def met(self, pid):
        """Factions this player has come across (seen their land, or found their capital). You can only deal with those."""
        p = self.players[pid]; m = getattr(p, "met", None)
        if m is None: m = p.met = set()
        if getattr(p, "_met_t", -99) != self.tick:
            p._met_t = self.tick; m.update(o for o in p.known_owner.values() if o >= 0 and o != pid); m.update(p.known_caps)
        return set(i for i in m if self.players[i].alive)

    def _peace(self):
        self.peace = set(); self.allies = set()
        for (a, b), pc in self.pacts.items():
            self.peace.add((a, b)); self.peace.add((b, a))
            if pc.get("ally"): self.allies.add((a, b)); self.allies.add((b, a))
        for i in range(len(getattr(self, "vdirty", ()))): self.vdirty[i] = True

    def _dip(self, kind, a, b, **kw):
        self.dip_log.append(dict(t=self.tick, kind=kind, a=a, b=b, **kw))

    def _res_of(self, p, k): return p.res if k == "res" else p.mp if k == "mp" else p.bank[k]

    def _res_add(self, p, k, n):
        if k == "res": p.res += n
        elif k == "mp": p.mp += n
        else: p.bank[k] += n

    def _deal_check(self, pid, to):
        if not (0 <= to < len(self.players)) or to == pid or not self.players[to].alive: return "no such faction"
        self.players[pid]._met_t = -99
        if to not in self.met(pid): return "you have not come across %s yet" % self.players[to].faction
        return None

    def order_say(self, pid, to, text):
        e = self._deal_check(pid, to)
        if e: return e
        q = self.players[to]; text = " ".join(str(text).split())[:D.MAIL_LEN]
        if not hasattr(q, "mail"): q.mail = []
        if sum(1 for m in q.mail if m["frm"] == pid and self.tick - m["t"] < 24) >= D.MAIL_PER_DAY: return "at most %d messages a day to one faction" % D.MAIL_PER_DAY
        q.mail.append(dict(t=self.tick, frm=pid, text=text)); del q.mail[:-D.MAIL_KEEP]
        self.met(to); q.met.add(pid)                      # a letter reveals that its sender exists
        self.event(to, "mail", "%s says: %s" % (self.players[pid].faction, text)); self._dip("say", pid, to, text=text); return None

    def order_give(self, pid, to, k, n):
        e = self._deal_check(pid, to)
        if e: return e
        if k not in D.GIVE or n <= 0: return "give what? one of %s, a positive amount" % " ".join(D.GIVE)
        p = self.players[pid]
        if self._res_of(p, k) < n: return "need %d %s (have %d)" % (n, k, self._res_of(p, k))
        self._res_add(p, k, -n); self._res_add(self.players[to], k, n); self.met(to); self.players[to].met.add(pid)
        self.event(to, "gift", "%s sent you %d %s" % (p.faction, n, k)); self._dip("give", pid, to, res=k, n=n); return None

    def order_offer(self, pid, to, kind, hours=0, give=None, want=None):
        """kind 'pact': no fighting between the two for `hours` (0 = until one side breaks it).
        kind 'trade': a one-off swap, give {resource: amount} for want {resource: amount}. Returns (error, offer id)."""
        e = self._deal_check(pid, to)
        if e: return e, None
        if kind not in ("pact", "alliance", "trade", "supply", "access"): return "offer what? pact, alliance, trade, supply or access", None
        if kind == "access" and (pid, to) in self.access: return "your roads are already open to each other", None
        key = (min(pid, to), max(pid, to))
        if kind == "alliance" and self.pacts.get(key, {}).get("ally") and self.pacts[key]["ends"] is None: return "you are already allied", None
        if kind in ("trade", "supply"):
            give = dict(give or {}); want = dict(want or {}); bad = None
            for side, d in ((pid, give), (to, want)):
                for k in [k for k in d if k.startswith("P")]:
                    i = int(k[1:]); d[k] = 1
                    if kind == "supply": bad = "land cannot be part of a standing delivery"
                    elif not (0 <= i < self.n) or (side == pid and self.owner[i] != pid): bad = "%s is not yours to give" % k
                    elif side == pid and i in self.players[pid].depots: bad = "%s holds a depot of yours" % k
            if bad: return bad, None
            if not give and not want or any(k not in D.GIVE and not k.startswith("P") for k in list(give) + list(want)): return "name amounts of %s (or provinces P<id> in a trade) on at least one side" % " ".join(D.GIVE), None
            if kind == "supply" and sum(1 for d in self.deals.values() if {d["a"], d["b"]} == {pid, to}) >= D.DEAL_MAX: return "you already have %d standing deliveries with them" % D.DEAL_MAX, None
        if kind == "pact" and not self.pacts.get(key, {}).get("truce") and (min(pid, to), max(pid, to)) in self.pacts and self.pacts[(min(pid, to), max(pid, to))]["ends"] is None and (self.pacts[(min(pid, to), max(pid, to))]["until"] or 0) - self.tick > D.PACT_RENEW: return "your pact with them still runs for more than %d h" % D.PACT_RENEW, None
        if kind in ("trade", "supply"):
            give = {k: int(v) for k, v in give.items() if v > 0}; want = {k: int(v) for k, v in want.items() if v > 0}
        if sum(1 for o in self.offers.values() if o["frm"] == pid and o["to"] == to) >= D.OFFERS_OPEN: return "you already have %d offers open with them" % D.OFFERS_OPEN, None
        i = self.next_offer; self.next_offer += 1
        if kind in ("pact", "alliance", "supply"):           # how long a pact runs is the two factions' own business (0 = until one of them breaks it)
            hours = int(hours) if hours and hours > 0 else 0
            if D.PACT_MAX: hours = min(hours or D.PACT_MAX, D.PACT_MAX)
        self.offers[i] = dict(id=i, frm=pid, to=to, kind=kind, hours=max(0, int(hours)), give=give or {}, want=want or {}, t=self.tick)
        self.met(to); self.players[to].met.add(pid)
        self.event(to, "offer", "offer %d from %s: %s" % (i, self.players[pid].faction, self.offer_text(self.offers[i])))
        self._dip("offer", pid, to, what=self.offer_text(self.offers[i])); return None, i

    def offer_text(self, o):
        if o["kind"] in ("pact", "alliance"): return "%s, %s" % (o["kind"], "%d h" % o["hours"] if o["hours"] else "until broken")
        if o["kind"] == "access": return "access: each may use the other's roads for supply, and your markets join across the border, until one of you revokes it"
        f = lambda d: " ".join((k if k.startswith("P") else "%d %s" % (v, k)) for k, v in sorted(d.items())) or "nothing"
        if o["kind"] == "supply": return "supply every day, they give %s, you give %s, %s" % (f(o["give"]), f(o["want"]), "%d h" % o["hours"] if o["hours"] else "until cancelled")
        return "trade, they give %s, you give %s" % (f(o["give"]), f(o["want"]))

    def order_answer(self, pid, oid, yes):
        o = self.offers.get(oid)
        if o is None or o["to"] != pid: return "no such offer to you (it may have lapsed)"
        a, b = self.players[o["frm"]], self.players[pid]
        if not yes:
            del self.offers[oid]; self.event(a.id, "offer", "%s rejected your offer %d" % (b.faction, oid)); self._dip("reject", pid, a.id, what=self.offer_text(o)); return None
        key = (min(a.id, b.id), max(a.id, b.id))
        if o["kind"] == "trade":
            land = False
            for x, d in ((a, o["give"]), (b, o["want"])):
                for k, v in d.items():
                    if k.startswith("P"):
                        i = int(k[1:]); land = True
                        if self.owner[i] != x.id or i in x.depots:
                            if x is a: del self.offers[oid]
                            return "%s can no longer be handed over" % k
                    elif self._res_of(x, k) < v:
                        if x is a: del self.offers[oid]; return "%s can no longer pay (offer dropped)" % a.faction
                        return "need %d %s (have %d)" % (v, k, self._res_of(b, k))
            for x, y, d in ((a, b, o["give"]), (b, a, o["want"])):
                for k, v in d.items():
                    if k.startswith("P"):
                        i = int(k[1:]); self._set_owner(i, y.id); self.stock[i] *= 0.25
                        self.event(y.id, "took", "P%d handed over by %s" % (i, x.faction)); self.event(x.id, "lostprov", "P%d handed over to %s" % (i, y.faction))
                    else: self._res_add(x, k, -v); self._res_add(y, k, v)
            if land and key not in self.pacts:                # time to march out: a short truce comes with any land that changes hands by agreement
                self.pacts[key] = dict(since=self.tick, until=self.tick + D.TRUCE_HOURS, ends=None, by=None, truce=True); self._peace()
        elif o["kind"] == "access":
            self.access.add((a.id, b.id)); self.access.add((b.id, a.id)); self.sdirty[a.id] = True; self.sdirty[b.id] = True
        elif o["kind"] == "supply":
            self.deals[oid] = dict(id=oid, a=a.id, b=b.id, give=dict(o["give"]), want=dict(o["want"]), since=self.tick, until=self.tick + o["hours"] if o["hours"] else None)
        else:
            self.pacts[key] = dict(since=self.tick, until=self.tick + o["hours"] if o["hours"] else None, ends=None, by=None, ally=o["kind"] == "alliance"); self._peace()
            for q in (a, b):
                for u in self.punits[q.id].values():
                    if u.plan_t >= 0 and self.owner[u.plan_t] in key: u.plan_t = -1; u.plan_b = 0.0
        del self.offers[oid]
        self.event(a.id, "offer", "%s ACCEPTED your offer %d (%s)" % (b.faction, oid, o["kind"])); self._dip("accept", pid, a.id, what=self.offer_text(o), deal=o["kind"]); return None

    def order_break(self, pid, to):
        key = (min(pid, to), max(pid, to)); pc = self.pacts.get(key)
        if pc is None: return "you have no pact with them"
        if pc["ends"] is not None: return "that pact already ends at t%d" % pc["ends"]
        pc["ends"] = self.tick + D.PACT_NOTICE; pc["by"] = pid; a = self.players[pid]; b = self.players[to]
        self.event(to, "pact", "%s BROKE its pact with you: fighting may resume at t%d" % (a.faction, pc["ends"]))
        for q in self.players:                              # word gets around among everyone who knows the breaker
            if q.alive and q.id not in key and pid in self.met(q.id): self.event(q.id, "news", "%s broke a pact with %s" % (a.faction, b.faction))
        self._dip("break", pid, to); return None

    def order_cancel(self, pid, did):
        """Stop a standing delivery at once (either side can). Everyone who knows the one who cut it off hears of it."""
        d = self.deals.get(did)
        if d is None or pid not in (d["a"], d["b"]): return "no such standing delivery of yours"
        other = d["b"] if pid == d["a"] else d["a"]; del self.deals[did]; a = self.players[pid]; b = self.players[other]
        self.event(other, "deal", "%s CUT OFF delivery %d (%s)" % (a.faction, did, self.deal_text(d, other)))
        for q in self.players:
            if q.alive and q.id not in (pid, other) and pid in self.met(q.id): self.event(q.id, "news", "%s cut off its deliveries to %s" % (a.faction, b.faction))
        self._dip("cancel", pid, other, deal=did); return None

    def deal_text(self, d, pid):
        f = lambda x: " ".join("%d %s" % (v, k) for k, v in sorted(x.items())) or "nothing"
        mine, theirs = (d["give"], d["want"]) if pid == d["a"] else (d["want"], d["give"])
        return "every day you give %s and get %s%s" % (f(mine), f(theirs), ", until t%d" % d["until"] if d["until"] else "")

    def _deliver(self):
        """Once a day every standing delivery is carried out; one that a side cannot pay lapses, and both are told who failed."""
        for i, d in list(self.deals.items()):
            a, b = self.players[d["a"]], self.players[d["b"]]
            if not (a.alive and b.alive) or (d["until"] is not None and self.tick >= d["until"]):
                del self.deals[i]
                for q in (a, b):
                    if q.alive: self.event(q.id, "deal", "delivery %d has run out" % i)
                continue
            fail = a if any(self._res_of(a, k) < v for k, v in d["give"].items()) else b if any(self._res_of(b, k) < v for k, v in d["want"].items()) else None
            if fail is not None:
                del self.deals[i]
                for q in (a, b): self.event(q.id, "deal", "delivery %d ENDED: %s could not deliver" % (i, "you" if q is fail else fail.faction))
                self._dip("lapsed", fail.id, b.id if fail is a else a.id, deal=i); continue
            for k, v in d["give"].items(): self._res_add(a, k, -v); self._res_add(b, k, v)
            for k, v in d["want"].items(): self._res_add(b, k, -v); self._res_add(a, k, v)

    def _diplomacy(self):
        if self.deals and self.tick % 24 == 0: self._deliver()
        if not self.pacts and not self.offers: return
        t = self.tick; ch = False
        for k, pc in list(self.pacts.items()):
            end = pc["ends"] if pc["ends"] is not None else pc["until"]
            if pc["ends"] is not None and pc["until"] is not None: end = min(pc["ends"], pc["until"])
            if end is not None and t >= end:
                del self.pacts[k]; ch = True
                for i in k:
                    self.event(i, "pact", "your pact with %s is over" % self.players[k[0] if i == k[1] else k[1]].faction)
                    for u in self.punits[i].values(): self.active.add(u.id)
                self._dip("ended", k[0], k[1], by=pc["by"])
        if ch: self._peace()
        for i, o in list(self.offers.items()):
            if t - o["t"] >= D.OFFER_HOURS: del self.offers[i]

    def refit_cost(self, pid, code):
        """What it costs to re-equip one unit of that type to the current model (no manpower: the men stay)."""
        st = self.players[pid].stats[code]; f = D.REFIT_COST
        return dict(res=max(1, int(math.ceil(st["cost"] * f))), **{k: int(math.ceil(st[k] * f)) for k in ("steel", "oil", "rare")})

    def order_refit(self, pid, uid):
        """Bring one unit up to its type's current model. Paid per unit; the unit must be out of the fight on supplied own land."""
        p = self.players[pid]; u = self.units.get(uid)
        if u is None or u.owner != pid: return "no such unit"
        cur = p.stats[u.type]
        if u.st is cur: return "%s#%d is already the current model" % (u.type, u.id)
        if u.fighting or u.rout: return "%s#%d is in combat" % (u.type, u.id)
        if self.owner[u.prov] != pid or u.prov not in p.supplied: return "%s#%d must stand on your own supplied land" % (u.type, u.id)
        c = self.refit_cost(pid, u.type); b = p.bank
        if p.res < c["res"]: return "need %d res (have %d)" % (c["res"], p.res)
        for k in ("steel", "oil", "rare"):
            if b[k] < c[k]: return "need %d %s (have %d)" % (c[k], k, b[k])
        p.res -= c["res"]
        for k in ("steel", "oil", "rare"): b[k] -= c[k]
        p.upkeep += cur["upkeep"] - u.st["upkeep"]; u.st = cur; u.rdy = max(0.0, u.rdy - D.REFIT_RDY); self.active.add(u.id)
        return None

    def order_recruit(self, pid, code, prov=None):
        p = self.players[pid]
        if code not in D.UNITS: return "unknown unit '%s'" % code
        if prov is None: prov = p.capital
        pr = self.provs[prov] if 0 <= prov < self.n else None
        if pr is None or self.owner[prov] != pid or not pr.city: return "P%d is not your city" % prov
        if prov not in p.supplied: return "P%d is cut off from your depots" % prov
        st = p.stats[code]
        if p.res < st["cost"]: return "need %d res (have %d)" % (st["cost"], p.res)
        if p.mp < st["mp"]: return "need %d manpower (have %d)" % (st["mp"], p.mp)
        b = p.bank
        for k in ("steel", "oil", "rare"):
            if b[k] < st[k]: return "need %d %s (have %d)" % (st[k], k, b[k])
        for k in ("steel", "oil", "rare"): b[k] -= st[k]
        p.res -= st["cost"]; p.mp -= st["mp"]; p.queue.append([code, prov, st["time"]])
        return None

    # ---------------------------------------------------------------- tick
    def step(self):
        if self.over: return
        self.tick += 1
        if self.tick % 24 == 1: self._seasons()
        self._diplomacy(); self._economy(); self._combat(); self._hourly(); self._move(); self._capture()
        self._close_assaults(); self._supply(); self._vision(); self._check_end()

    # ---------------------------------------------------------------- economy: cities, roads, markets
    def room(self, prov):
        """Development a province can carry before it chokes on its own traffic."""
        return max(0.0, D.DEV_ROOM + D.DEV_ROOM_INFRA * self.infra[prov] + (0.0 if self.provs[prov].city else D.DEV_ROOM_RURAL))

    def dev_eff(self, prov):
        d = self.dev[prov]; r = self.room(prov)
        return d if d <= r else r + (d - r) * D.DEV_CHOKE

    def linked(self, a, b):
        oa = self.owner[a]; ob = self.owner[b]
        return oa >= 0 and (oa == ob or (oa, ob) in self.access)

    def market(self, prov):
        """Developed mass within reach: its own, plus its neighbours' and their neighbours', each step weakened by how poor the roads between them are.
        Only land of the same owner counts, or of an owner who has opened its roads to this one."""
        dev = self.dev; infra = self.infra; provs = self.provs; m = self.dev_eff(prov); L0 = D.LINK; L1 = D.LINK_INFRA
        if self.owner[prov] < 0: return m
        for b in provs[prov].nbrs:
            if not self.linked(prov, b): continue
            l = L0 + L1 * min(infra[prov], infra[b]); m += l * dev[b]
            for c in provs[b].nbrs:
                if c != prov and dev[c] > 0 and self.linked(b, c): m += l * (L0 + L1 * min(infra[b], infra[c])) * dev[c]
        return m

    def _wealth(self):
        """What every province yields now (once a day and when something was built)."""
        for i, pr in enumerate(self.provs):
            if pr.terrain == "water": continue
            d = self.dev_eff(i)
            if d <= 0 and self.infra[i] <= 0:
                near = any(self.dev[b] > 0 for b in pr.nbrs)
                if not near: self.agg[i] = 1.0; self.prod[i] = float(pr.y); self.prod_mp[i] = float(pr.mp); continue
            a = self.agg[i] = 1.0 + D.AGG * math.log(1.0 + self.market(i))
            self.prod[i] = (pr.y * (1.0 + D.DEV_Y * d) + D.DEV_FLAT * d) * a; self.prod_mp[i] = pr.mp * (1.0 + D.DEV_MP * d)

    def _econ_day(self):
        """Once a day: cities grow where the market is good and there is room, upkeep is charged, and what cannot be kept up decays."""
        dev = self.dev; infra = self.infra; fought = set(self.battles)
        for p in self.players:
            if not p.alive: p.maint = 0.0; continue
            m = 0.0; broke = p.res <= 0.0 and p.income < p.upkeep + p.maint
            for i in self.owned[p.id]:
                d = dev[i]; L = infra[i]
                if d <= 0 and L <= 0: continue
                if broke:
                    dev[i] = d = max(0.0, d - D.DEV_DECAY); infra[i] = L = max(0.0, L - D.DEV_DECAY)
                elif d > 0 and i in fought: dev[i] = d = max(0.0, d - D.DEV_BATTLE * 24)
                elif d > 0 and i in p.supplied and i not in fought:
                    r = self.room(i)
                    if d < r: dev[i] = d = min(D.DEV_MAX, d + D.DEV_GROW * (self.agg[i] - 1.0) * (1.0 - d / r))
                m += D.DEV_KEEP * d * d + D.INFRA_KEEP * L
            p.maint = m
        self._wealth()

    def _roads(self, prov):
        """Roads changed here: routes and supply distances have to be worked out again."""
        self._pfree.clear(); self._pown.clear(); o = self.owner[prov]
        if o >= 0:
            self.sdirty[o] = True
            for a, b in self.access:
                if a == o: self.sdirty[b] = True

    def dev_cost(self, prov):
        """(res, resource, amount) for the next level of development here."""
        k = int(self.dev[prov]) + 1; return D.DEV_COST * k, D.DEV_NEED[0], D.DEV_NEED[1] * k

    def infra_cost(self, prov):
        k = int(self.infra[prov]) + 1; return D.INFRA_COST * k, D.INFRA_NEED[0], D.INFRA_NEED[1] * k

    def order_develop(self, pid, prov, kind="dev"):
        """Invest in a province of yours: kind 'dev' raises its development by one level, 'infra' its roads and rail."""
        p = self.players[pid]
        if not (0 <= prov < self.n) or self.owner[prov] != pid: return "P%d is not yours" % prov
        if prov not in p.supplied: return "P%d is cut off from your depots" % prov
        if any(w[0] == kind and w[1] == prov for w in p.works): return "already building that at P%d" % prov
        cur = self.dev[prov] if kind == "dev" else self.infra[prov]; top = D.DEV_MAX if kind == "dev" else D.INFRA_MAX
        if cur + 1.0 > top + 1e-9: return "P%d is already at the top level" % prov
        res, k, n = self.dev_cost(prov) if kind == "dev" else self.infra_cost(prov)
        if p.res < res: return "need %d res (have %d)" % (res, p.res)
        if p.bank[k] < n: return "need %d %s (have %d)" % (n, k, p.bank[k])
        p.res -= res; p.bank[k] -= n; p.works.append([kind, prov, D.DEV_HOURS if kind == "dev" else D.INFRA_HOURS]); return None

    def order_revoke(self, pid, to):
        """Close your roads to a faction you had opened them to (and theirs to you). Everyone who knows you hears of it."""
        if (pid, to) not in self.access: return "you have no access agreement with them"
        self._access_end(pid, to); a = self.players[pid]; b = self.players[to]
        self.event(to, "deal", "%s CLOSED its roads to you" % a.faction)
        for q in self.players:
            if q.alive and q.id not in (pid, to) and pid in self.met(q.id): self.event(q.id, "news", "%s closed its roads to %s" % (a.faction, b.faction))
        self._dip("revoke", pid, to); return None

    def _access_end(self, a, b):
        self.access.discard((a, b)); self.access.discard((b, a)); self.sdirty[a] = True; self.sdirty[b] = True

    def _economy(self):
        provs = self.provs
        if self.tick % 24 == 0: self._econ_day()
        for p in self.players:
            if not p.alive: continue
            y = mp = 0; dep = dict.fromkeys(D.STRAT, 0); prod = self.prod; pmp = self.prod_mp
            for i in p.supplied:
                pr = provs[i]; y += prod[i]; mp += pmp[i]
                for k in D.STRAT: dep[k] += getattr(pr, k)
            m = p.mult; p.income = y * m["res"]; p.mp_income = mp * m["mp"]
            p.res = max(0.0, p.res + (p.income - p.upkeep - p.maint) / 24.0); p.mp += p.mp_income / 24.0
            for w in list(p.works):
                w[2] -= 1
                if w[2] <= 0:
                    p.works.remove(w); i = w[1]
                    if self.owner[i] != p.id: continue
                    if w[0] == "dev": self.dev[i] = min(D.DEV_MAX, self.dev[i] + 1.0)
                    else:
                        self.infra[i] = min(D.INFRA_MAX, self.infra[i] + 1.0); self._roads(i)
                    self.event(p.id, "built", "%s at P%d is now %.1f" % ("development" if w[0] == "dev" else "infrastructure", i, self.dev[i] if w[0] == "dev" else self.infra[i]))
            inc = p.inc; b = p.bank
            for k in D.STRAT: inc[k] = dep[k] * m.get(k, 1.0); b[k] += inc[k] / 24.0
            if self.tick % 24 == 0: p.fuel = sum(D.FUEL.get(u.type, 0.0) for u in self.punits[p.id].values())
            b["oil"] -= p.fuel / 24.0
            if b["oil"] <= 0.0:
                b["oil"] = 0.0
                if p.fuel > inc["oil"] and not p.nofuel: p.nofuel = True; self.event(p.id, "fuel", "OUT OF OIL: engines burn %.1f a day, you produce %.1f" % (p.fuel, inc["oil"]), key="fuel", gap=240)
            elif p.nofuel and b["oil"] > p.fuel: p.nofuel = False
            if p.depot_build or len(p.depots) > 1: self._depots(p)
            for r in list(p.research):
                r[2] -= 1
                if r[2] <= 0: p.research.remove(r); self._finish_research(p, r[0], r[1])
            for q in list(p.queue):
                q[2] -= 1
                if q[2] <= 0:
                    p.queue.remove(q)
                    at = q[1] if self.owner[q[1]] == p.id else p.capital
                    if self.owner[at] != p.id or self.enemy_at(at, p.id): continue
                    u = self.spawn(p.id, q[0], at); u.rdy = float(D.RDY_NEW); u.mor = min(100.0, u.mor + p.mor0)
                    self.event(p.id, "ready", "%s#%d at P%d" % (u.type, u.id, at))

    def _hourly(self):
        """Supplies flow in; every unit's supplies, readiness, morale, experience, strength and digging move on.
        Units that are doing something are served every hour; the calm rest one slice per hour, for SLICES hours at once."""
        stock = self.stock; provs = self.provs; hop = self.stock_hop; cold = self.cold; cf = D.COLD_FLOW
        for p in self.players:
            fl = D.STOCK_FLOW * p.mult["flow"]; th = self.throttle[p.id]; hb = self.hub[p.id]
            for i, h in self.hops[p.id].items():
                pr = provs[i]; cap = D.STOCK_CAP_CITY if pr.city else D.STOCK_CAP
                if stock[i] < cap: stock[i] = min(cap, stock[i] + fl / (1.0 + hop * h) * (0.5 if pr.biome else 1.0) * th.get(hb.get(i), 1.0) * (cf if i in cold else 1.0))
        units = self.units; act = self.active; one = self._unit_hour
        for i in sorted(act):
            u = units.get(i)
            if u is not None: one(u, 1)
        k = D.SLICES
        for i in sorted(self.slices[self.tick % k]):
            if i not in act: one(units[i], k)
        keep = set()
        for i in act:
            u = units.get(i)
            if u is not None and (u.path or u.fighting or u.plan_t >= 0 or not u.settled or u.rout or u.sup > 1.0): keep.add(i)
        self.active = keep

    def _unit_hour(self, u, k):
        stock = self.stock; p = self.players[u.owner]; pr = u.prov; fighting = u.fighting
        if fighting == 1: use = D.USE_ASSAULT; dr = D.RDY_ASSAULT
        elif fighting == 2: use = D.USE_DEFEND; dr = D.RDY_DEFEND
        elif u.path: use = D.USE_IDLE; dr = D.RDY_MOVE
        elif u.contact: use = D.USE_CONTACT; dr = D.RDY_CONTACT
        else: use = D.USE_IDLE; dr = D.RDY_REST
        use *= k; d = self.depot(u)
        if d >= 0 and stock[d] >= use: stock[d] -= use; u.dry = False
        else: u.dry = True; dr = min(dr, 0.0) - 0.3
        if p.nofuel and dr > 0 and u.type in D.FUEL: dr = 0.0
        u.rdy = max(0.0, min(100.0, u.rdy + dr * k))
        if u.plan_t >= 0:
            if fighting == 1: u.plan_b = max(0.0, u.plan_b - D.PLAN_DECAY)
            elif not u.path and not u.dry:
                if self.owner[u.plan_t] == u.owner: u.plan_t = -1; u.plan_b = 0.0
                else:
                    cap = D.PLAN_MAX_EXACT if self.intel(u.owner, u.plan_t) == 2 and any(
                        x.type == "rec" for b in self.provs[u.plan_t].nbrs for x in self.pos[b] if x.owner == u.owner) else D.PLAN_MAX
                    u.plan_b = min(float(cap), u.plan_b + D.PLAN_RATE * p.mult["plan"])
        if u.sup: u.sup = u.sup * D.SUP_DECAY if k == 1 and u.sup > 1.0 else 0.0
        home = self.owner[pr] == u.owner and pr in p.supplied
        near = home or any(b in p.supplied for b in self.provs[pr].nbrs)
        was = u.supplied; u.supplied = near
        if not home:                                         # campaigning away from home: winter and fever take their share
            loss = 0.0
            if pr in self.cold: loss += D.FROST * (D.HARDY if p.hardy else 1.0)
            if pr in self.jungle and not p.tropic: loss += D.FEVER / p.mult["heal"]
            if loss:
                u.str -= loss * k
                if u.str <= 0: self.event(u.owner, "lost", "%s#%d at P%d wasted away (%s)" % (u.type, u.id, pr, "frost" if pr in self.cold else "fever"), key="env", gap=24); self._die(u, None); return
        calm = not fighting and not u.contact
        if home and calm and u.str < 100:
            gain = min(100.0 - u.str, D.REINFORCE * k * p.mult["heal"]); need = gain * u.st["mp"] / 100.0      # replacements come out of the manpower pool
            if p.mp >= need:
                p.mp -= need
                u.xp = (u.xp * u.str + D.XP_REPL * gain) / (u.str + gain)                  # ... and arrive green: they dilute the unit's experience
                u.str += gain
        elif not near:
            u.str -= D.ATTRITION * k; u.mor -= D.MOR_CUT * k
            if was: self.event(u.owner, "nosupply", "%s#%d at P%d is out of supply" % (u.type, u.id, pr))
            if u.str <= 0 or u.mor <= 0:
                if u.str > 0: self.event(u.owner, "surrender", "%s#%d at P%d, cut off, laid down its arms" % (u.type, u.id, pr))
                self._die(u, None); return
        if near:
            if fighting: pass
            elif u.contact: u.mor = min(100.0, u.mor + D.MOR_CONTACT * k)
            elif not u.dry: u.mor = min(100.0, u.mor + D.MOR_REST * k * p.mult["rest"])
            if home and calm and not u.path and u.xp < D.XP_TRAIN_CAP: u.xp = min(float(D.XP_TRAIN_CAP), u.xp + D.XP_TRAIN * k)   # drill
        if u.dry: u.mor = max(0.0, u.mor - D.MOR_DRY * k)
        if u.dig and not u.path and fighting != 1 and self.owner[pr] == u.owner:
            lvl = self.fort_level(pr)
            if lvl >= D.FORT_MAX: u.dig = False
            else:
                self.fort[pr] = min(float(D.FORT_MAX), self.fort[pr] + k * u.st["dig"] * (u.str / 100.0) / (D.FORT_HOURS * (lvl + 1)))
                if self.fort_level(pr) > lvl:
                    self.event(u.owner, "fort", "P%d %s (level %d)" % (pr, D.FORT_NAMES[lvl + 1], lvl + 1))

    def _ground(self, code, src, dst):
        """Fire multiplier from the ground alone: target terrain for this unit type, height difference, sea crossing."""
        t = self.provs[dst]; s = self.provs[src]; st = D.UNITS[code]; m = 1.0
        if t.terrain in D.ROUGH: m *= st["rough"]
        if t.terrain in D.HIGH: m *= st["high"]
        if s.sea and dst in s.sea: m *= D.AMPHIB                       # firing across a strait: a landing
        e0, e1 = s.elev, t.elev
        return m * (D.DOWNHILL ** (e0 - e1) if e0 > e1 else D.UPHILL ** (e1 - e0))

    def _atk(self, u, src, dst, base=None):
        """Fire power of u (standing in province src) against a target in province dst."""
        t = self.provs[dst]; st = u.st
        m = (st["atk"] if base is None else base) * u.str / 100.0 * (1.0 if u.supplied else D.UNSUPPLIED_MULT)
        m *= (1.0 - D.RDY_ATK + D.RDY_ATK * u.rdy / 100.0) * (D.DRY_MULT if u.dry else 1.0)
        m *= (D.XP_ATK0 + D.XP_ATK * u.xp / 100.0) * (1.0 - D.MOR_ATK + D.MOR_ATK * u.mor / 100.0) * (1.0 - D.SUP_FIRE * u.sup / 100.0)
        if u.plan_t == dst: m *= 1.0 + u.plan_b / 100.0
        if u.type in D.FUEL and self.players[u.owner].nofuel: m *= D.FUEL_OUT
        if t.terrain in D.ROUGH: m *= st["rough"]
        if t.terrain in D.HIGH: m *= st["high"]
        s = self.provs[src]
        if s.sea and dst in s.sea: m *= D.AMPHIB                       # firing across a strait: a landing
        e0, e1 = s.elev, t.elev
        return m * (D.DOWNHILL ** (e0 - e1) if e0 > e1 else D.UPHILL ** (e1 - e0))

    def _fort_div(self, prov, pierce):
        """How much a fort divides incoming damage, after the attacker's pierce share."""
        return 1.0 + D.FORT_DFN * self.fort_level(prov) * (1.0 - pierce)

    def _combat(self):
        """Every unit fires at the enemies within its own range (up to TARGETS nearest, fire split between them).
        A unit with orders to move is advancing: it halts while it has a target, fires with its attack value and has
        no cover. A unit standing its ground fires with max(atk, HOLD_FIRE x dfn) and is covered by the terrain and,
        on its own soil, by the fort. Routed units do not fire. All damage of the hour lands at once.
        Experience, morale, suppression and formation experience all act here (see data.py)."""
        B = D.BUCKET; grid = self.grid; units = self.units; provs = self.provs; owner = self.owner; players = self.players
        for u in self._hot: u.fighting = 0; u.contact = False
        hot_units = self._hot = []
        mono = {k: (next(iter(c)) if len(c) == 1 else -2) for k, c in self.gown.items()}
        dmg = {}; kby = {}; fights = {}; con = set(); self.battles = {}; mates = {}; gfire = {}; act = self.active; tfc = self._tf; peace = self.peace; ass = self.assaults
        for (bx, by), me in mono.items():
            hot = me == -2
            if not hot:
                for dx in (-2, -1, 0, 1, 2):
                    for dy in (-2, -1, 0, 1, 2):
                        o = mono.get((bx + dx, by + dy))
                        if o is not None and o != me: hot = True; break
                    if hot: break
            if not hot: continue
            foes = {}                                                # (owner, reach in buckets) -> enemy units that could be in range
            for u in grid[(bx, by)]:
                u.contact = True; hot_units.append(u)
                if u.rout: continue
                st = u.st; r = st["range"]; r2 = r * r; R = 1 if r <= B else 2
                fl = foes.get((u.owner, R))
                if fl is None:
                    fl = foes[(u.owner, R)] = [t for dx in range(-R, R + 1) for dy in range(-R, R + 1)
                                              for t in grid.get((bx + dx, by + dy), ()) if t.owner != u.owner and (t.owner, u.owner) not in peace]
                if not fl: continue
                ux = u.x; uy = u.y; best = []
                if u.path or owner[u.prov] != u.owner:               # on the move, or standing on someone else's land: fights whatever is in reach
                    for t in fl:
                        d = (t.x - ux) ** 2 + (t.y - uy) ** 2
                        if d <= r2: best.append((d, t.id, t))
                else:                                                # holding its own line: a quiet front stays quiet. It fires at what advances
                    uo = u.owner; upv = u.prov                       # or intrudes, and joins a battle that is already on (either way round)
                    for t in fl:
                        if not t.path and owner[t.prov] == t.owner and (t.prov, uo) not in ass and (upv, t.owner) not in ass \
                                and u.plan_t != t.prov and t.plan_t != upv: continue      # (a prepared attack opens with its guns: units planning an attack on a province shell it, and are shelled back, when in range)
                        d = (t.x - ux) ** 2 + (t.y - uy) ** 2
                        if d <= r2: best.append((d, t.id, t))
                if not best: continue
                best.sort(); best = best[:D.TARGETS]
                adv = bool(u.path); u.fighting = 1 if adv else 2; u.hours += 1; act.add(u.id)
                base = None if adv else max(u.st["atk"], D.HOLD_FIRE * u.st["dfn"])
                form = 1.0
                if u.group:                                          # a formation fighting together: at least FORM_MIN of its units in this province
                    gk = (u.owner, u.group, u.prov); c = mates.get(gk)
                    if c is None: c = mates[gk] = sum(1 for o in self.pos[u.prov] if o.owner == u.owner and o.group == u.group)
                    if c >= D.FORM_MIN:
                        form = 1.0 + D.FORM_ATK * players[u.owner].fxp.get(u.group, 0.0) / 100.0
                        gfire[(u.owner, u.group)] = gfire.get((u.owner, u.group), 0) + 1
                u.xp = min(100.0, u.xp + (D.XP_ASSAULT if adv else D.XP_DEFEND) * (1.2 - u.xp / 100.0))      # learning by doing, slower at the top
                heavy = st["supp"]; ap1 = st["ap"] - 1.0; up = u.prov
                m0 = (st["atk"] if base is None else base) * u.str * 0.01 * (1.0 if u.supplied else D.UNSUPPLIED_MULT) \
                    * (1.0 - D.RDY_ATK + D.RDY_ATK * u.rdy * 0.01) * (D.DRY_MULT if u.dry else 1.0) \
                    * (D.XP_ATK0 + D.XP_ATK * u.xp * 0.01) * (1.0 - D.MOR_ATK + D.MOR_ATK * u.mor * 0.01) * (1.0 - D.SUP_FIRE * u.sup * 0.01) * form / len(best)
                for d, tid, t in best:
                    tp = t.prov; tf = tfc.get((u.type, up, tp))
                    if tf is None: tf = tfc[(u.type, up, tp)] = self._ground(u.type, up, tp)
                    pw = m0 * tf
                    if u.plan_t == tp: pw *= 1.0 + u.plan_b * 0.01
                    h = t.st["hard"]
                    if h: pw *= 1.0 + h * ap1                          # armour shrugs off soft weapons; anti-tank weapons tear it open
                    if not t.path:                                   # standing: cover from terrain, and from the fort at home
                        cov = provs[tp].dfn
                        if owner[tp] == t.owner: cov *= self._fort_div(tp, u.st["pierce"])
                        if cov > 1.0:
                            e = ass.get((tp, u.owner))               # positions face one way: attacked from several sides, cover counts for less
                            if e is not None and e["dirs"] > 1: cov = 1.0 + (cov - 1.0) * (D.FLANK_COVER[1] if e["dirs"] > 2 else D.FLANK_COVER[0])
                        pw /= cov
                    if t.fighting == 0:
                        t.fighting = 2 if not t.path else 1
                        if not t.contact: t.contact = True; hot_units.append(t); act.add(t.id)
                    hit = pw * D.DMG_K * 14.0 / max(4.0, t.st["dfn"]) / (D.XP_DFN0 + D.XP_DFN * t.xp / 100.0)     # veterans use the ground better
                    dmg[tid] = dmg.get(tid, 0.0) + hit; kby[tid] = u
                    t.sup = min(100.0, t.sup + hit * D.SUP_K * heavy)
                    if u.prov != t.prov: con.add((min(u.prov, t.prov), max(u.prov, t.prov)))
                    q = t.prov
                    if adv and owner[q] == t.owner:                  # an assault on province q
                        f = fights.get((q, u.owner))
                        if f is None: f = fights[(q, u.owner)] = ({}, {}, [0.0])
                        f[0][u.id] = u; f[1][tid] = t; f[2][0] += pw
        self.contacts = [list(c) for c in sorted(con)]
        for (pid, name), n in gfire.items():                         # a formation learns when it fights as one
            fx = players[pid].fxp; fx[name] = min(100.0, fx.get(name, 0.0) + D.FORM_GAIN * min(1.0, n / 10.0))
        for tid in sorted(dmg):
            t = units.get(tid)
            if t is not None:
                x = dmg[tid] * self.rng.uniform(0.8, 1.2); t.str -= x
                steady = (1.0 - D.MOR_VET * t.xp / 100.0) * (1.0 - D.FORM_MOR * players[t.owner].fxp.get(t.group, 0.0) / 100.0 if t.group else 1.0)
                t.mor = max(0.0, t.mor - x * D.MOR_DMG * steady)
        for (prov, side), (att, dfd, pw) in sorted(fights.items()):
            att = list(att.values()); dfd = list(dfd.values()); t = provs[prov]; lvl = self.fort_level(prov)
            dirs = set((u.prov if u.prov != prov else u.last) for u in att)
            self.battles[prov] = dict(att=[u.id for u in att], frm=sorted(d for d in dirs if d != prov), side=side)
            ep = self.assaults.get((prov, side))
            if ep is not None:
                if len(dirs) > ep["dirs"]: ep["dirs"] = len(dirs)
                if not ep["entered"] and any(u.prov == prov for u in att): ep["entered"] = 1
            if ep is None:
                ac = {}
                for u in att: ac[u.type] = ac.get(u.type, 0) + 1
                dc = {}
                for o in dfd: dc[o.type] = dc.get(o.type, 0) + 1
                ep = self.assaults[(prov, side)] = dict(
                    t=self.tick, side=side, prov=prov, terrain=t.terrain, city=int(t.city), fort=lvl, dirs=len(dirs),
                    att_n=len(att), att_str=round(sum(max(0.0, u.str) for u in att)), att_rdy=round(sum(u.rdy for u in att) / len(att)),
                    att_bonus=round(sum(u.plan_b for u in att if u.plan_t == prov) / len(att)), att_types=ac,
                    att_stock=round(min(self.stock[d] if d >= 0 else 0 for d in (self.depot(u) for u in att))),
                    def_n=len(dfd), def_str=round(sum(max(0.0, o.str) for o in dfd)), def_rdy=round(sum(o.rdy for o in dfd) / len(dfd)),
                    def_types=dc, def_supplied=int(all(o.supplied for o in dfd)), power=round(pw[0], 1), resist=0.0,
                    sea=int(any(d in t.sea for d in dirs)), a0=0.0, d0=0.0, ids={}, dids={},
                    aimed=sum(1 for u in att if prov in u.path), entered=int(any(u.prov == prov for u in att)))      # attackers actually ordered into the province (0 = fire in passing)
            ep["last"] = self.tick
            for u in att:                                            # units join an assault as they come into range
                if u.id not in ep["ids"]: ep["ids"][u.id] = (max(0.0, u.str), u.type, u.rdy, u.plan_b if u.plan_t == prov else 0.0, u.xp, u.mor)
            for o in dfd:
                if o.id not in ep["dids"]: ep["dids"][o.id] = (max(0.0, o.str), o.type, o.rdy, 0.0, o.xp, o.mor)
            ep["dirs"] = max(ep["dirs"], len(dirs))
            self.event(dfd[0].owner, "battle", "P%d attacked from %s" % (prov, ",".join("P%d" % d for d in sorted(dirs))), key=("b", prov), gap=72)
            self.event(side, "battle", "attacking P%d" % prov, key=("a", prov), gap=72)
        for tid in sorted(dmg):
            t = units.get(tid)
            if t is None: continue
            if t.str <= 0:
                k = kby[tid]
                if k.id in units: k.xp = min(100.0, k.xp + D.XP_KILL); k.mor = min(100.0, k.mor + D.MOR_KILL)
                self._die(t, k.owner, shock=True)
            elif (t.str < D.RETREAT_AT or t.mor < D.MOR_BREAK) and not t.rout: self._retreat(t)

    def _close_assaults(self):
        """An assault episode ends when the province changes hands (success), or nobody has attacked for 6 h and no
        attacker is still marching on it (failure)."""
        for key in list(self.assaults):
            ep = self.assaults[key]; prov, side = key
            won = self.owner[prov] == side
            if not won and (self.tick - ep["last"] < 6 or any(
                    i in self.units and self.units[i].path and self.units[i].path[0] == prov for i in ep["ids"])): continue   # still advancing
            del self.assaults[key]
            us = [self.units[i] for i in ep["ids"] if i in self.units]            # what became of the attackers
            ep["fate"] = dict(destroyed=len(ep["ids"]) - len(us), routed=sum(1 for u in us if u.rout), sent_elsewhere=sum(1 for u in us if u.path and not u.rout),
                              halted=sum(1 for u in us if not u.path and u.prov != prov), inside=sum(1 for u in us if not u.path and u.prov == prov))
            a1 = sum(max(0.0, self.units[i].str) for i in ep["ids"] if i in self.units)
            d1 = sum(max(0.0, self.units[i].str) for i in ep["dids"] if i in self.units)
            A = list(ep["ids"].values()); Dd = list(ep["dids"].values()); ac = {}; dc = {}
            for x in A: ac[x[1]] = ac.get(x[1], 0) + 1
            for x in Dd: dc[x[1]] = dc.get(x[1], 0) + 1
            a0 = sum(x[0] for x in A); d0 = sum(x[0] for x in Dd)
            ep.update(won=int(won), hours=ep["last"] - ep["t"] + 1, att_loss=round(max(0.0, a0 - a1)), def_loss=round(max(0.0, d0 - d1)),
                      att_n=len(A), att_str=round(a0), att_rdy=round(sum(x[2] for x in A) / len(A)), att_bonus=round(sum(x[3] for x in A) / len(A)),
                      att_xp=round(sum(x[4] for x in A) / len(A)), att_mor=round(sum(x[5] for x in A) / len(A)),
                      def_xp=round(sum(x[4] for x in Dd) / len(Dd)), def_mor=round(sum(x[5] for x in Dd) / len(Dd)),
                      att_types=ac, def_n=len(Dd), def_str=round(d0), def_rdy=round(sum(x[2] for x in Dd) / len(Dd)), def_types=dc)
            for k in ("ids", "dids", "a0", "d0", "last"): ep.pop(k)
            self.battle_log.append(ep)

    def _retreat(self, u):
        """A broken unit (too weak, or its morale gone) falls back to a friendly province (its own, if it was
        attacking). It does not fight on the way. With nowhere to go it stands; cut off and out of heart it surrenders."""
        if self.owner[u.prov] == u.owner and not self.enemy_at(u.prov, u.owner) and not u.fighting: opts = [u.prov]     # not under fire: pull back to the key point
        else: opts = [b for b in self.provs[u.prov].nbrs if self.owner[b] == u.owner and not self.enemy_at(b, u.owner)]
        if not opts:
            if u.path: u.path = []                 # nowhere to go: stands and fights on
            if u.mor < D.MOR_SURRENDER and not u.supplied:
                self.event(u.owner, "surrender", "%s#%d at P%d, surrounded, laid down its arms" % (u.type, u.id, u.prov)); self._die(u, None)
            return
        sup = self.players[u.owner].supplied
        b = min(opts, key=lambda i: (i not in sup, any(self.enemy_at(c, u.owner) for c in self.provs[i].nbrs), i))
        u.path = [b]; u.dig = False; u.rout = True; u.plan_t = -1; u.plan_b = 0.0; u.settled = False; self.active.add(u.id)
        self.event(u.owner, "retreat", "%s#%d falls back to P%d" % (u.type, u.id, b))

    def _die(self, u, killer, shock=False):
        if u.id in self.units:
            del self.units[u.id]; self.pos[u.prov].remove(u); del self.punits[u.owner][u.id]
            self.slices[u.id % D.SLICES].discard(u.id); self.active.discard(u.id); self._look(u, -1)
            self.grid[u.bk].remove(u); c = self.gown[u.bk]
            if c[u.owner] <= 1:
                del c[u.owner]
                if not c: del self.grid[u.bk]; del self.gown[u.bk]
            else: c[u.owner] -= 1
            p = self.players[u.owner]; p.losses += 1; p.upkeep -= u.st["upkeep"]; p.n_units -= 1
            self.event(u.owner, "lost", "%s#%d at P%d" % (u.type, u.id, u.prov))
            if shock:                                      # the units beside it see it destroyed
                for o in self.pos[u.prov]:
                    if o.owner == u.owner: o.mor = max(0.0, o.mor - D.MOR_SHOCK * (1.0 - D.MOR_VET * o.xp / 100.0))
            if killer is not None:
                self.players[killer].kills += 1; self.event(killer, "kill", "%s at P%d" % (u.type, u.prov))

    def _move(self):
        """Units walk in straight lines from key point to key point (their place in the formation around it).
        An advancing unit that has a target stays where it is and fights; a routed unit keeps going. A sea link is
        crossed the same way: the unit counts as in the province it left until it lands."""
        provs = self.provs; cell = self.map.cell; gw = self.map.gw; gh = self.map.gh; units = self.units
        for i in sorted(self.active):
            u = units.get(i)
            if u is None or (u.settled and not u.path): continue
            if u.path:
                if u.fighting == 1 and not u.rout: continue
                nxt = u.path[0]
                if nxt != u.prov and nxt not in provs[u.prov].nbrs: u.path = []; continue
                goal = provs[nxt]
            else:
                goal = provs[u.prov]; nxt = u.prov
            tx = goal.cx + u.ox; ty = goal.cy + u.oy; dx = tx - u.x; dy = ty - u.y; d = (dx * dx + dy * dy) ** 0.5
            if d < 0.02:
                if u.path:
                    u.path.pop(0)
                    if not u.path: self._arrived(u)
                else: u.settled = True
                continue
            here = u.prov
            if u.path and nxt != here:
                cx = int(u.x); cy = int(u.y)
                if 0 <= cx < gw and 0 <= cy < gh and cell[cy * gw + cx] == nxt:       # crossed the border
                    self._enter(u, nxt); here = nxt
            step = D.SPAN / self.move_cost(u, here)
            if step >= d:
                u.x = tx; u.y = ty
                if u.prov != nxt: self._enter(u, nxt)
                if u.path:
                    u.path.pop(0)
                    if not u.path: self._arrived(u)
                else: u.settled = True
            else:
                u.x += dx / d * step; u.y += dy / d * step
            self._rebucket(u)

    def _arrived(self, u):
        u.settled = True
        if u.rout: u.rout = False; u.mor = max(u.mor, float(D.MOR_RALLY))      # rallies behind the line

    def _capture(self):
        """A province changes hands when a side has a unit at its key point (within CAP_R) and no unit of any
        other side that is still fighting stands in the province."""
        cand = set(); units = self.units; owner = self.owner
        for i in self.active:
            u = units.get(i)
            if u is not None and owner[u.prov] != u.owner: cand.add(u.prov)
        for q in sorted(cand):
            sides = set(u.owner for u in self.pos[q] if not u.rout and u.type != "rec" and (u.owner, owner[q]) not in self.peace)      # scouts neither take nor hold land; nor do pact partners passing through
            if len(sides) != 1: continue
            side = next(iter(sides)); pr = self.provs[q]; r2 = D.CAP_R ** 2
            if side == self.owner[q]: continue
            if not any(u.owner == side and u.type != "rec" and (u.x - pr.cx) ** 2 + (u.y - pr.cy) ** 2 <= r2 for u in self.pos[q]): continue
            old = self.owner[q]; self._set_owner(q, side)
            self.fort[q] = float(self.fort_level(q) // 2)        # captured works are half wrecked
            self.stock[q] *= 0.25                                # most of the depot is burnt or carried off
            if self.dev[q] > 0 or self.infra[q] > 0:             # a city taken by force is a damaged city
                self.dev[q] *= D.DEV_SACK; self.infra[q] *= D.INFRA_SACK; self._roads(q)
            if old >= 0 and (side, old) in self.access: self._access_end(side, old)
            self.event(side, "took", "P%d" % q)
            if old >= 0:
                self.event(old, "lostprov", "P%d" % q)
                for b in pr.nbrs:                                # the neighbours' flank is suddenly open
                    if self.owner[b] == old:
                        for u in self.pos[b]:
                            if u.owner == old: u.mor = max(0.0, u.mor - D.MOR_FLANK * (1.0 - D.MOR_VET * u.xp / 100.0)); self.active.add(u.id)
                for u in self.pos[q]:
                    if u.owner == side: u.mor = min(100.0, u.mor + D.MOR_WIN)

    def _supply(self):
        """A province is supplied when it connects to the capital through your own provinces."""
        if self._odirty:                                      # the owner list was edited from outside: rebuild the indexes
            self._odirty = False; self._pown.clear()
            for s in self.owned: s.clear()
            for i, o in enumerate(self.owner):
                if o >= 0: self.owned[o].add(i)
            n = len(self.players); self.sdirty = [True] * n; self.vdirty = [True] * n; self.ownvis = [None] * n
        for p in self.players:
            if not self.sdirty[p.id]: continue
            self.sdirty[p.id] = False
            s = set()
            hp = {}; hub = {}; q = []; dist = {}; infra = self.infra; owner = self.owner; acc = set(b for a, b in self.access if a == p.id); IH = D.INFRA_HOP
            for d in sorted(p.depots):                           # supply spreads from every working depot at once: each province draws on the nearest
                if owner[d] == p.id and d not in p.depot_build: dist[d] = 0.0; hub[d] = d; heapq.heappush(q, (0.0, d, d))
            link = {}; done = set()
            while q:                                             # good roads shorten the way; a partner who opened its roads lets supply pass over them
                da, a, h = heapq.heappop(q)
                if a in done: continue
                done.add(a); hub[a] = h
                if owner[a] == p.id: s.add(a); hp[a] = da
                for b in self.provs[a].nbrs:
                    ob = owner[b]
                    if ob != p.id and not (ob in acc and infra[b] >= 1.0): continue
                    if b in done:
                        if hub[b] != h and ob == p.id and owner[a] == p.id: link.setdefault(h, set()).add(hub[b])
                        continue
                    sea = b in self.provs[a].sea
                    if sea and (b in self.cold or a in self.cold): continue          # no shipping into the ice
                    nd = da + (D.SEA_HOPS if sea else 1.0) / (1.0 + IH * infra[b])
                    if nd < dist.get(b, 1e18): dist[b] = nd; heapq.heappush(q, (nd, b, h))
            hub = {b: hub[b] for b in hp}
            self.hops[p.id] = hp; self.hub[p.id] = hub; ld = {}
            for b, h in hp.items(): ld[hub[b]] = ld.get(hub[b], 0.0) + (0.5 if self.provs[b].biome else 1.0) / (1.0 + self.stock_hop * h)
            self.load[p.id] = ld                                 # a depot can only push so much: beyond its capacity everything it serves gets proportionally less
            self.throttle[p.id] = {d: min(1.0, (D.HUB_LOAD_CITY if self.provs[d].city else D.HUB_LOAD) * (1.0 + D.INFRA_HUB * self.infra[d]) / max(1e-9, v)) for d, v in ld.items()}
            p._links = link
            cut = [i for i in p.supplied if i not in s and self.owner[i] == p.id]
            if cut: self.event(p.id, "cut", "supply cut to %d province(s) incl. %s" % (len(cut), ",".join("P%d" % i for i in sorted(cut)[:4])))
            p.supplied = s

    def sight_from(self, prov, rng):
        """Provinces seen from `prov` at graph range `rng`. Sight does not pass through ground higher than the viewer."""
        key = (prov, rng); r = self._sight.get(key)
        if r is not None: return r
        e0 = self.provs[prov].elev; seen = {prov: 0}; q = [prov]; i = 0
        while i < len(q):
            a = q[i]; i += 1
            if seen[a] >= rng: continue
            if a != prov and self.provs[a].elev > e0: continue      # visible, but blocks what lies behind
            for b in self.provs[a].nbrs:
                if b not in seen: seen[b] = seen[a] + 1; q.append(b)
        r = self._sight[key] = frozenset(seen)
        return r

    def _vision(self):
        """Recomputed only for players whose land or lookout posts changed this hour."""
        provs = self.provs; refresh = self.tick % 24 == 0
        for p in self.players:
            if not (self.vdirty[p.id] or refresh): continue
            self.vdirty[p.id] = False
            ov = self.ownvis[p.id]
            if ov is None:
                ov = self.ownvis[p.id] = set()
                for i in self.owned[p.id]: ov.add(i); ov.update(provs[i].nbrs)
            vis = set(ov)
            for k in self.occ[p.id]: vis.update(self.sight_from(*k))
            for a, b in self.allies:                          # allies show each other what they see
                if a == p.id: vis |= self.players[b].visible
            p.visible = vis; p.explored |= vis
            ko = p.known_owner; kf = p.known_fort; owner = self.owner
            kd = p.known_dev; dev = self.dev; infra = self.infra
            for i in vis:
                ko[i] = owner[i]; kf[i] = self.fort_level(i)
                if dev[i] > 0 or infra[i] > 0 or i in kd: kd[i] = (dev[i], infra[i])
            for e in self.players:
                if e.id != p.id and e.alive:
                    for d in e.depots:
                        if d in vis and d not in p.known_depots and d not in e.depot_build: p.known_depots[d] = e.id
                if e.id != p.id and e.alive and e.id not in p.known_caps and e.capital in vis and self.owner[e.capital] == e.id:
                    p.known_caps[e.id] = e.capital; self.event(p.id, "intel", "capital of P%d found at P%d" % (e.id, e.capital))

    def intel(self, pid, prov):
        """2 = exact (your unit is adjacent/in contact or a rec sees it), 1 = rough estimate, 0 = not visible."""
        p = self.players[pid]
        if prov not in p.visible: return 0
        pos = self.pos
        for b in self.provs[prov].nbrs:
            if any(x.owner == pid for x in pos[b]): return 2
            for c in self.provs[b].nbrs:                  # a rec two provinces away with line of sight
                for u in pos[c]:
                    if u.owner == pid and u.type == "rec" and prov in self.sight_from(c, u.st["sight"] + self.provs[c].elev): return 2
        return 1

    def estimate(self, pid, prov):
        """What `pid` believes about enemy units in `prov`: (level, {type: n} or None, strength, count)."""
        lvl = self.intel(pid, prov)
        if not lvl: return None
        es = [u for u in self.pos[prov] if u.owner != pid]
        if not es: return (lvl, {}, 0, 0)
        tot = sum(u.str for u in es)
        if lvl == 2:
            c = {}
            for u in es: c[u.type] = c.get(u.type, 0) + 1
            return (2, c, int(tot), len(es))
        r = random.Random((self.seed * 1000003 + pid * 7919 + prov * 131 + self.tick // 48) & 0xffffffff)
        est = max(50, int(round(tot * r.uniform(0.7, 1.3) / 50.0)) * 50)
        return (1, None, est, max(1, int(round(len(es) * r.uniform(0.7, 1.3)))))

    def _check_end(self):
        """A faction that has lost its last depot is out: its remaining land goes to the captor and its units disband.
        The last faction standing wins; at the time limit the highest score wins."""
        for p in self.players:
            if not p.alive: continue
            for d in [d for d in p.depots if self.owner[d] != p.id]: self._lose_depot(p, d, self.owner[d])
            if not p.depots:
                p.alive = False; taker = getattr(p, "_fell_to", -1)
                for u in list(self.punits[p.id].values()): self._die(u, taker if taker >= 0 else None)
                for i in list(self.owned[p.id]): self._set_owner(i, taker); self.fort[i] = 0.0
                p.queue = []
                if taker >= 0: self.players[taker].mp += p.mp * D.LOOT_MP
                p.mp = 0.0; p.depot_build = {}; p.depot_want = {}
                for k in [k for k in self.pacts if p.id in k]: del self.pacts[k]
                for k in [k for k, o in self.offers.items() if p.id in (o["frm"], o["to"])]: del self.offers[k]
                self._peace()
                for u in self.units.values():                # everyone standing on that land looks again at whose it is
                    if self.owner[u.prov] != u.owner: self.active.add(u.id)
                for q in self.players:
                    q.known_caps.pop(p.id, None)
                    for d in [d for d, o in q.known_depots.items() if o == p.id]: del q.known_depots[d]
                    if q.alive: self.event(q.id, "fall", "P%d (%s) capitulated to P%d" % (p.id, p.faction, taker))
        live = [p.id for p in self.players if p.alive]
        if len(live) <= 1:
            self.over = True; self.winner = live[0] if live else None; return
        if self.tick >= self.max_ticks:
            self.over = True; sc = sorted(((self.score(i), i) for i in live), reverse=True)
            self.winner = None if sc[0][0] == sc[1][0] else sc[0][1]

    def _lose_depot(self, p, d, taker):
        """A depot has fallen: what was stored there goes to whoever took it. The rest of the treasury stays where it was."""
        f = p.depots.pop(d); p.depot_want.pop(d, None); p.depot_build.pop(d, None); p._fell_to = taker
        take = dict(res=p.res * f, **{k: p.bank[k] * f for k in D.STRAT})
        p.res -= take["res"]
        for k in D.STRAT: p.bank[k] -= take[k]
        if taker is not None and taker >= 0:
            w = self.players[taker]; w.res += take["res"]
            for k in D.STRAT: w.bank[k] += take[k]
            self.event(taker, "loot", "depot of %s at P%d taken: %d res, %d steel, %d oil, %d rare" % (p.faction, d, take["res"], take["steel"], take["oil"], take["rare"]))
        self.event(p.id, "depot", "depot P%d LOST with %d%% of your treasury (%d res)" % (d, round(f * 100), take["res"]))
        tot = sum(p.depots.values())
        if tot > 0:
            for k in p.depots: p.depots[k] /= tot
        elif p.depots:                                       # only empty or unfinished depots are left: what remains of the treasury is with them
            for k in p.depots: p.depots[k] = 1.0 / len(p.depots)
        for q in self.players: q.known_depots.pop(d, None)
        if p._cap == d:                                      # the seat moves to the largest depot that is left
            p._cap = max(p.depots, key=lambda k: (p.depots[k], -k)) if p.depots else d
            for q in self.players: q.known_caps.pop(p.id, None)
        self.sdirty[p.id] = True

    def depot_cost(self, pid): return int(D.DEPOT_COST)

    def order_depot(self, pid, prov, weight=1.0):
        """Open a depot in a province of yours, or change how much of the treasury you want kept there (weight 0 = close it).
        Supply flows from every working depot; the treasury moves between depots only as fast as it can be carried."""
        p = self.players[pid]
        if not (0 <= prov < self.n) or self.owner[prov] != pid: return "P%d is not yours" % prov
        weight = max(0.0, float(weight))
        if prov not in p.depots:
            if weight <= 0: return "P%d is not a depot" % prov
            if prov not in p.supplied: return "P%d is cut off from your depots" % prov
            if p.res < D.DEPOT_COST: return "need %d res (have %d)" % (D.DEPOT_COST, p.res)
            p.res -= D.DEPOT_COST; p.depots[prov] = 0.0; p.depot_build[prov] = D.DEPOT_HOURS; p.depot_want[prov] = weight; return None
        if weight <= 0 and sum(1 for k, v in p.depot_want.items() if v > 0 and k != prov) == 0: return "you need at least one depot"
        p.depot_want[prov] = weight; return None

    def _depots(self, p):
        """New depots open; the treasury is carried towards the shares the faction asked for, DEPOT_SHIFT of the whole per hour,
        and only between depots joined by its own land."""
        if p.depot_build:
            for d in list(p.depot_build):
                p.depot_build[d] -= 1
                if p.depot_build[d] <= 0: del p.depot_build[d]; self.sdirty[p.id] = True; self.event(p.id, "depot", "depot P%d is open" % d)
        if len(p.depots) < 2: return
        act = [d for d in p.depots if d not in p.depot_build]; tot = sum(p.depot_want.get(d, 0.0) for d in act)
        if tot <= 0 or len(act) < 2: return
        gap = {d: p.depot_want.get(d, 0.0) / tot - p.depots[d] for d in act}
        give = sorted((d for d in act if gap[d] < -1e-6), key=lambda d: gap[d]); get = sorted((d for d in act if gap[d] > 1e-6), key=lambda d: -gap[d])
        left = D.DEPOT_SHIFT; hub = self.hub[p.id]; links = getattr(p, "_links", {})
        def joined(a, b):                                    # depots whose supply areas touch (directly or through others) are joined by own land
            seen = {a}; q = [a]
            while q:
                x = q.pop()
                if x == b: return True
                for y in links.get(x, ()):
                    if y not in seen: seen.add(y); q.append(y)
                for x2, ys in links.items():
                    if x in ys and x2 not in seen: seen.add(x2); q.append(x2)
            return False
        for a in give:
            for b in get:
                if left <= 0: break
                m = min(-gap[a], gap[b], left)
                if m <= 0 or not joined(a, b): continue
                p.depots[a] -= m; p.depots[b] += m; gap[a] += m; gap[b] -= m; left -= m
        for d in [d for d in act if p.depot_want.get(d, 0.0) <= 0 and p.depots[d] < 1e-4 and len(p.depots) > 1]:      # an emptied depot that is no longer wanted closes
            p.depots.pop(d); p.depot_want.pop(d, None); self.sdirty[p.id] = True
            if p._cap == d: p._cap = max(p.depots, key=lambda k: (p.depots[k], -k))

    def score(self, pid):
        return sum(self.provs[i].y for i in self.owned[pid]) * 10 + sum(int(u.str) for u in self.punits[pid].values()) // 10


def small_game(seed=0, factions=("aurum", "sable"), **kw):
    """The old duel: two factions on a 300-province map. Fast; used by tests, experiments and the review loop."""
    return Game(factions=factions, seed=seed, gmap=gen_map(seed, 126, 78, 22, 14, players=len(factions)), **kw)
