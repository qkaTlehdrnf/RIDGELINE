"""How fronts behave in a recorded war: how often land changes hands, whether it changes back, and whether borders sit on rough ground.
  python tools/front_stats.py replay.rlr [seed]"""
import sys, json
sys.path.insert(0, "."); sys.path.insert(0, "tools")
from collections import Counter
import rlr_tools
from ridgeline.engine import Game

def main(path, seed=1):
    g = Game("world", seed); P = g.n; terr = [p.terrain for p in g.provs]; nb = [list(p.nbrs) for p in g.provs]
    snaps = {}; prev = None; flips = [0] * P; back = [0] * P; hist = [[] for _ in range(P)]; byq = Counter()
    for fr in rlr_tools.frames(path):
        t, prov = fr[0], fr[3]
        if t % 24: continue
        own = (prov[0] - 1).tolist()
        if prev is not None:
            for i in range(P):
                if own[i] != prev[i] and prev[i] >= 0 and own[i] >= 0:
                    flips[i] += 1; byq[t * 4 // 9217] += 1
                    if own[i] in hist[i]: back[i] += 1
                    hist[i].append(prev[i])
        prev = own
        if t % (24 * 96) == 0: snaps[t // 24] = own
    land = [i for i in range(P) if terr[i] != "water"]
    out = dict(changes_total=sum(flips), by_quarter=[byq[q] for q in range(4)], provinces_changed=sum(1 for i in land if flips[i]), provinces_changed_twice=sum(1 for i in land if flips[i] >= 2),
               returned_to_former_owner=sum(back), land=len(land))
    tc = Counter(terr[i] for i in land); fl = Counter(); 
    for i in land: fl[terr[i]] += flips[i]
    out["changes_per_100_provinces_by_terrain"] = {k: round(100 * fl[k] / tc[k], 1) for k in tc}
    def edges(own): return {(a, b) for a in land for b in nb[a] if a < b and own[a] >= 0 and own[b] >= 0 and own[a] != own[b]}
    alle = [(a, b) for a in land for b in nb[a] if a < b]
    rough = lambda e: terr[e[0]] in ("hill", "mountain") or terr[e[1]] in ("hill", "mountain")
    out["rough_share_all_edges"] = round(sum(map(rough, alle)) / len(alle), 3)
    riv = lambda e: e[1] in g.provs[e[0]].river
    out["river_share_all_edges"] = round(sum(map(riv, alle)) / len(alle), 3)
    E = {d: edges(o) for d, o in snaps.items()}
    out["borders"] = {d: dict(edges=len(e), rough_share=round(sum(map(rough, e)) / max(1, len(e)), 3), river_share=round(sum(map(riv, e)) / max(1, len(e)), 3)) for d, e in sorted(E.items())}
    ds = sorted(E)
    out["border_kept"] = {"%d->%d" % (a, b): round(len(E[a] & E[b]) / max(1, len(E[a])), 3) for a, b in zip(ds, ds[1:]) if E[a]}
    print(json.dumps(out, indent=1))
if __name__ == "__main__": main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 1)
