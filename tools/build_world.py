"""Build ridgeline/world_land.bin from Natural Earth (public domain) land and lake polygons.

    python3 tools/build_world.py ne_50m_land.geojson ne_110m_lakes.geojson

The output is a zlib-compressed bit mask, W x H cells, equirectangular, longitude -180..180, latitude LAT_N..LAT_S
(see ridgeline/worldgen.py). The game itself never needs the source files or the network.
"""
import json, os, sys, zlib

W, H = 1152, 420; LAT_N, LAT_S = 75.0, -56.25


def rings(path):
    for f in json.load(open(path))["features"]:
        g = f["geometry"]; polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys: yield poly


def fill(mask, poly, val):
    """Even-odd scanline fill of one polygon (outer ring + holes) at cell centres."""
    edges = []
    for ring in poly:
        pts = [((lon + 180.0) / 360.0 * W, (LAT_N - lat) / (LAT_N - LAT_S) * H) for lon, lat in ring]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if y0 != y1: edges.append((x0, y0, x1, y1) if y0 < y1 else (x1, y1, x0, y0))
    if not edges: return
    ya = max(0, int(min(e[1] for e in edges))); yb = min(H - 1, int(max(e[3] for e in edges)))
    for y in range(ya, yb + 1):
        yc = y + 0.5; xs = sorted(x0 + (yc - y0) / (y1 - y0) * (x1 - x0) for x0, y0, x1, y1 in edges if y0 <= yc < y1)
        for a, b in zip(xs[::2], xs[1::2]):
            for x in range(max(0, int(a + 0.5)), min(W, int(b + 0.5))): mask[y * W + x] = val


mask = bytearray(W * H)
for poly in rings(sys.argv[1]): fill(mask, poly, 1)
if len(sys.argv) > 2:
    for poly in rings(sys.argv[2]): fill(mask, poly, 0)
bits = bytearray((W * H + 7) // 8)
for i, v in enumerate(mask):
    if v: bits[i >> 3] |= 1 << (i & 7)
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ridgeline", "world_land.bin")
open(out, "wb").write(zlib.compress(bytes(bits), 9))
print("land cells", sum(mask), "of", W * H, "->", os.path.getsize(out), "bytes")
for y in range(0, H, 10): print("".join("#" if mask[y * W + x] else "." for x in range(0, W, 8)))
