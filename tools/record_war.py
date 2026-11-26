"""Play one war with the factions' policies (no model calls) and record it twice over:
  <out>.rlr   the full replay for the WebGL viewer and tools/make_video.mjs (written by tools/record_replay.py's Recorder)
  <out>.json  a small side file for the phone page (tools/make_mobile.py): depots, pacts and real attacks over time

  python tools/record_war.py --seed 1 --hours 2400 --pol-dir runs/league_world [--gen N] --out runs/replays/war
--gen N: use each faction's genN.py (or its newest one below N) instead of the newest.
"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
from ridgeline import data as D
from ridgeline.engine import Game
from ridgeline.iface import Session
from record_replay import Recorder as _Recorder


class Recorder(_Recorder):
    """The replay format stores who fires at whom as 16-bit unit indexes. In a very long war the unit count can pass
    65,535; shots that involve a unit beyond that index are left out of the replay (the units themselves are all kept)."""
    def _shots(self, units, pos):
        return [(a, b) for a, b in _Recorder._shots(self, units, pos) if a < 65536 and b < 65536]


def main():
    a = sys.argv[1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    seed = int(opt("--seed", 1)); hours = int(opt("--hours", 2400)); out = opt("--out", "runs/replays/war"); pol = opt("--pol-dir", "runs/league_world"); top = int(opt("--gen", 10 ** 6)); every = int(opt("--every", 1))
    from ridgeline.worldgen import gen_world
    factions = tuple(w[0] for w in D.WORLD); g = Game(factions=factions, seed=seed, gmap=gen_world(seed, scale=1.0), max_ticks=hours); n = len(g.players)
    sess = [Session(g, i) for i in range(n)]; bm = os.path.join(ROOT, "policies", "model.json"); used = []
    for s in sess:
        d = os.path.join(pol, g.players[s.pid].faction)
        gens = sorted(int(x[3:-3]) for x in os.listdir(d) if x.startswith("gen") and x.endswith(".py") and x[3:-3].isdigit() and int(x[3:-3]) <= top) if os.path.isdir(d) else []
        f = os.path.join(d, "gen%d.py" % gens[-1]) if gens else os.path.join(ROOT, "policies", "basic.py"); used.append(gens[-1] if gens else -1); s.set_policy("main", open(f, encoding="utf-8").read())
        if os.path.exists(bm): s.model = json.load(open(bm))
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    rec = Recorder(g, out + ".rlr"); rec.frame(); t0 = time.time(); side = []; seen = 0
    def snap():
        nonlocal seen
        new = g.battle_log[seen:]; seen = len(g.battle_log)
        side.append(dict(t=g.tick, depots=[{str(d): round(v, 2) for d, v in p.depots.items()} if p.alive else {} for p in g.players],
                         building=[sorted(p.depot_build) for p in g.players], pacts=len(g.pacts),
                         dev=[round(sum(g.dev[i] for i in g.owned[p.id]), 1) for p in g.players], infra=[round(sum(g.infra[i] for i in g.owned[p.id]), 1) for p in g.players],
                         income=[round(p.income) for p in g.players], access=len(g.access) // 2, deals=len(g.deals), allies=len(g.allies) // 2,
                         attacks=sum(1 for b in new if b.get("aimed", 1) > 0), won=sum(1 for b in new if b.get("aimed", 1) > 0 and b.get("won"))))
    snap()
    while not g.over:
        for s in sess: s.pre_tick()
        g.step()
        if g.tick % every == 0: rec.frame()
        if g.tick % 12 == 0: snap()
        if g.tick % 200 == 0: print("t%d units %d %.0fs" % (g.tick, len(g.units), time.time() - t0), flush=True)
    dump = lambda res: json.dump(dict(result=res, gens=used, side=side, falls=sorted(set((t, x) for p in g.players for t, k, x in p.events if k == "fall")),
                                      depot_events=[(t, p.faction, x) for p in g.players for t, k, x in p.events if k == "depot"]), open(out + ".json", "w"))
    res = dict(seed=seed, winner=g.winner, ticks=g.tick, provinces=[len(g.owned[i]) for i in range(n)], alive=[p.alive for p in g.players])
    rec.close(res)
    dump(res)
    print("wrote", out + ".rlr", out + ".json", res)


if __name__ == "__main__":
    main()
