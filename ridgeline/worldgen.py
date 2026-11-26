"""The real world as a Ridgeline map: coastlines from Natural Earth (public domain; see tools/build_world.py),
mountain ranges and deserts placed by hand at their real positions, about 30 factions starting around real cities.

Projection: equirectangular, one cell = 0.3125 degrees at scale 1 (1152 x 420 cells, 75N to 56S). Provinces are grown
outwards from seed points over land only, so a province never spans a strait. Land masses are joined by sea links
(Prov.sea): short straits and a few longer sea lanes, so every faction can reach every other.

The geography (cells, provinces, terrain, links) is the same every game; the seed only changes yields, minor cities and
each faction's starting territory, army and treasury. Built once per process and cached on disk.
"""
import heapq
import math
import os
import pickle
import random
import tempfile
import zlib

from . import data as D
from .mapgen import Map, Prov, deposits, start_bank

W0, H0 = 1152, 420; LAT_N, LAT_S = 75.0, -56.25
HERE = os.path.dirname(os.path.abspath(__file__))
VERSION = 3

# (weight, half-width in degrees, [(lat, lon), ...]) weight 1.3 = high range, 0.8 = uplands
RANGES = [
    (1.5, 1.6, [(35, 74), (31, 79), (28, 86), (28, 95)]), (1.0, 2.6, [(34, 80), (33, 90), (32, 97)]), (1.3, 1.0, [(36, 80), (36, 95)]),
    (1.3, 1.0, [(35, 69), (37, 72), (39, 74)]), (1.3, 1.0, [(42, 74), (42, 80), (43, 88)]), (1.2, 1.0, [(49, 87), (46, 95)]),
    (1.3, 1.0, [(38, 44), (33, 48), (29, 53), (27, 57)]), (1.3, 0.7, [(43.5, 40), (42, 45), (41, 48)]), (1.2, 0.6, [(36.5, 49), (36, 55)]),
    (1.1, 0.8, [(37, 30), (37.5, 36), (39, 42)]), (1.3, 0.7, [(44.3, 7), (46.3, 9.5), (47.2, 13.5)]), (1.2, 0.5, [(42.8, -1.5), (42.4, 2.5)]),
    (1.1, 0.6, [(49.3, 19), (48, 24.5), (45.6, 25.5), (45.3, 22.5)]), (1.1, 0.7, [(45, 15), (42.5, 19.5), (40, 21)]),
    (1.2, 0.8, [(60, 7.5), (64, 13), (68.5, 18)]), (1.0, 0.7, [(66, 60), (60, 59), (53, 58.5)]), (1.0, 0.5, [(44.3, 9.5), (42.3, 13.3), (40.2, 16)]),
    (1.2, 0.8, [(31, -8), (33.5, -3), (35.5, 5)]), (1.2, 1.2, [(13.5, 38), (8, 39)]), (0.9, 0.9, [(1, 36), (-4, 35.3), (-10, 34)]),
    (1.0, 0.8, [(-28, 29.3), (-31, 27.5)]), (0.9, 0.9, [(23.5, 5.5), (21, 17.5)]),
    (1.3, 1.3, [(62, -130), (55, -122), (51, -117), (45, -112), (39.5, -106.3), (34, -106)]), (1.2, 0.7, [(49, -121.3), (42, -122), (37, -118.8)]),
    (1.2, 0.8, [(63, -151), (61, -143), (59, -136)]), (0.8, 0.6, [(34.5, -84), (38, -80), (41.5, -75.5), (45, -70.5)]),
    (1.2, 0.8, [(28.5, -107.5), (23, -104.5), (19, -99), (16.5, -96)]), (1.0, 0.6, [(15.3, -91.5), (13.5, -87), (9.5, -83.5)]),
    (1.5, 0.9, [(10.5, -73), (5, -75), (-1.5, -78.5), (-9.5, -77), (-15.5, -71), (-22, -67.5), (-32.5, -70), (-41, -71.8), (-50, -73)]),
    (0.8, 1.2, [(-20, -44), (-13, -41.5)]), (0.8, 0.9, [(5, -62), (3, -55)]),
    (1.1, 0.9, [(67, 128), (63, 136)]), (1.0, 0.9, [(56, 118), (57, 132)]), (1.2, 0.7, [(60, 163), (54, 158.5)]), (0.9, 0.7, [(48, 138), (44, 134)]),
    (1.0, 0.7, [(34, 104), (33.8, 111)]), (1.2, 0.9, [(31, 99.5), (25.5, 100)]), (1.1, 0.5, [(35.8, 137.5), (37.5, 139.6)]), (0.9, 0.5, [(40.5, 127.5), (36.5, 128.8)]),
    (0.9, 0.6, [(19.5, 103.5), (14.5, 108)]), (1.0, 0.6, [(25.5, 94.5), (19.5, 94.3)]), (1.0, 0.6, [(4.5, 96.8), (-4.8, 103.8)]),
    (1.3, 0.7, [(-3.8, 137.5), (-6, 146)]), (0.9, 0.8, [(3.5, 115.5), (0.5, 113.5)]), (0.8, 0.7, [(-17.5, 145.5), (-28, 152), (-36.5, 148.5)]),
    (1.2, 0.5, [(-42.3, 172.3), (-45, 168.5)]), (0.8, 0.5, [(20, 73.7), (10.5, 77)]), (0.8, 0.8, [(52, 96), (51, 104)]),
    (1.4, 2.5, [(75, -42), (68, -42), (62, -45)]),
]
# where the strategic resources are (lat, lon, radius in degrees): the fields the wars of the last two centuries were fought over
FIELDS = dict(
    oil=[(27, 50, 9), (41, 49, 5), (30, -97, 8), (9, -66, 5), (61, 72, 9), (29, 12, 8), (1, 108, 7), (45, 26, 3), (55, -113, 5), (5, 6, 4)],
    coal=[(53, -2, 3), (51, 10, 6), (48, 38, 4), (38, -81, 6), (37, 113, 7), (23, 86, 5), (-27, 29, 5), (-25, 148, 7), (54, 87, 5)],
    steel=[(65, 20, 5), (49, 6, 3), (56, 59, 6), (47, -90, 6), (-19, -44, 6), (-23, 119, 7), (42, 124, 5), (21, 83, 4), (48, 33, 3), (43, -4, 3), (8, -10, 5)],
    rubber=[(8, 102, 9), (-2, 112, 9), (-4, -62, 10), (0, 20, 9), (6, -5, 6), (9, 78, 4), (15, -88, 4)],
    rare=[(-10, 26, 6), (-26, 27, 5), (26, 112, 7), (-18, -67, 7), (40, -110, 7), (45, 68, 7), (58, 110, 9), (39, 35, 4), (32, -6, 4), (-30, 137, 6)])
