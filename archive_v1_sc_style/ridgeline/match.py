"""Lockstep runner: fast, deterministic matches between in-process agents (no HTTP, no wall clock)."""
import json

from .engine import Game
from .iface import Session


def run_match(make_a, make_b, factions=("aurum", "sable"), seed=0, interval=10, max_ticks=18000, replay=None,
              replay_every=10, on_tick=None):
    """make_a/make_b: callables Session -> agent with .step(). Returns result dict."""
    g = Game(factions=factions, seed=seed, max_ticks=max_ticks)
    sess = [Session(g, 0), Session(g, 1)]
    agents = [make_a(sess[0]), make_b(sess[1])]
    frames = []
    while not g.over:
        if g.tick % interval == 0:
            for a in agents: a.step()
        for s in sess: s.pre_tick()
        g.step()
        if replay and g.tick % replay_every == 0: frames.append(g.snapshot())
        if on_tick: on_tick(g, sess)
    res = dict(winner=g.winner, ticks=g.tick, score=[round(g.score(0)), round(g.score(1))],
               killed=[p.killed_value for p in g.players], mined=[p.mined for p in g.players], factions=list(factions))
    if replay:
        with open(replay, "w") as f:
            json.dump(dict(map=map_json(g), frames=frames, result=res), f, separators=(",", ":"))
    return res


def map_json(g):
    return dict(w=g.W, h=g.H, level=g.level, ramp=[int(x) for x in g.ramp], brush=[int(x) for x in g.brush],
                block=[int(x) for x in g.map.block], factions=[p.faction for p in g.players])


if __name__ == "__main__":
    import sys, time
    sys.path.insert(0, ".")
    from bots.basic import Bot
    t = time.time()
    r = run_match(lambda s: Bot(s), lambda s: Bot(s), replay=sys.argv[1] if len(sys.argv) > 1 else None)
    print(r, "%.1fs" % (time.time() - t))
