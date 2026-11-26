"""Random province maps. Every seed gives a different map and a different, asymmetric start."""
import math
import random

from . import data as D


class Prov:
    __slots__ = ("id", "terrain", "elev", "y", "mp", "city", "nbrs", "cx", "cy", "cells", "cost", "dfn", "biome", "sea", "name", "steel", "oil", "rare", "coal", "rubber", "lat", "river")

    def __init__(self, id):
        self.id = id; self.terrain = "plain"; self.elev = 0; self.y = 0; self.mp = 0; self.city = False
        self.nbrs = []; self.cx = self.cy = 0.0; self.cells = 0; self.cost = 16; self.dfn = 1.0
        self.steel = self.oil = self.rare = self.coal = self.rubber = 0; self.lat = 30.0   # latitude (only the world map has a real one)     # daily yield of the deposit here, if any
        self.biome = ""             # "" temperate, "desert", "tundra": harsh ground (poor, slow, supplies arrive at half speed)
        self.river = frozenset()    # neighbours on the far bank of a great river (world map)
        self.sea = ()               # neighbours reached across water (a strait or a sea lane), a subset of nbrs
        self.name = ""              # real-world place name where there is one (world map cities)


class Map:
    def __init__(self):
        self.gw = self.gh = 0; self.cell = []; self.provs = []; self.seed = 0
        self.capitals = []; self.start_provs = []; self.start_units = []; self.start_res = []; self.start_mp = []; self.scale = 1.0; self.world = False; self.names = []; self.start_bank = []