DESERTS = [(23, 10, 7.5, 28), (22, 48, 7.5, 8), (32.5, 40, 2.5, 4), (32, 56.5, 3, 4), (41, 61, 4, 7), (39, 83, 2.6, 7), (43, 105, 3.5, 10),
           (27, 71, 2.5, 2.5), (-23, 19, 5.5, 5.5), (-25, 131, 7, 13), (-23, -69.6, 5, 1.2), (30.5, -109, 4, 5), (39, -116, 3, 3)]   # lat, lon, half-height, half-width (degrees)
JUNGLE = [(-3, -62, 9, 14), (0, 21, 6, 9), (2, 110, 9, 14), (16, 100, 6, 6)]
CITIES = [("Chicago", 41.9, -87.6), ("Los Angeles", 34.0, -118.2), ("Houston", 29.8, -95.4), ("Miami", 25.8, -80.2), ("Montreal", 45.5, -73.6),
          ("Denver", 39.7, -105.0), ("Havana", 23.1, -82.4), ("Caracas", 10.5, -66.9), ("Santiago", -33.4, -70.7), ("Sao Paulo", -23.5, -46.6),
          ("Manaus", -3.1, -60.0), ("Dublin", 53.3, -6.3), ("Lisbon", 38.7, -9.1), ("Rome", 41.9, 12.5), ("Vienna", 48.2, 16.4),
          ("Warsaw", 52.2, 21.0), ("Athens", 38.0, 23.7), ("Istanbul", 41.0, 28.9), ("St Petersburg", 59.9, 30.3), ("Baghdad", 33.3, 44.4),
          ("Karachi", 24.9, 67.0), ("Mumbai", 19.1, 72.9), ("Kolkata", 22.6, 88.4), ("Chengdu", 30.7, 104.1), ("Shanghai", 31.2, 121.5),
          ("Seoul", 37.6, 127.0), ("Guangzhou", 23.1, 113.3), ("Manila", 14.6, 121.0), ("Singapore", 1.4, 103.8), ("Bangkok", 13.8, 100.5),
          ("Hanoi", 21.0, 105.8), ("Perth", -32.0, 115.9), ("Melbourne", -37.8, 145.0), ("Auckland", -36.9, 174.8), ("Nairobi", -1.3, 36.8),
          ("Luanda", -8.8, 13.2), ("Khartoum", 15.6, 32.5), ("Dakar", 14.7, -17.4), ("Casablanca", 33.6, -7.6), ("Cape Town", -33.9, 18.4),
          ("Vladivostok", 43.1, 131.9), ("Irkutsk", 52.3, 104.3), ("Almaty", 43.2, 76.9), ("Kabul", 34.5, 69.2), ("Anchorage", 61.2, -149.9),
          ("Reykjavik", 64.1, -21.9), ("Yakutsk", 62.0, 129.7), ("Winnipeg", 49.9, -97.1), ("Lagos", 6.5, 3.4), ("Sapporo", 43.1, 141.3)]


