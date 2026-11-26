"""Ridgeline game engine. Deterministic, tick based (10 ticks/s).

Core mechanics
- Three elevation levels. Ground units cross levels only through ramps.
- Vision: a viewer sees a tile only if the tile is not higher than the viewer's eye level
  and no higher tile or brush lies in between. High ground sees down; low ground cannot see up.
- Fog of war per player: `vis` (now) and `explored` (ever). Terrain itself is known.
- A unit that fires is revealed to everyone for REVEAL_TICKS.
- Economy: workers mine ore patches and return to an HQ. Structures train units.
"""
import heapq
import math
from collections import OrderedDict

from . import data as D
from .mapgen import default_map

INF = float("inf")
SQ2 = 1.41421356


class Ent:
    __slots__ = ("id", "owner", "type", "x", "y", "hp", "st", "order", "tgt", "cd", "carry", "timer",
                 "gs", "queue", "rally", "prog", "reveal", "group", "repeat", "fly", "struct", "tx", "ty",
                 "size", "amt", "goal", "last_seen", "moving", "born")

    def __init__(self, id, owner, type, x, y, st):
        self.id = id; self.owner = owner; self.type = type; self.x = x; self.y = y; self.st = st
        self.hp = st["hp"] if st else 0
        self.order = ("idle",); self.tgt = 0; self.cd = 0; self.carry = 0; self.timer = 0; self.gs = ""
        self.queue = []; self.rally = None; self.prog = 1.0; self.reveal = -1; self.group = ""
        self.repeat = None; self.fly = bool(st and st.get("fly")); self.struct = bool(st and st.get("struct"))
        self.tx = self.ty = 0; self.size = 0; self.amt = 0; self.goal = None; self.last_seen = None
        self.moving = False; self.born = 0


class Player:
    def __init__(self, pid, faction, n):
        self.id = pid; self.faction = faction; self.stats = D.stats_for(faction)
        self.ore = D.START_ORE; self.vis = bytearray(n); self.explored = bytearray(n)
        self.vis_ents = set(); self.mem = {}       # enemy structure memory: id -> dict
        self.events = []; self.throttle = {}
        self.groups = {}                            # name -> set of ids
        self.mined = 0; self.income_log = []        # (tick, amount)
        self.lost_value = 0; self.killed_value = 0
        self.alive = True


