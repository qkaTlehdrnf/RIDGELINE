"""Controlled check of the river rule: the same attack across a river border and across an ordinary border.
  python tools/river_test.py"""
import sys; sys.path.insert(0, ".")
from ridgeline.engine import Game

def run(a, b, na, nd, seed):
    g = Game("world", seed); A, B = 0, 1
    for u in list(g.units.values()): g._die(u, None)
    for p in g.players: p.res = 1e6
    for q in set([a, b]) | set(g.provs[a].nbrs) | set(g.provs[b].nbrs): g._set_owner(q, -1)
    g._set_owner(a, A); g._set_owner(b, B); g.players[A].capital = a; g.players[B].capital = b
    g.players[A].depots = {a: 1.0}; g.players[B].depots = {b: 1.0}
    g._supply()
    ids = [g.spawn(A, "inf", a).id for _ in range(na)]; [g.spawn(B, "inf", b) for _ in range(nd)]
    for u in g.units.values(): u.rdy = 80.0; u.supplied = True
    g.order_move(A, ids, b); t0 = g.tick
    for _ in range(240):
        g._hourly(); g._combat(); g._move(); g._capture(); g.tick += 1
        if g.owner[b] == A: return g.tick - t0, sum(1 for u in g.units.values() if u.owner == A)
    return None, sum(1 for u in g.units.values() if u.owner == A)

g = Game("world", 1); P = g.provs
ok = lambda p: p.terrain == "plain" and not p.biome and not p.city and abs(p.lat) < 35
riv = [(p.id, q) for p in P if ok(p) for q in p.river if ok(P[q])][:12]
dry = [(p.id, q) for p in P if ok(p) and not p.river for q in p.nbrs if ok(P[q]) and q not in p.sea and not P[q].river][:12]
for name, es in (("river", riv), ("no river", dry)):
    for na in (6, 9, 12):
        r = [run(a, b, na, 3, 1) for a, b in es]; w = [x for x in r if x[0] is not None]
        print("%-9s %2d inf vs 3: won %d/%d, mean hours %s, attackers left %.1f" % (name, na, len(w), len(r), round(sum(x[0] for x in w) / len(w)) if w else "-", sum(x[1] for x in r) / len(r)))