def gen_map(seed=0, gw=504, gh=312, cols=88, rows=56, players=3):
    """Default: 88 x 56 province seeds (about 4,900 provinces), three factions. Smaller maps for tests and quick
    experiments: gen_map(seed, 126, 78, 22, 14, players=2)."""
    rng = random.Random(seed)
    area = cols * rows / 308.0                      # 1.0 = the old 22 x 14 map
    m = Map(); m.gw, m.gh, m.seed = gw, gh, seed
    pts = []
    for r in range(rows):
        for c in range(cols):
            pts.append(((c + 0.15 + 0.7 * rng.random()) * gw / cols, (r + 0.15 + 0.7 * rng.random()) * gh / rows))
    n = len(pts); m.provs = [Prov(i) for i in range(n)]
    m.cell = [0] * (gw * gh)
    cw, chh = gw / cols, gh / rows
    for y in range(gh):
        for x in range(gw):
            c0, r0 = int((x + 0.5) / cw), int((y + 0.5) / chh); best = -1; bd = 1e18
            for r in range(max(0, r0 - 1), min(rows, r0 + 2)):          # the nearest seed is always in the 3x3 block
                for c in range(max(0, c0 - 1), min(cols, c0 + 2)):
                    i = r * cols + c; d = (pts[i][0] - x - 0.5) ** 2 + (pts[i][1] - y - 0.5) ** 2
                    if d < bd: bd = d; best = i
            m.cell[y * gw + x] = best
            p = m.provs[best]; p.cx += x + 0.5; p.cy += y + 0.5; p.cells += 1
    for p in m.provs:
        if p.cells: p.cx /= p.cells; p.cy /= p.cells
        else: p.cx, p.cy = pts[p.id]
    adj = [set() for _ in range(n)]
    for y in range(gh):
        for x in range(gw):
            a = m.cell[y * gw + x]
            if x + 1 < gw:
                b = m.cell[y * gw + x + 1]
                if a != b: adj[a].add(b); adj[b].add(a)
            if y + 1 < gh:
                b = m.cell[(y + 1) * gw + x]
                if a != b: adj[a].add(b); adj[b].add(a)
    # height field: mountain ranges (ridged line segments), rolling hills, and basins that fill with water
    ranges = []
    for _ in range(int(rng.randint(4, 6) * area ** 0.6)):
        x0, y0 = rng.random() * gw, rng.random() * gh; ang = rng.random() * 6.283; ln = rng.uniform(30, 63) * area ** 0.2
        ranges.append((x0, y0, x0 + math.cos(ang) * ln, y0 + math.sin(ang) * ln, rng.uniform(4, 7)))
    bumps = [(rng.random() * gw, rng.random() * gh, rng.choice((0.7, 0.6, -1.0, -1.1)), rng.uniform(6, 13)) for _ in range(int(14 * area))]

    def seg_d2(px, py, x0, y0, x1, y1):
        dx, dy = x1 - x0, y1 - y0; t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy + 1e-9)))
        return (px - x0 - t * dx) ** 2 + (py - y0 - t * dy) ** 2
    for p in m.provs:
        h = sum(s * math.exp(-((p.cx - bx) ** 2 + (p.cy - by) ** 2) / (2 * r * r)) for bx, by, s, r in bumps)
        h += sum(1.3 * math.exp(-seg_d2(p.cx, p.cy, x0, y0, x1, y1) / (2 * w * w)) for x0, y0, x1, y1, w in ranges)
        h += rng.uniform(-0.15, 0.15)
        edge = min(p.cx, p.cy, gw - p.cx, gh - p.cy)
        if edge < 5 and rng.random() < 0.45: h -= 1.0               # ragged coastline
        if p.cells == 0 or h < -0.5: p.terrain = "water"
        elif h > 0.95: p.terrain = "mountain"
        elif h > 0.5: p.terrain = "hill"
        elif rng.random() < 0.25: p.terrain = "forest"
        # four height levels: 0 lowland, 1 upland (plain or forest on raised ground), 2 hills, 3 mountains
        p.elev = 3 if p.terrain == "mountain" else 2 if p.terrain == "hill" else 1 if h > 0.12 else 0
    # keep the largest land mass
    land = [p.id for p in m.provs if p.terrain != "water"]; best = []; seen = set()
    for s in land:
        if s in seen: continue
        comp = [s]; seen.add(s); i = 0
        while i < len(comp):
            for b in adj[comp[i]]:
                if b not in seen and m.provs[b].terrain != "water": seen.add(b); comp.append(b)
            i += 1
        if len(comp) > len(best): best = comp
    keep = set(best)
    for p in m.provs:
        if p.id not in keep: p.terrain = "water"; p.elev = 0
        t = D.TERRAIN[p.terrain]; p.cost = t["cost"]; p.dfn = t["dfn"]
        p.y = rng.randint(*t["y"]) if p.terrain != "water" else 0
        p.mp = rng.randint(*t["mp"]) if p.terrain != "water" else 0
        p.nbrs = sorted(b for b in adj[p.id] if b in keep) if p.id in keep else []
    land = sorted(keep)
    # cities: spread out, never on mountains
    cities = []
    cand = [i for i in land if m.provs[i].terrain != "mountain"]; rng.shuffle(cand)
    for i in cand:
        if len(cities) >= max(8, len(land) // 7): break
        if all(i not in m.provs[c].nbrs and i != c for c in cities): cities.append(i)
    for c in cities:
        p = m.provs[c]; p.city = True; p.y += D.CITY_YIELD; p.mp += D.CITY_MP; p.dfn += D.CITY_DFN
    # a few resource hubs: provinces worth fighting over
    hubs = [i for i in land if i not in cities]; rng.shuffle(hubs)
    for i in hubs[:max(4, len(land) // 12)]: m.provs[i].y += rng.randint(3, 6)
    deposits(m, land, random.Random(seed * 7 + 3))
    # asymmetric start: capitals far apart, random territory size, army and treasury
    # (several capitals, mutually far apart: farthest-point picks from a random first city)
    caps = [rng.choice(cities)]; dist = {caps[0]: graph_dist(m, caps[0])}
    caps[0] = max(cities, key=lambda c: (dist[caps[0]].get(c, 0), c)); dist = {caps[0]: graph_dist(m, caps[0])}
    while len(caps) < players:
        far = sorted(cities, key=lambda c: -min(dist[k].get(c, 0) for k in caps))
        c = rng.choice(far[:max(1, len(far) // 12)]); caps.append(c); dist[c] = graph_dist(m, c)
    rng.shuffle(caps); m.capitals = caps; m.scale = sc = max(1.0, area ** 0.5)
    for pid, cap in enumerate(caps):
        k = int(rng.randint(26, 48) * sc); order = sorted(dist[cap], key=lambda i: (dist[cap][i], rng.random()))
        mine = [i for i in order if all(dist[cap][i] < dist[o].get(i, 9999) for o in caps if o != cap)][:k + 1]
        m.start_provs.append(mine)
        army = ["inf"] * int(16 * sc) + [rng.choice(("inf", "inf", "inf", "mil", "mil", "mtn", "mot", "arm", "art", "eng", "rec"))
                                         for _ in range(int(rng.randint(30, 60) * sc))]
        m.start_units.append([(t, rng.choice(mine)) for t in army])
        m.start_res.append(int(rng.randint(200, 600) * sc)); m.start_mp.append(int(rng.randint(300, 800) * sc))
    start_bank(m, random.Random(seed * 11 + 5), sc)
    return m


def deposits(m, land, rng):
    """Steel, oil and rare-material deposits. Steel likes hills and mountains, oil likes deserts, tundra and plains,
    rare materials turn up anywhere but mostly in high ground."""
    like = dict(steel=lambda p: 2.2 if p.terrain in D.HIGH else 0.7, oil=lambda p: 2.5 if p.biome else 1.0 if p.terrain == "plain" else 0.4,
                rare=lambda p: 2.0 if p.terrain in D.HIGH else 0.8, coal=lambda p: 1.8 if p.terrain in ("hill", "forest") else 0.8,
                rubber=lambda p: 2.5 if p.terrain == "forest" else 0.5)
    for kind, (share, lo, hi) in D.DEPOSIT.items():
        for i in land:
            p = m.provs[i]
            if rng.random() < share * like[kind](p): setattr(p, kind, rng.randint(lo, hi))


def start_bank(m, rng, sc=1.0):
    """Random starting stockpiles of the three special resources (asymmetric, like everything else at the start)."""
    m.start_bank = [dict(steel=int(rng.randint(40, 160) * sc), oil=int(rng.randint(30, 120) * sc), rare=int(rng.randint(5, 30) * sc), coal=int(rng.randint(20, 90) * sc), rubber=int(rng.randint(10, 50) * sc)) for _ in m.capitals]


def graph_dist(m, src):
    d = {src: 0}; q = [src]; i = 0
    while i < len(q):
        for b in m.provs[q[i]].nbrs:
            if b not in d: d[b] = d[q[i]] + 1; q.append(b)
        i += 1
    return d


def ascii_map(m, mark=None):
    """Coarse character map (one char per grid cell): province id mod 36, water '~'."""
    ch = "0123456789abcdefghijklmnopqrstuvwxyz"; rows = []
    for y in range(m.gh):
        rows.append("".join("~" if m.provs[m.cell[y * m.gw + x]].terrain == "water" else
                            (mark or {}).get(m.cell[y * m.gw + x], ch[m.cell[y * m.gw + x] % 36]) for x in range(m.gw)))
    return "\n".join(rows)


if __name__ == "__main__":
    import sys
    m = gen_map(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
    print(ascii_map(m)); print("capitals", m.capitals, "start", m.start_provs, m.start_units, m.start_res)
    print({t: sum(1 for p in m.provs if p.terrain == t) for t in D.TERRAIN})