def _mask(scale):
    bits = zlib.decompress(open(os.path.join(HERE, "world_land.bin"), "rb").read())
    full = bytearray(W0 * H0)
    for i in range(W0 * H0):
        if bits[i >> 3] >> (i & 7) & 1: full[i] = 1
    if scale >= 1.0: return W0, H0, full
    k = int(round(1.0 / scale)); w, h = W0 // k, H0 // k; m = bytearray(w * h)
    for y in range(h):
        for x in range(w):
            if sum(full[(y * k + j) * W0 + x * k + i] for j in range(k) for i in range(k)) * 2 >= k * k: m[y * w + x] = 1
    return w, h, m


def _geography(scale):
    """Seed-independent part: cells, provinces (key point, terrain, height, biome), land and sea links."""
    f = os.path.join(tempfile.gettempdir(), "ridgeline_world_v%d_%s.pickle" % (VERSION, scale))
    if os.path.exists(f):
        try: return pickle.load(open(f, "rb"))
        except Exception: pass
    gw, gh, land = _mask(scale); rng = random.Random(20261114); deg = 360.0 / gw      # degrees per cell
    sp = D.SPAN                                                                      # seed spacing = key-point spacing the rules assume
    owner = [-1] * (gw * gh); seeds = []
    y = sp / 2
    while y < gh:
        lat = LAT_N - y * deg; stretch = 1.0 / max(0.45, math.cos(math.radians(lat))) ** 0.8     # fewer provinces where the projection inflates the land
        x = rng.random() * sp
        while x < gw:
            sx = int(x + rng.uniform(-0.3, 0.3) * sp) % gw; sy = min(gh - 1, max(0, int(y + rng.uniform(-0.3, 0.3) * sp)))
            if land[sy * gw + sx] and owner[sy * gw + sx] < 0: owner[sy * gw + sx] = len(seeds); seeds.append((sx, sy))
            x += sp * stretch
        y += sp

    def grow(start):
        heap = [(0.0, i, x, y) for i, x, y in start]; heapq.heapify(heap); dist = {}
        for i, x, y in start: dist[y * gw + x] = 0.0; owner[y * gw + x] = i
        while heap:
            d, i, x, y = heapq.heappop(heap)
            if dist.get(y * gw + x, 1e9) < d: continue
            for dx, dy, c in ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, 1.414), (1, -1, 1.414), (-1, 1, 1.414), (-1, -1, 1.414)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < gw and 0 <= ny < gh): continue
                k = ny * gw + nx
                if not land[k]: continue
                if dx and dy and not (land[y * gw + nx] and land[ny * gw + x]): continue       # no squeezing diagonally between two water cells
                nd = d + c
                if nd < dist.get(k, 1e9) and (owner[k] < 0 or k in dist): dist[k] = nd; owner[k] = i; heapq.heappush(heap, (nd, i, nx, ny))
    grow([(i, x, y) for i, (x, y) in enumerate(seeds)])
    # land the seeds never reached (islands, peninsulas behind a one-cell neck): seed it too, or sink it if tiny
    for k0 in range(gw * gh):
        if not land[k0] or owner[k0] >= 0: continue
        comp = [k0]; owner[k0] = -2; i = 0
        while i < len(comp):
            k = comp[i]; i += 1; x, y = k % gw, k // gw
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < gw and 0 <= ny < gh and land[ny * gw + nx] and owner[ny * gw + nx] == -1: owner[ny * gw + nx] = -2; comp.append(ny * gw + nx)
        if len(comp) < 5:
            for k in comp: land[k] = 0; owner[k] = -1
            continue
        for k in comp: owner[k] = -1
        new = []
        for j in range(len(comp) // 40 + 1):
            k = comp[min(len(comp) - 1, j * 40 + 12)]; new.append((len(seeds), k % gw, k // gw)); seeds.append((k % gw, k // gw))
        grow(new)
    n = len(seeds) + 1                                   # province 0 is all water
    cell = [0] * (gw * gh); sx = [0.0] * n; sy = [0.0] * n; cnt = [0] * n
    for k in range(gw * gh):
        if land[k] and owner[k] >= 0:
            i = owner[k] + 1; cell[k] = i; sx[i] += k % gw + 0.5; sy[i] += k // gw + 0.5; cnt[i] += 1
    key = [None] * n; bestd = [1e18] * n
    for i in range(1, n):
        if cnt[i]: sx[i] /= cnt[i]; sy[i] /= cnt[i]
    for k in range(gw * gh):                             # key point: the province's own cell nearest its centre (never in the water)
        i = cell[k]
        if i:
            d = (k % gw + 0.5 - sx[i]) ** 2 + (k // gw + 0.5 - sy[i]) ** 2
            if d < bestd[i]: bestd[i] = d; key[i] = (k % gw + 0.5, k // gw + 0.5)
    adj = [set() for _ in range(n)]
    for y in range(gh):
        for x in range(gw):
            a = cell[y * gw + x]
            if not a: continue
            if x + 1 < gw:
                b = cell[y * gw + x + 1]
                if b and a != b: adj[a].add(b); adj[b].add(a)
            if y + 1 < gh:
                b = cell[(y + 1) * gw + x]
                if b and a != b: adj[a].add(b); adj[b].add(a)
    live = [i for i in range(1, n) if cnt[i]]
    # --- sea links. 1) straits: provinces close across water that are far apart (or unconnected) over land
    sea = [set() for _ in range(n)]; B = 12.0; bk = {}
    for i in live: bk.setdefault((int(key[i][0] / B), int(key[i][1] / B)), []).append(i)

    def near_land(a, lim):
        seen = {a}; q = [(a, 0)]; j = 0
        while j < len(q):
            c, d = q[j]; j += 1
            if d < lim:
                for b in adj[c] | sea[c]:
                    if b not in seen: seen.add(b); q.append((b, d + 1))
        return seen
    cand = []
    for a in live:
        ax, ay = key[a]
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for b in bk.get((int(ax / B) + dx, int(ay / B) + dy), ()):
                    if b > a:
                        d = (key[b][0] - ax) ** 2 + (key[b][1] - ay) ** 2
                        if d < (2.1 * sp) ** 2 and b not in adj[a]: cand.append((d, a, b))
    for d, a, b in sorted(cand):
        if b not in near_land(a, 5): sea[a].add(b); sea[b].add(a)
    # 2) sea lanes: join every remaining land mass to its nearest neighbour, nearest first (islands too far out are sunk)
    comp = {}
    def components():
        comp.clear(); out = []
        for s in live:
            if s in comp: continue
            c = [s]; comp[s] = len(out); j = 0
            while j < len(c):
                for b in adj[c[j]] | sea[c[j]]:
                    if b not in comp: comp[b] = len(out); c.append(b)
                j += 1
            out.append(c)
        return out
    dead = set()
    while True:
        cs = [c for c in components() if c[0] not in dead]
        if len(cs) <= 1: break
        c = min(cs, key=len); best = None
        for a in c:
            ax, ay = key[a]
            for b in live:
                if comp[b] != comp[a] and b not in dead:
                    d = (key[b][0] - ax) ** 2 + (key[b][1] - ay) ** 2
                    if best is None or d < best[0]: best = (d, a, b)
        if best[0] > (75.0 * scale) ** 2 and len(c) < 4: dead.update(c); continue      # a speck in mid-ocean
        sea[best[1]].add(best[2]); sea[best[2]].add(best[1])
    for i in dead:
        cnt[i] = 0
    for k in range(gw * gh):
        if cell[k] in dead: cell[k] = 0
    # --- terrain from real geography
    def xy(lat, lon): return (lon + 180.0) / deg, (LAT_N - lat) / deg
    segs = []
    for wt, wd, pts in RANGES:
        for (la0, lo0), (la1, lo1) in zip(pts, pts[1:]): segs.append(xy(la0, lo0) + xy(la1, lo1) + (wt, wd / deg))
    bumps = [(rng.random() * gw, rng.random() * gh, rng.choice((0.55, 0.65, 0.75)), rng.uniform(5, 11) * scale + 2) for _ in range(int(170 * max(1.0, scale * 1.0)))]
    terr = {}
    for i in live:
        if not cnt[i]: continue
        px, py = key[i]; lat = LAT_N - py * deg; lon = px * deg - 180.0; h = rng.uniform(-0.15, 0.15)
        for x0, y0, x1, y1, wt, w in segs:
            if min(x0, x1) - 3 * w < px < max(x0, x1) + 3 * w and min(y0, y1) - 3 * w < py < max(y0, y1) + 3 * w:
                dx, dy = x1 - x0, y1 - y0; t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / (dx * dx + dy * dy + 1e-9)))
                h += wt * math.exp(-((px - x0 - t * dx) ** 2 + (py - y0 - t * dy) ** 2) / (2 * w * w))
        for bx, by, s, r in bumps:
            d2 = (px - bx) ** 2 + (py - by) ** 2
            if d2 < 9 * r * r: h += s * math.exp(-d2 / (2 * r * r))
        inside = lambda box: ((lat - box[0]) / box[2]) ** 2 + ((lon - box[1]) / box[3]) ** 2 < 1.0
        biome = "desert" if any(inside(b) for b in DESERTS) else "tundra" if lat > 64 or (lat > 59 and -74 < lon < -11 and lon < -20 + (lat - 59) * 3) else ""
        if h > 0.95: t = "mountain"
        elif h > 0.5: t = "hill"
        else:
            pf = 0.0 if biome == "desert" else 0.65 if any(inside(b) for b in JUNGLE) else 0.55 if 50 < lat <= 66 else 0.3 if biome else 0.18
            t = "forest" if rng.random() < pf else "plain"
        terr[i] = (t, 3 if t == "mountain" else 2 if t == "hill" else 1 if h > 0.12 else 0, biome, round(lat, 1), round(lon, 1))
    geo = dict(gw=gw, gh=gh, cell=cell, key=key, cnt=cnt, adj=[sorted(a) for a in adj], sea=[sorted(a) for a in sea], terr=terr, deg=deg)
    try: pickle.dump(geo, open(f, "wb"), 4)
    except Exception: pass
    return geo


def gen_world(seed=0, scale=1.0, factions=None):
    """World map for the factions named (default: all of data.WORLD, about 30). scale 0.5 gives a quarter of the provinces."""
    geo = _geography(scale); rng = random.Random(seed * 104729 + 7)
    names = list(factions) if factions else [w[0] for w in D.WORLD]
    m = Map(); m.gw, m.gh, m.seed, m.cell, m.world = geo["gw"], geo["gh"], seed, geo["cell"], True
    n = len(geo["key"]); m.provs = [Prov(i) for i in range(n)]; deg = geo["deg"]
    for p in m.provs:
        t = geo["terr"].get(p.id)
        if t is None or not geo["cnt"][p.id]:
            p.terrain = "water"; p.cost = 0; p.dfn = 0; continue
        p.terrain, p.elev, p.biome = t[0], t[1], t[2]; p.cx, p.cy = geo["key"][p.id]; p.cells = geo["cnt"][p.id]; p.lat = round(LAT_N - p.cy * deg, 1)
        tt = D.TERRAIN[p.terrain]; p.cost = tt["cost"] + (D.HARSH_COST if p.biome else 0); p.dfn = tt["dfn"]
        p.y = rng.randint(0, 1) if p.biome else rng.randint(*tt["y"]); p.mp = 0 if p.biome else rng.randint(*tt["mp"])
        p.sea = tuple(geo["sea"][p.id]); p.nbrs = sorted(set(geo["adj"][p.id]) | set(p.sea))
    land = [p.id for p in m.provs if p.terrain != "water"]

    def at(lat, lon):
        x, y = (lon + 180.0) / deg, (LAT_N - lat) / deg
        return min(land, key=lambda i: ((m.provs[i].cx - x) ** 2 + (m.provs[i].cy - y) ** 2, i))
    def city(i, name=""):
        p = m.provs[i]
        if p.city: return
        p.city = True; p.y += D.CITY_YIELD; p.mp += D.CITY_MP; p.dfn += D.CITY_DFN; p.name = name
        if p.terrain == "mountain": p.terrain = "hill"; p.elev = 2; p.cost = D.TERRAIN["hill"]["cost"]; p.dfn = D.TERRAIN["hill"]["dfn"] + D.CITY_DFN
    world = {w[0]: w for w in D.WORLD}; caps = []
    for f in names:
        w = world[f]; c = at(w[2], w[3]); city(c, w[1]); caps.append(c)
    for nm, la, lo in CITIES: city(at(la, lo), nm)
    cities = [p.id for p in m.provs if p.city]
    cand = [i for i in land if m.provs[i].terrain != "mountain" and not (m.provs[i].biome and rng.random() < 0.8)]; rng.shuffle(cand)
    for i in cand:
        if len(cities) >= len(land) // 9: break
        if all(i not in m.provs[c].nbrs for c in cities[-400:]) and not m.provs[i].city and not any(m.provs[b].city for b in m.provs[i].nbrs):
            city(i); cities.append(i)
    hubs = [i for i in land if not m.provs[i].city]; rng.shuffle(hubs)
    for i in hubs[:len(land) // 12]: m.provs[i].y += rng.randint(3, 6)
    # v8: strategic resources lie where they lie on the real earth: thick inside the historical fields, a thin scatter elsewhere
    dr = random.Random(seed * 7 + 3)
    for kind, fields in FIELDS.items():
        share, lo, hi = D.DEPOSIT[kind]
        for i in land:
            p = m.provs[i]; lat = LAT_N - p.cy * deg; lon = p.cx * deg - 180.0; best = 0.0
            for la, lo_, r in fields:
                d = math.hypot(lat - la, (lon - lo_) * math.cos(math.radians(la))) / r
                if d < 1.0: best = max(best, 0.55 * (1.0 - 0.6 * d))
            if dr.random() < max(best, share * 0.12): setattr(p, kind, dr.randint(lo, hi))
    # asymmetric start: every faction gets the land nearest its capital (random size), an army and a treasury of random size
    m.capitals = caps; m.scale = 4.0 * scale; m.names = names
    claim = {}; q = []
    for pid, c in enumerate(caps): claim[c] = (0, pid); q.append(c)
    size = [int(rng.randint(22, 60) * max(0.3, scale ** 1.5)) for _ in caps]; got = [[] for _ in caps]; j = 0
    while j < len(q):                                   # simultaneous flood from all capitals, each stops at its own size
        a = q[j]; j += 1; d, pid = claim[a]
        if len(got[pid]) > size[pid]: continue
        got[pid].append(a)
        for b in m.provs[a].nbrs:
            if b not in claim and b not in m.provs[a].sea: claim[b] = (d + 1, pid); q.append(b)
    kinds = ("inf", "inf", "inf", "inf", "mil", "mil", "mtn", "mot", "arm", "art", "art", "eng", "rec")
    for pid in range(len(caps)):
        mine = got[pid]; m.start_provs.append(mine)
        k = int(rng.randint(400, 900) * max(0.2, scale ** 1.5))
        army = ["inf"] * (k // 4) + [rng.choice(kinds) for _ in range(k - k // 4)]
        m.start_units.append([(t, rng.choice(mine)) for t in army])
        m.start_res.append(int(rng.randint(300, 900))); m.start_mp.append(int(rng.randint(500, 1500)))
    start_bank(m, random.Random(seed * 11 + 5), 3.0)
    return m
