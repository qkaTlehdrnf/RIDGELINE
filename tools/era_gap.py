"""How much an age is worth in a fight: the same assault (attackers of one age against defenders of another).

  python tools/era_gap.py
"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ridgeline import ages as A
from ridgeline import engine as E
import tools.scenario as S


def game(ea, ed):
    real = E.small_game
    def make(seed):
        g = real(seed)
        for pid, e in ((0, ea), (1, ed)):
            p = g.players[pid]; st = {}
            for c, s in p.stats.items():
                s = dict(s); s["atk"] = round(s["atk"] * A.POW[e], 2); s["dfn"] = round(s["dfn"] * A.POW[e], 2); s["range"] = round(max(1.5, s["range"] * A.RNG[e]), 2); st[c] = s
            p.stats = st
        return g
    return make


def main():
    print("attacker age (30 inf) vs defender age (30 inf), plain, fort 1: took / hours / attacker strength lost / defender strength left")
    for ea, ed, na in ((0, 0, 30), (0, 0, 90), (2, 0, 30), (3, 0, 30), (5, 0, 30), (5, 0, 5), (6, 0, 3), (0, 5, 30), (0, 5, 300), (5, 5, 30), (5, 5, 90), (5, 3, 30), (6, 5, 30)):
        S.small_game = game(ea, ed)
        r = S.run({"inf": na}, {"inf": 30}, fort=1, prep=50, hours=300)
        print("%-10s x%-3d vs %-10s x30: %s" % (A.ERAS[ea], na, A.ERAS[ed], " ".join(str(round(x)) if not isinstance(x, bool) else str(x) for x in r)))


if __name__ == "__main__": main()
