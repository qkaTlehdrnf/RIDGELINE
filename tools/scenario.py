"""Controlled assault experiments: one attacked province, fixed forces, vary preparation.

  python tools/scenario.py            # prints a table; edit CASES below or import run()
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ridgeline.engine import Game, small_game

DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}


def run(att, dfd, fort=2, terrain="plain", rdy=100, prep=0, stock=400, hours=300, seed=3, dirs=1, log=None):
    """att/dfd: {type: n}. dirs: attack from this many neighbouring provinces. Returns (took, hours, attacker
    strength lost, defender strength left)."""
    g = small_game(seed)
    for u in list(g.units.values()): g._die(u, None)
    # a target with at least `dirs` neighbours; everything flat so only the chosen terrain matters
    b = next(p.id for p in g.provs if p.terrain != "water" and sum(1 for n in p.nbrs if g.provs[n].terrain != "water") >= dirs + 1)
    nb = [n for n in g.provs[b].nbrs if g.provs[n].terrain != "water"]
    src = nb[:dirs]; back = nb[dirs]
    g.provs[b].terrain = terrain; g.provs[b].dfn = DFN[terrain]
    for i in src + [back]: g.provs[i].elev = g.provs[b].elev
    for p in g.players: p.mp = 1e6
    g.players[0].capital = src[0]; g.players[1].capital = back
    for i in range(g.n): g.owner[i] = -1
    for i in src: g.owner[i] = 0
    g.owner[b] = 1; g.owner[back] = 1; g._own_dirty = True
    g.fort[b] = float(fort)
    for i in src + [b, back]: g.stock[i] = stock
    D = [g.spawn(1, t, b) for t, n in dfd.items() for _ in range(n)]
    A = []
    for t, n in att.items():
        for k in range(n): A.append(g.spawn(0, t, src[k % dirs]))
    for u in A: u.rdy = rdy
    for u in D: u.rdy = 80
    ids = [u.id for u in A]; a0 = sum(u.str for u in A)
    for i in src:
        own = [u.id for u in A if u.prov == i]
        if prep and own: g.order_prepare(0, own, b)
    for _ in range(prep):
        g.step()
        for i in src: g.stock[i] = max(g.stock[i], stock)
    t0 = g.tick; g.order_move(0, ids, b)
    while g.tick - t0 < hours and g.owner[b] != 0 and any(u.path for u in A if u.id in g.units): g.step()
    left = sum(u.str for u in A if u.id in g.units)
    if log is not None:
        for _ in range(8): g.step()                  # let the episode close
        log.extend(dict(b, seed=-1) for b in g.battle_log)
    return (g.owner[b] == 0, g.tick - t0 + prep, round(max(0, a0 - left)), round(sum(u.str for u in D if u.id in g.units)))


CASES = [
    ("3:1 inf, light trench, plain", dict(att={"inf": 9}, dfd={"inf": 3}, fort=1, terrain="plain")),
    ("3:1 combined arms, trench line, plain", dict(att={"inf": 9, "art": 3, "arm": 3}, dfd={"inf": 5}, fort=2, terrain="plain")),
    ("2:1 inf, trench line, hill", dict(att={"inf": 10}, dfd={"inf": 5}, fort=2, terrain="hill")),
    ("dense front 1.5:1, fortress, hill", dict(att={"inf": 15, "art": 3}, dfd={"inf": 10, "art": 2}, fort=3, terrain="hill")),
    ("dense front, artillery mass, 2 directions", dict(att={"inf": 12, "art": 8, "arm": 4}, dfd={"inf": 10, "art": 2}, fort=3, terrain="hill", dirs=2)),
]

if __name__ == "__main__":
    for name, kw in CASES:
        print(name)
        for label, rdy, prep in (("worn, hasty", 30, 0), ("rested, hasty", 100, 0), ("rested, 48 h plan", 100, 48)):
            took, h, loss, left = run(rdy=rdy, prep=prep, **kw)
            print("   %-18s %s after %3d h, attacker lost %4d, defender left %4d" % (label, "TAKEN " if took else "failed", h, loss, left))
