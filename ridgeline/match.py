"""Lockstep runner: fast deterministic matches (no wall clock). Each side = optional policy file + optional agent."""
import json
import os

from .engine import Game
from .mapgen import gen_map
from .iface import Session
from .render import frame, scene

HERE = os.path.dirname(os.path.abspath(__file__))
BASIC = os.path.join(HERE, "..", "policies", "basic.py")


def run_match(policies=None, agents=None, factions=("aurum", "sable", "cinder"), seed=0, interval=10,
              max_ticks=4800, replay=None, replay_every=24, models=None, battle_log=None, timeline=None, size=None, progress=None):
    """policies: python files with tick(api) (or None). agents: callables Session -> object with .step(), called
    every `interval` ticks (the '5 seconds' cadence at 2 ticks/s)."""
    n = 1 if isinstance(factions, str) else len(factions); policies = policies or (BASIC,) * n; agents = agents or (None,) * n; models = models or (None,) * n
    if size == "small": gmap = gen_map(seed, 126, 78, 22, 14, players=n)          # the old 300-province map
    elif size: gmap = gen_map(seed, *size, players=n)                              # (gw, gh, cols, rows)
    else: gmap = None
    g = Game(factions=factions, seed=seed, max_ticks=max_ticks, gmap=gmap)        # factions="world": the world map, about 30 factions
    n = len(g.players)
    if isinstance(policies, str): policies = (policies,) * n
    if len(policies) < n: policies = tuple(policies[i % len(policies)] for i in range(n))
    agents = tuple(agents) + (None,) * (n - len(agents)); models = tuple(models) + (None,) * (n - len(models)); big = len(g.units) > 6000
    sess = [Session(g, i) for i in range(n)]
    for s, f in zip(sess, policies):
        if f:
            r = s.set_policy("main", open(f, encoding="utf-8").read())
            if "installed" not in r: raise RuntimeError(r)
    for s, f in zip(sess, models):
        if f: s.model = json.load(open(f, encoding="utf-8"))
    ag = [mk(s) if mk else None for mk, s in zip(agents, sess)]
    tl = []
    frames = [frame(g, compact=True, stacks=not big)]
    while not g.over:
        if g.tick % interval == 0:
            for a in ag:
                if a: a.step()
        for s in sess: s.pre_tick()
        g.step()
        if replay and g.tick % replay_every == 0: frames.append(frame(g, compact=True, stacks=not big))
        if progress and g.tick % 100 == 0: progress(g)
        if g.tick % 120 == 0:
            tl.append(dict(t=g.tick, prov=[g.owner.count(i) for i in range(n)], units=[p.n_units for p in g.players],
                           income=[round(p.income - p.upkeep) for p in g.players], mp=[int(p.mp) for p in g.players],
                           kills=[p.kills for p in g.players], assaults=len(g.battles), contacts=len(g.contacts)))
    res = dict(seed=seed, winner=g.winner, ticks=g.tick, provinces=[g.owner.count(i) for i in range(n)], alive=[p.alive for p in g.players],
               units=[len(g.punits[i]) for i in range(n)], forts=sum(1 for i in range(g.n) if g.fort_level(i)),
               kills=[p.kills for p in g.players], start=dict(provs=[len(x) for x in g.map.start_provs],
                                                              units=[len(x) for x in g.map.start_units], res=g.map.start_res))
    res["policy_errors"] = [s.policies.get("main", {}).get("err") if "main" in s.policies else "removed (crash or time budget)" for s in sess]
    res["policy_ms"] = [round(s.policies["main"]["ms"] / max(1, s.policies["main"]["calls"]), 2) if "main" in s.policies else None for s in sess]
    if battle_log is not None: battle_log.extend(dict(b, seed=seed) for b in g.battle_log)
    if timeline is not None: timeline.extend(tl)
    if replay:
        with open(replay, "w") as f:
            json.dump(dict(scene=scene(g), frames=frames, result=res), f, separators=(",", ":"))
    return res


if __name__ == "__main__":
    import sys, time
    t = time.time(); seed = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    small = "--small" in sys.argv
    print(run_match(seed=seed, replay=sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None,
                    size="small" if small else None,
                    factions="world" if "--world" in sys.argv else ("aurum", "sable") if "--two" in sys.argv else ("aurum", "sable", "cinder")),
          "%.2fs" % (time.time() - t))