class Game:
    def __init__(self, factions=("aurum", "sable"), seed=0, gmap=None, max_ticks=18000):
        self.map = m = gmap or default_map()
        self.W, self.H = m.w, m.h
        n = self.N = m.w * m.h
        self.seed = seed; self.tick = 0; self.max_ticks = max_ticks
        self.level = m.level; self.ramp = m.ramp; self.brush = m.brush; self.block = list(m.block)
        self.vis_h = [m.level[i] - (1 if m.ramp[i] else 0) for i in range(n)]
        self.occ = [0] * n
        self.occ_ver = 0
        self.ents = {}; self.next_id = 1
        self.players = [Player(i, f, n) for i, f in enumerate(factions)]
        self.winner = None; self.over = False
        self._fields = OrderedDict(); self._masks = {}
        self._build_nbrs(); self._build_regions()
        self._spiral = sorted(((dx, dy) for dx in range(-4, 5) for dy in range(-4, 5)),
                              key=lambda o: (o[0] * o[0] + o[1] * o[1], o))
        for (x, y) in m.ore:
            e = self._new(-1, "ore", x + 0.5, y + 0.5, None)
            e.amt = D.ORE_PER_PATCH; e.tx, e.ty, e.size = x, y, 1
            self.occ[m.idx(x, y)] = e.id
        for p in self.players:
            sx, sy = m.starts[p.id]
            hq = self._place_struct(p.id, "hq", sx, sy, done=True)
            for k in range(D.START_WORKERS):
                t = self._free_tile_near(hq.x, hq.y, k)
                self._spawn_unit(p.id, "wrk", t)
        self.update_vision()

    # ------------------------------------------------------------------ terrain
    def idx(self, x, y): return y * self.W + x
    def in_map(self, x, y): return 0 <= x < self.W and 0 <= y < self.H

    def _edge(self, a, b):
        if self.block[a] or self.block[b]: return False
        la, lb, ra, rb = self.level[a], self.level[b], self.ramp[a], self.ramp[b]
        if ra == rb: return la == lb
        if ra: return lb in (la, la - 1)
        return la in (lb, lb - 1)

    def _build_nbrs(self):
        W, H = self.W, self.H
        self.nbrs = [[] for _ in range(self.N)]
        for y in range(H):
            for x in range(W):
                a = y * W + x
                if self.block[a]: continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and self._edge(a, ny * W + nx):
                        self.nbrs[a].append((ny * W + nx, 1.0, -1, -1))
                for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < W and 0 <= ny < H): continue
                    b = ny * W + nx; o1 = y * W + nx; o2 = ny * W + x
                    if self._edge(a, b) and self._edge(a, o1) and self._edge(a, o2) and self._edge(o1, b) and self._edge(o2, b):
                        self.nbrs[a].append((b, SQ2, o1, o2))
        self.edge_set = [set(n[0] for n in ns) for ns in self.nbrs]

    def _build_regions(self):
        """Connected flat areas (non-ramp) become regions R0..; ramp groups become r0.. linking regions."""
        W = self.W
        self.region = [-1] * self.N; self.regions = []; self.ramps = []
        self.ramp_id = [-1] * self.N
        for start in range(self.N):
            if self.block[start] or self.region[start] >= 0 or self.ramp[start]: continue
            rid = len(self.regions); cells = []; stack = [start]; self.region[start] = rid
            while stack:
                t = stack.pop(); cells.append(t)
                for n, c, _, _ in self.nbrs[t]:
                    if c == 1.0 and self.region[n] < 0 and not self.ramp[n]:
                        self.region[n] = rid; stack.append(n)
            xs = [c % W for c in cells]; ys = [c // W for c in cells]
            self.regions.append(dict(id=rid, level=self.level[start], size=len(cells),
                                     cx=sum(xs) // len(xs), cy=sum(ys) // len(ys),
                                     bbox=(min(xs), min(ys), max(xs), max(ys)), ramps=[], ore=0, tag=""))
        for start in range(self.N):
            if not self.ramp[start] or self.ramp_id[start] >= 0: continue
            rid = len(self.ramps); cells = []; stack = [start]; self.ramp_id[start] = rid; link = set()
            while stack:
                t = stack.pop(); cells.append(t)
                for n, c, _, _ in self.nbrs[t]:
                    if self.ramp[n]:
                        if self.ramp_id[n] < 0: self.ramp_id[n] = rid; stack.append(n)
                    elif c == 1.0: link.add(self.region[n])
            xs = [c % W for c in cells]; ys = [c // W for c in cells]
            self.ramps.append(dict(id=rid, cx=sum(xs) // len(xs), cy=sum(ys) // len(ys), link=sorted(link)))
            for r in link: self.regions[r]["ramps"].append(rid)
        for (x, y) in self.map.ore:
            # ore tiles sit inside a region
            r = self.region[self.idx(x, y)]
            if r >= 0: self.regions[r]["ore"] += 1
        for pid, (sx, sy) in enumerate(self.map.starts):
            main = self.region[self.idx(sx, sy)]
            self.regions[main]["tag"] = "P%d main" % pid
            for rr in self.regions[main]["ramps"]:
                for o in self.ramps[rr]["link"]:
                    if o != main and not self.regions[o]["tag"]: self.regions[o]["tag"] = "P%d natural" % pid

    def region_at(self, x, y):
        t = self.idx(int(x), int(y))
        if self.ramp[t]: return "r%d" % self.ramp_id[t]
        r = self.region[t]
        return "R%d" % r if r >= 0 else "-"

    # ------------------------------------------------------------------ entities
    def _new(self, owner, type, x, y, st):
        e = Ent(self.next_id, owner, type, x, y, st); self.next_id += 1
        e.born = self.tick
        self.ents[e.id] = e
        return e

    def _foot(self, tx, ty, size):
        return [self.idx(x, y) for y in range(ty, ty + size) for x in range(tx, tx + size)]

    def _place_struct(self, pid, code, tx, ty, done=False):
        st = self.players[pid].stats[code]
        e = self._new(pid, code, tx + st["size"] / 2, ty + st["size"] / 2, st)
        e.tx, e.ty, e.size = tx, ty, st["size"]
        e.prog = 1.0 if done else 0.0
        e.hp = st["hp"] if done else max(1, st["hp"] // 10)
        foot = self._foot(tx, ty, e.size)
        for t in foot: self.occ[t] = e.id
        self.occ_ver += 1
        fs = set(foot)
        for u in list(self.ents.values()):          # eject ground units standing in the footprint
            if not u.struct and u.type != "ore" and not u.fly and self.idx(int(u.x), int(u.y)) in fs:
                t = self._free_tile_near(u.x, u.y, 0)
                u.x, u.y = t % self.W + 0.5, t // self.W + 0.5
        return e

    def _spawn_unit(self, pid, code, tile):
        st = self.players[pid].stats[code]
        return self._new(pid, code, tile % self.W + 0.5, tile // self.W + 0.5, st)

    def _free_tile_near(self, x, y, skip=0, same_as=None):
        """Nearest walkable free tile to (x,y). `skip` picks the k-th candidate (for spreading spawns)."""
        cx, cy = int(x), int(y); k = 0
        for r in range(0, 12):
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dx), abs(dy)) != r: continue
                    nx, ny = cx + dx, cy + dy
                    if not self.in_map(nx, ny): continue
                    t = self.idx(nx, ny)
                    if self.block[t] or self.occ[t]: continue
                    if same_as is not None and self.region[t] != same_as: continue
                    if k >= skip: return t
                    k += 1
        return self.idx(cx, cy)

    def supply(self, pid):
        used = cap = 0
        for e in self.ents.values():
            if e.owner != pid: continue
            if e.struct:
                if e.prog >= 1.0: cap += e.st["supply"]
                for u in e.queue: used += self.players[pid].stats[u]["sup"]
            else:
                used += e.st["sup"]
        return used, cap

    def event(self, pid, kind, text, key=None, gap=100):
        p = self.players[pid]
        if key is not None:
            last = p.throttle.get(key, -10 ** 9)
            if self.tick - last < gap: return
            p.throttle[key] = self.tick
        p.events.append((self.tick, kind, text))

    # ------------------------------------------------------------------ vision
    def _mask(self, tile, eye, sight):
        key = (tile, eye, sight)
        m = self._masks.get(key)
        if m is not None: return m
        W = self.W; cx, cy = tile % W, tile // W; r = int(sight); out = []
        vh = self.vis_h; brush = self.brush; r2 = sight * sight
        src_brush = brush[tile]
        for y in range(max(0, cy - r), min(self.H, cy + r + 1)):
            for x in range(max(0, cx - r), min(W, cx + r + 1)):
                dx, dy = x - cx, y - cy
                if dx * dx + dy * dy > r2: continue
                t = y * W + x
                if eye < 9:
                    if vh[t] > eye: continue
                    steps = max(abs(dx), abs(dy)); ok = True; in_src = src_brush
                    for s in range(1, steps):
                        ix = cx + int(round(dx * s / steps)); iy = cy + int(round(dy * s / steps))
                        it = iy * W + ix
                        if vh[it] > eye: ok = False; break
                        if brush[it]:
                            if not in_src: ok = False; break
                        else: in_src = False
                    if not ok: continue
                out.append(t)
        self._masks[key] = out
        return out

    def eye_of(self, e):
        if e.fly: return 9
        t = self.idx(int(e.x), int(e.y))
        return self.vis_h[t] + (e.st.get("eye_bonus", 0) if e.struct else 0)

    def update_vision(self):
        for p in self.players:
            vis = bytearray(self.N); seen = set()
            for e in self.ents.values():
                if e.owner != p.id: continue
                if e.struct and e.prog < 1.0: sight = 2
                else: sight = e.st["sight"]
                key = (self.idx(int(e.x), int(e.y)), self.eye_of(e), sight)
                if key in seen: continue
                seen.add(key)
                for t in self._mask(*key): vis[t] = 1
            p.vis = vis
            ex = p.explored
            for i in range(self.N):
                if vis[i]: ex[i] = 1
        for p in self.players:
            ve = set(); mine = [e for e in self.ents.values() if e.owner == p.id and (not e.struct or e.prog >= 1)]
            vis = p.vis
            for e in self.ents.values():
                if e.owner == p.id or e.owner < 0: continue
                v = False
                if e.reveal > self.tick: v = True
                elif e.struct:
                    v = any(vis[t] for t in self._foot(e.tx, e.ty, e.size))
                elif e.fly:
                    for u in mine:
                        s = u.st["sight"]
                        if (u.x - e.x) ** 2 + (u.y - e.y) ** 2 <= s * s: v = True; break
                else:
                    v = bool(vis[self.idx(int(e.x), int(e.y))])
                if v:
                    ve.add(e.id)
                    if e.struct:
                        if e.id not in p.mem:
                            self.event(p.id, "found", "enemy %s#%d @%d,%d" % (e.type, e.id, e.x, e.y))
                        p.mem[e.id] = dict(type=e.type, x=int(e.x), y=int(e.y), t=self.tick,
                                           hp=int(100 * e.hp / e.st["hp"]))
                    elif e.st["dmg"] > 0 and e.type != "wrk":
                        self.event(p.id, "contact", "enemy %s @%d,%d/%s" % (e.type, e.x, e.y, self.region_at(e.x, e.y)),
                                   key=("contact", int(e.x) // 10, int(e.y) // 10), gap=150)
            for sid in [s for s in p.mem if s not in self.ents]:
                mm = p.mem[sid]
                if vis[self.idx(mm["x"], mm["y"])]: del p.mem[sid]
            p.vis_ents = ve

    def visible(self, pid, e):
        return e.owner == pid or e.id in self.players[pid].vis_ents

    # ------------------------------------------------------------------ pathing
    def field(self, seeds):
        key = seeds
        f = self._fields.get(key)
        if f is not None and f[0] == self.occ_ver:
            self._fields.move_to_end(key); return f[1]
        dist = [INF] * self.N; heap = []; ss = set(seeds); occ = self.occ; nbrs = self.nbrs
        for s in seeds: dist[s] = 0.0; heap.append((0.0, s))
        pop, push = heapq.heappop, heapq.heappush
        while heap:
            d, t = pop(heap)
            if d > dist[t]: continue
            for n, c, o1, o2 in nbrs[t]:
                if occ[n] and n not in ss: continue
                if o1 >= 0 and (occ[o1] or occ[o2]): continue
                nd = d + c
                if nd < dist[n]: dist[n] = nd; push(heap, (nd, n))
        self._fields[key] = (self.occ_ver, dist)
        if len(self._fields) > 300: self._fields.popitem(last=False)
        return dist

    def line_walkable(self, a, b):
        W = self.W; ax, ay, bx, by = a % W, a // W, b % W, b // W
        dx, dy = bx - ax, by - ay; steps = max(abs(dx), abs(dy))
        if steps > 14: return False
        prev = a; occ = self.occ
        for s in range(1, steps + 1):
            t = (ay + int(round(dy * s / steps))) * W + ax + int(round(dx * s / steps))
            if t == prev: continue
            if t not in self.edge_set[prev] or occ[t]: return False
            px, py, qx, qy = prev % W, prev // W, t % W, t // W
            if px != qx and py != qy and (occ[py * W + qx] or occ[qy * W + px]): return False
            prev = t
        return True

    def move_toward(self, e, gx, gy, seeds=None):
        """Advance one tick toward (gx,gy). Returns 'moved', 'arrived' or 'blocked'."""
        spd = e.st["spd"]
        dx, dy = gx - e.x, gy - e.y; d = math.hypot(dx, dy)
        if e.fly:
            if d <= spd: e.x, e.y = gx, gy; return "arrived"
            e.x += dx / d * spd; e.y += dy / d * spd; e.moving = True; return "moved"
        W = self.W; ct = int(e.y) * W + int(e.x)
        gt = int(gy) * W + int(gx)
        px, py = gx, gy
        if ct != gt and not (seeds is None and self.line_walkable(ct, gt)):
            f = self.field(seeds or (gt,))
            if f[ct] == INF: return "blocked"
            best = None; bd = f[ct]; occ = self.occ
            for n, c, o1, o2 in self.nbrs[ct]:
                if occ[n]: continue
                if o1 >= 0 and (occ[o1] or occ[o2]): continue
                if f[n] < bd - 1e-9: bd = f[n]; best = n
            if best is None: return "arrived"
            if best != gt or seeds:
                px, py = best % W + 0.5, best // W + 0.5
            dx, dy = px - e.x, py - e.y; d = math.hypot(dx, dy)
        elif ct == gt and self.occ[gt]:
            return "arrived"
        if d <= spd:
            e.x, e.y = px, py
            return "arrived" if (px == gx and py == gy) else "moved"
        e.x += dx / d * spd; e.y += dy / d * spd; e.moving = True
        return "moved"

    # ------------------------------------------------------------------ orders (validated API)
    def own(self, pid, ids):
        return [self.ents[i] for i in ids if i in self.ents and self.ents[i].owner == pid]

    def order_units(self, pid, ids, order):
        """order: ('move',x,y) ('amove',x,y) ('attack',id) ('hold',) ('stop',) ('gather',ore_id)."""
        units = [e for e in self.own(pid, ids) if not e.struct]
        if not units: return "no units selected"
        kind = order[0]
        if kind in ("move", "amove"):
            x, y = float(order[1]), float(order[2])
            if not self.in_map(int(x), int(y)): return "off map"
            gt = self.idx(int(x), int(y))
            if self.block[gt] or self.occ[gt]:
                gt = self._free_tile_near(x, y); x, y = gt % self.W + 0.5, gt // self.W + 0.5
            reg = self.region[gt]; k = 0
            for e in sorted(units, key=lambda u: u.id):
                self._release(e)
                sx, sy = x, y
                if len(units) > 1 and not e.fly:
                    while k < len(self._spiral):
                        ox, oy = self._spiral[k]; k += 1
                        tx, ty = int(x) + ox, int(y) + oy
                        if not self.in_map(tx, ty): continue
                        t = self.idx(tx, ty)
                        if self.block[t] or self.occ[t] or self.region[t] != reg or self.ramp[t]: continue
                        sx, sy = tx + 0.5, ty + 0.5; break
                e.order = (kind, sx, sy); e.tgt = 0; e.goal = (int(x), int(y))
            return None
        if kind == "attack":
            t = self.ents.get(order[1])
            if t is None or t.owner == pid or t.owner < 0: return "bad target"
            if not self.visible(pid, t) and t.id not in self.players[pid].mem: return "target not visible"
            for e in units:
                self._release(e); e.order = ("attack", t.id); e.tgt = 0; e.last_seen = (t.x, t.y)
            return None
        if kind in ("hold", "stop"):
            for e in units:
                self._release(e); e.order = ("hold",) if kind == "hold" else ("idle",); e.tgt = 0
            return None
        if kind == "gather":
            o = self.ents.get(order[1])
            if o is None or o.type != "ore": return "not an ore patch"
            ws = [e for e in units if e.type == "wrk"]
            if not ws: return "no workers selected"
            for e in ws:
                self._release(e); e.order = ("gather", o.id); e.gs = "to_hq" if e.carry else "to_ore"; e.tgt = 0
            return None
        return "unknown order"

    def _release(self, e):
        """Called before replacing an order: refund a reserved build."""
        if e.order[0] == "build":
            self.players[e.owner].ore += self.players[e.owner].stats[e.order[1]]["cost"]

    def can_place(self, pid, code, tx, ty):
        st = self.players[pid].stats[code]; size = st["size"]
        if tx < 1 or ty < 1 or tx + size > self.W - 1 or ty + size > self.H - 1: return "off map"
        foot = self._foot(tx, ty, size); l0 = self.level[foot[0]]; p = self.players[pid]
        for t in foot:
            if self.block[t] or self.occ[t] or self.ramp[t] or self.level[t] != l0: return "site not buildable"
            if not p.explored[t]: return "site not explored"
        if code == "hq":
            for o in self.ents.values():
                if o.type == "ore" and abs(o.x - (tx + 1.5)) < 3.5 and abs(o.y - (ty + 1.5)) < 3.5: return "too close to ore"
        return None

    def find_site(self, pid, code, x, y, radius=6):
        best = None; bd = INF
        size = self.players[pid].stats[code]["size"]
        for ty in range(int(y) - radius, int(y) + radius + 1):
            for tx in range(int(x) - radius, int(x) + radius + 1):
                d = (tx + size / 2 - x) ** 2 + (ty + size / 2 - y) ** 2
                if d < bd and self.can_place(pid, code, tx, ty) is None and self._site_clear(tx, ty, size):
                    bd = d; best = (tx, ty)
        return best

    def _site_clear(self, tx, ty, size):
        """Keep a 1-tile walkable margin so structures never seal ramps or ore."""
        for y in range(ty - 1, ty + size + 1):
            for x in range(tx - 1, tx + size + 1):
                if not self.in_map(x, y): return False
                t = self.idx(x, y)
                if self.ramp[t] or (self.occ[t] and self.ents[self.occ[t]].type != "ore" and
                                    not (tx <= x < tx + size and ty <= y < ty + size)): return False
        return True

    def order_build(self, pid, wid, code, tx, ty):
        p = self.players[pid]
        if code not in D.STRUCTS: return "unknown structure"
        st = p.stats[code]
        ws = [e for e in self.own(pid, [wid]) if e.type == "wrk"]
        if not ws: return "need a worker"
        w = ws[0]
        # resume an unfinished structure
        for e in self.ents.values():
            if e.owner == pid and e.struct and e.prog < 1.0 and e.tx == tx and e.ty == ty and e.type == code:
                self._release(w); w.order = ("construct", e.id); return None
        if st["req"] and not any(e.owner == pid and e.type == st["req"] and e.prog >= 1 for e in self.ents.values()):
            return "requires %s" % st["req"]
        if p.ore < st["cost"]: return "need %d ore (have %d)" % (st["cost"], p.ore)
        err = self.can_place(pid, code, tx, ty)
        if err: return err
        self._release(w)
        p.ore -= st["cost"]
        w.order = ("build", code, tx, ty); w.tgt = 0
        return None

    def order_train(self, pid, sid, ucode):
        p = self.players[pid]; s = self.ents.get(sid)
        if s is None or s.owner != pid or not s.struct: return "no such structure"
        if s.prog < 1.0: return "%s#%d not finished" % (s.type, s.id)
        if ucode not in s.st["trains"]: return "%s cannot train %s" % (s.type, ucode)
        if len(s.queue) >= D.MAX_QUEUE: return "queue full"
        st = p.stats[ucode]
        if p.ore < st["cost"]: return "need %d ore (have %d)" % (st["cost"], p.ore)
        used, cap = self.supply(pid)
        if used + st["sup"] > cap: return "supply blocked %d/%d (build dep)" % (used, cap)
        p.ore -= st["cost"]
        s.queue.append(ucode)
        if len(s.queue) == 1: s.timer = st["time"]
        return None

    def order_cancel(self, pid, sid):
        s = self.ents.get(sid); p = self.players[pid]
        if s is None or s.owner != pid or not s.struct: return "no such structure"
        if not s.queue: return "queue empty"
        u = s.queue.pop(); p.ore += p.stats[u]["cost"]
        return None

    # ------------------------------------------------------------------ combat helpers
    def dist(self, e, t):
        if t.size:
            h = t.size / 2
            dx = max(abs(e.x - t.x) - h, 0); dy = max(abs(e.y - t.y) - h, 0)
            return math.hypot(dx, dy)
        return math.hypot(e.x - t.x, e.y - t.y)

    def can_hit(self, e, t):
        st = e.st
        if t.fly: return st["aa"]
        if st["rng"] <= 1.5 and not e.fly:
            a = self.idx(int(e.x), int(e.y))
            if t.size: return True
            b = self.idx(int(t.x), int(t.y))
            return a == b or b in self.edge_set[a]
        return True

    def _fire(self, e, t):
        st = e.st; e.cd = st["cd"]; e.reveal = self.tick + D.REVEAL_TICKS
        mult = 1.0
        if st["rng"] > 1.5 and not e.fly and not t.fly and \
                self.vis_h[self.idx(int(t.x), int(t.y))] > self.eye_of(e):
            mult = D.UPHILL_MULT
        self._damage(e, t, st["dmg"] * mult)
        if st["splash"]:
            r2 = st["splash"] ** 2
            for o in list(self.ents.values()):
                if o is not t and o.owner >= 0 and o.owner != e.owner and not o.fly and \
                        (o.x - t.x) ** 2 + (o.y - t.y) ** 2 <= r2:
                    self._damage(e, o, st["dmg"] * mult * 0.5)

    def _damage(self, src, t, dmg):
        if t.id not in self.ents: return
        dmg = max(1.0, dmg - t.st["armor"])
        t.hp -= dmg
        if t.owner >= 0:
            self.event(t.owner, "attacked", "%s under attack @%d,%d/%s" % (
                "base" if t.struct else ("workers" if t.type == "wrk" else "army"), t.x, t.y, self.region_at(t.x, t.y)),
                key=("atk", t.struct, int(t.x) // 12, int(t.y) // 12), gap=150)
            # idle victims answer back
            if not t.struct and t.order[0] == "idle" and t.st["dmg"] > 0 and t.type != "wrk" and not t.tgt:
                t.tgt = src.id
        if t.hp <= 0: self._kill(t, src)

    def _kill(self, t, src=None):
        if t.id not in self.ents: return
        del self.ents[t.id]
        if t.owner >= 0:
            p = self.players[t.owner]; val = t.st["cost"]
            p.lost_value += val
            self.event(t.owner, "lost", "%s#%d @%d,%d" % (t.type, t.id, t.x, t.y))
            if t.order[0] == "build": p.ore += p.stats[t.order[1]]["cost"]
            for u in t.queue: p.ore += p.stats[u]["cost"]
            if src is not None and src.owner >= 0 and src.owner != t.owner:
                self.players[src.owner].killed_value += val
                self.event(src.owner, "kill", "%s#%d @%d,%d" % (t.type, t.id, t.x, t.y))
        if t.size:
            for i in self._foot(t.tx, t.ty, t.size):
                if self.occ[i] == t.id: self.occ[i] = 0
            self.occ_ver += 1

    def _acquire(self, e, rng):
        best = None; bd = INF; pid = e.owner; ve = self.players[pid].vis_ents
        for i in ve:
            t = self.ents.get(i)
            if t is None or not self.can_hit(e, t): continue
            d = self.dist(e, t)
            if d > rng: continue
            if t.struct and t.st["dmg"] == 0: d += 100      # prefer things that shoot back
            elif t.type == "wrk": d += 50
            if d < bd: bd = d; best = t
        return best

    # ------------------------------------------------------------------ tick
    def step(self):
        if self.over: return
        self.tick += 1
        tick = self.tick
        ents = self.ents
        order = list(ents.values())
        if tick & 1: order.reverse()            # alternate so neither side always acts first
        for e in order:
            if e.id not in ents or e.owner < 0: continue
            if e.cd > 0: e.cd -= 1
            e.moving = False
            if e.struct: self._tick_struct(e)
            else: self._tick_unit(e)
        if tick % 2 == 0:
            self._separate()
            self.update_vision()
        if tick % 20 == 0: self._check_end()

    def _tick_struct(self, s):
        p = self.players[s.owner]
        if s.prog < 1.0: return
        if s.queue:
            s.timer -= 1
            if s.timer <= 0:
                u = s.queue.pop(0)
                t = self._spawn_tile(s)
                ne = self._spawn_unit(s.owner, u, t)
                self.event(s.owner, "ready", "%s#%d from %s#%d" % (u, ne.id, s.type, s.id))
                if s.rally: ne.order = ("amove" if u != "wrk" else "move", s.rally[0], s.rally[1])
                if s.queue: s.timer = p.stats[s.queue[0]]["time"]
        elif s.repeat:
            err = self.order_train(s.owner, s.id, s.repeat)
            if err and err.startswith("supply"):
                self.event(s.owner, "warn", "supply blocked", key=("sup",), gap=300)
        if s.st["dmg"] and s.cd <= 0:
            t = self.ents.get(s.tgt)
            if t is None or not self.visible(s.owner, t) or self.dist(s, t) > s.st["rng"]:
                t = self._acquire(s, s.st["rng"]); s.tgt = t.id if t else 0
            if t: self._fire(s, t)

    def _spawn_tile(self, s):
        gx, gy = s.rally if s.rally else (s.x, s.y + s.size)
        best = None; bd = INF
        for y in range(s.ty - 1, s.ty + s.size + 1):
            for x in range(s.tx - 1, s.tx + s.size + 1):
                if not self.in_map(x, y): continue
                t = self.idx(x, y)
                if self.block[t] or self.occ[t] or self.level[t] != self.level[self.idx(s.tx, s.ty)]: continue
                d = (x - gx) ** 2 + (y - gy) ** 2
                if d < bd: bd = d; best = t
        return best if best is not None else self._free_tile_near(s.x, s.y)

    def _tick_unit(self, e):
        o = e.order; kind = o[0]; st = e.st; pid = e.owner
        if kind == "move":
            if self.move_toward(e, o[1], o[2]) != "moved": e.order = ("idle",)
            return
        if kind == "gather": return self._tick_gather(e)
        if kind == "build": return self._tick_build(e)
        if kind == "construct": return self._tick_construct(e)
        if st["dmg"] <= 0:
            if kind == "amove":
                if self.move_toward(e, o[1], o[2]) != "moved": e.order = ("idle",)
            elif kind == "attack": e.order = ("idle",)
            return
        # combat-capable orders: idle, hold, amove, attack
        t = None
        if kind == "attack":
            t = self.ents.get(o[1])
            if t is None: e.order = ("idle",); e.tgt = 0; return
            if not self.visible(pid, t):
                if e.last_seen and self.move_toward(e, e.last_seen[0], e.last_seen[1]) == "moved": return
                e.order = ("idle",); return
            e.last_seen = (t.x, t.y)
        else:
            if e.tgt:
                t = self.ents.get(e.tgt)
                if t is None or not self.visible(pid, t) or not self.can_hit(e, t): t = None; e.tgt = 0
            if t is None and (self.tick + e.id) % 3 == 0 and (e.type != "wrk" or kind == "amove"):
                acq = st["rng"] + 0.5 if kind == "hold" else max(st["sight"], st["rng"])
                t = self._acquire(e, acq); e.tgt = t.id if t else 0
        if t is not None:
            d = self.dist(e, t)
            if d <= st["rng"] + (0.5 if st["rng"] <= 1.5 else 0) and d >= st["minr"] and self.can_hit(e, t):
                if e.cd <= 0: self._fire(e, t)
                return
            if kind == "hold": e.tgt = 0; return
            if d < st["minr"]:
                e.tgt = 0 if kind != "attack" else e.tgt; return
            seeds = tuple(self._foot(t.tx, t.ty, t.size)) if t.size else None
            if self.move_toward(e, t.x, t.y, seeds) == "blocked" and kind != "attack": e.tgt = 0
            return
        if kind == "amove":
            if self.move_toward(e, o[1], o[2]) != "moved": e.order = ("idle",)

    def _nearest_hq(self, e):
        best = None; bd = INF
        for s in self.ents.values():
            if s.owner == e.owner and s.type == "hq" and s.prog >= 1:
                d = (s.x - e.x) ** 2 + (s.y - e.y) ** 2
                if d < bd: bd = d; best = s
        return best

    def _tick_gather(self, e):
        ore = self.ents.get(e.order[1])
        if e.gs == "to_ore":
            if ore is None:
                alt = self.nearest_ore(e.x, e.y, 10)
                if alt is None: e.order = ("idle",); return
                e.order = ("gather", alt.id); return
            if self.dist(e, ore) <= 1.45:
                e.gs = "mining"; e.timer = D.MINE_TICKS; return
            if self.move_toward(e, ore.x, ore.y, (self.idx(ore.tx, ore.ty),)) == "blocked": e.order = ("idle",)
        elif e.gs == "mining":
            if ore is None: e.gs = "to_ore"; return
            e.timer -= 1
            if e.timer <= 0:
                n = min(D.MINE_LOAD, ore.amt); ore.amt -= n; e.carry = n; e.gs = "to_hq"
                if ore.amt <= 0:
                    self.event(e.owner, "warn", "ore patch #%d depleted @%d,%d" % (ore.id, ore.x, ore.y))
                    self._kill(ore)
        else:
            hq = self._nearest_hq(e)
            if hq is None: e.order = ("idle",); return
            if self.dist(e, hq) <= 1.45:
                p = self.players[e.owner]; p.ore += e.carry; p.mined += e.carry
                p.income_log.append((self.tick, e.carry)); e.carry = 0; e.gs = "to_ore"; return
            if self.move_toward(e, hq.x, hq.y, tuple(self._foot(hq.tx, hq.ty, hq.size))) == "blocked": e.order = ("idle",)

    def nearest_ore(self, x, y, maxd=INF, count_workers=False):
        best = None; bd = INF
        load = {}
        if count_workers:
            for u in self.ents.values():
                if u.order[0] == "gather": load[u.order[1]] = load.get(u.order[1], 0) + 1
        for o in self.ents.values():
            if o.type != "ore": continue
            d = math.hypot(o.x - x, o.y - y)
            if d > maxd: continue
            d += 3.0 * load.get(o.id, 0)
            if d < bd: bd = d; best = o
        return best

    def _tick_build(self, e):
        _, code, tx, ty = e.order; p = self.players[e.owner]; st = p.stats[code]; size = st["size"]
        cx, cy = tx + size / 2, ty + size / 2
        d = math.hypot(max(abs(e.x - cx) - size / 2, 0), max(abs(e.y - cy) - size / 2, 0))
        if d <= 1.45:
            err = self.can_place(e.owner, code, tx, ty)
            if err:
                p.ore += st["cost"]; e.order = ("idle",)
                self.event(e.owner, "warn", "build %s @%d,%d failed: %s" % (code, tx, ty, err)); return
            s = self._place_struct(e.owner, code, tx, ty)
            e.order = ("construct", s.id); return
        if self.move_toward(e, cx, cy, tuple(self._foot(tx, ty, size))) == "blocked":
            p.ore += st["cost"]; e.order = ("idle",)
            self.event(e.owner, "warn", "build %s @%d,%d failed: unreachable" % (code, tx, ty))

    def _tick_construct(self, e):
        s = self.ents.get(e.order[1])
        if s is None or s.prog >= 1.0: e.order = ("idle",); return
        if self.dist(e, s) > 1.45:
            if self.move_toward(e, s.x, s.y, tuple(self._foot(s.tx, s.ty, s.size))) == "blocked": e.order = ("idle",)
            return
        s.prog += 1.0 / s.st["time"]
        s.hp = min(s.st["hp"], s.hp + 0.9 * s.st["hp"] / s.st["time"])
        if s.prog >= 1.0:
            s.prog = 1.0; e.order = ("idle",)
            self.event(e.owner, "ready", "%s#%d built @%d,%d" % (s.type, s.id, s.x, s.y))

    def _separate(self):
        W = self.W; cells = {}
        for e in self.ents.values():
            if e.struct or e.owner < 0 or e.fly or e.moving or e.order[0] in ("gather", "build", "construct"): continue
            cells.setdefault((int(e.x), int(e.y)), []).append(e)
        for (cx, cy), lst in cells.items():
            for e in lst:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for o in cells.get((cx + dx, cy + dy), ()):
                            if o.id <= e.id: continue
                            ddx, ddy = o.x - e.x, o.y - e.y; d = math.hypot(ddx, ddy)
                            if d >= 0.6: continue
                            if d < 1e-6:
                                a = (e.id * 2.39996) % 6.283; ddx, ddy, d = math.cos(a), math.sin(a), 1.0
                            push = (0.6 - d) / 2 * 0.5
                            self._nudge(e, -ddx / d * push, -ddy / d * push)
                            self._nudge(o, ddx / d * push, ddy / d * push)

    def _nudge(self, e, dx, dy):
        nx, ny = e.x + dx, e.y + dy
        a = self.idx(int(e.x), int(e.y)); b = self.idx(int(nx), int(ny))
        if a == b or (b in self.edge_set[a] and not self.occ[b] and abs(b - a) in (1, self.W)):
            e.x, e.y = nx, ny

    def _check_end(self):
        alive = []
        for p in self.players:
            p.alive = any(e.owner == p.id and e.struct for e in self.ents.values())
            if p.alive: alive.append(p.id)
        if len(alive) == 1: self.over = True; self.winner = alive[0]
        elif not alive: self.over = True; self.winner = None
        elif self.tick >= self.max_ticks:
            self.over = True
            sc = [self.score(p.id) for p in self.players]
            self.winner = None if sc[0] == sc[1] else (0 if sc[0] > sc[1] else 1)

    def score(self, pid):
        p = self.players[pid]
        return p.ore + sum(e.st["cost"] * (e.hp / e.st["hp"]) for e in self.ents.values() if e.owner == pid)

    # ------------------------------------------------------------------ snapshot (spectator / replay)
    def snapshot(self):
        return dict(t=self.tick, ore=[p.ore for p in self.players],
                    sup=[self.supply(p.id) for p in self.players],
                    e=[[e.id, e.owner, e.type, round(e.x, 2), round(e.y, 2),
                        round(e.hp / e.st["hp"], 2) if e.st else round(e.amt / D.ORE_PER_PATCH, 2),
                        e.size, round(e.prog, 2)] for e in self.ents.values()],
                    vis=[_pack(p.vis) for p in self.players])


def _pack(b):
    import base64
    out = bytearray((len(b) + 7) // 8)
    for i, v in enumerate(b):
        if v: out[i >> 3] |= 1 << (i & 7)
    return base64.b64encode(bytes(out)).decode()
