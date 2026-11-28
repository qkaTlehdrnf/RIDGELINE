"""Time a world war and fingerprint its state, to compare engines (and engine changes) on the same seed.

  python tools/bench_war.py --hours 600 [--seed 1] [--engine cpu|torch] [--pol-dir runs/league_world] [--root <another checkout>]

Every --every hours it prints the hour, units, seconds per hour (engine step / agents) and a hash of every unit's exact
state, every province owner and every player's purse. Two runs with the same hashes played the same war bit for bit.
"""
import hashlib, json, os, sys, time

a = sys.argv[1:]
opt = lambda k, d: a[a.index(k) + 1] if k in a else d
ROOT = os.path.abspath(opt("--root", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")))
sys.path.insert(0, ROOT)
from ridgeline import data as D
from ridgeline.engine import Game
from ridgeline.iface import Session
from ridgeline.worldgen import gen_world

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def fingerprint(g):
    h = hashlib.sha1()
    for i in sorted(g.units):
        u = g.units[i]
        h.update(repr((i, u.owner, u.type, u.prov, u.str, u.rdy, u.mor, u.xp, u.sup, u.x, u.y, u.fighting, u.contact, u.path, u.plan_t, u.plan_b, u.rout, u.dry, u.supplied)).encode())
    h.update(repr(g.owner).encode()); h.update(repr([(p.res, p.mp, p.kills, p.losses) for p in g.players]).encode()); h.update(repr(g.fort).encode())
    return h.hexdigest()[:12]


def main():
    seed = int(opt("--seed", 1)); hours = int(opt("--hours", 600)); every = int(opt("--every", 100)); pol = opt("--pol-dir", os.path.join(HERE, "runs", "league_world"))
    f = tuple(w[0] for w in D.WORLD); g = Game(factions=f, seed=seed, gmap=gen_world(seed, scale=1.0), max_ticks=9216)
    if opt("--engine", "cpu") == "torch":
        from ridgeline import tcore
        tcore.enable(g, opt("--device", None))
    sess = [Session(g, i) for i in range(len(f))]
    for s in sess:
        d = os.path.join(pol, g.players[s.pid].faction)
        gens = sorted(int(x[3:-3]) for x in os.listdir(d) if x.startswith("gen") and x.endswith(".py") and x[3:-3].isdigit())
        s.set_policy("main", open(os.path.join(d, "gen%d.py" % gens[-1]), encoding="utf-8").read()); s.model = json.load(open(os.path.join(HERE, "policies", "model.json")))
    te = ta = 0.0; t0 = time.time()
    for h in range(1, hours + 1):
        t = time.time()
        for s in sess: s.pre_tick(); s.call_req = None
        t1 = time.time(); g.step(); t2 = time.time(); ta += t1 - t; te += t2 - t1
        if h % every == 0:
            print("h%d units %d engine %.3fs/h agents %.3fs/h total %.0fs %s" % (h, len(g.units), te / h, ta / h, time.time() - t0, fingerprint(g)), getattr(g, "_tc", {}).get("stats", ""), flush=True)


if __name__ == "__main__":
    main()
