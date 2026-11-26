"""Compare observation encodings over one policy-vs-policy game.  python tools/bench_tokens.py [seed] [interval_ticks]

Token counts are estimates (no tokenizer bundled): 1 token per 4 letters, per 3 digits, per punctuation mark.
The same estimator is applied to every format, so the ratios are what matter.
"""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ridgeline.engine import Game
from ridgeline.iface import Session
from ridgeline.match import BASIC

PIECE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


def est_tokens(s):
    return sum((len(m) + 3) // 4 if m[0].isalpha() else (len(m) + 2) // 3 if m[0].isdigit() else 1 for m in PIECE.findall(s))


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    interval = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 1200
    g = Game(seed=seed); sess = [Session(g, i) for i in range(len(g.players))]
    for s in sess: s.set_policy("main", open(BASIC).read())
    watch = Session(g, 0); rows = []
    while not g.over and g.tick < limit:
        for s in sess: s.pre_tick()
        g.step()
        if g.tick % interval == 0:
            j = json.dumps(watch.obs_json(), separators=(",", ":"))
            ev = watch._ev; full = watch.obs("full"); watch._ev = ev      # full is measured without consuming events
            watch._last = watch._prev if hasattr(watch, "_prev") else {}
            delta = watch.obs("delta"); watch._prev = watch._last
            rows.append((g.tick, sum(1 for u in g.units.values() if u.owner == 0), g.owner.count(0),
                         est_tokens(j), est_tokens(full), est_tokens(delta), delta.count("\n") == 0))
    print("seed %d: %d ticks, winner P%s, one observation every %d ticks (%d observations)" % (seed, g.tick, g.winner, interval, len(rows)))
    print("brief (sent once, cacheable): ~%d tokens" % est_tokens(watch.brief()))
    print("%-6s %-6s %-6s %10s %10s %10s" % ("tick", "units", "provs", "json_full", "text_full", "text_delta"))
    for r in rows[::max(1, len(rows) // 10)]: print("%-6d %-6d %-6d %10d %10d %10d" % r[:6])
    tot = [sum(r[i] for r in rows) for i in (3, 4, 5)]; n = len(rows)
    print("mean   %13s %10d %10d %10d" % ("", tot[0] // n, tot[1] // n, tot[2] // n))
    print("max    %13s %10d %10d %10d" % ("", max(r[3] for r in rows), max(r[4] for r in rows), max(r[5] for r in rows)))
    print("quiet turns (header only, model call can be skipped): %d of %d" % (sum(1 for r in rows if r[6]), n))
    print("text_full is %.0fx smaller than json_full; text_delta is %.0fx smaller" % (tot[0] / tot[1], tot[0] / tot[2]))


if __name__ == "__main__":
    main()
