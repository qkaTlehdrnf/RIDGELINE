"""Compare observation encodings over a full bot-vs-bot game.

  python tools/bench_tokens.py [interval_ticks]

Token counts are estimates (no tokenizer is bundled): words ~ 1 token per 4 letters, each digit group
~ 1 token per 3 digits, every punctuation mark 1 token. The same estimator is applied to every format,
so the ratios are meaningful even if absolute numbers are off by 10-20%.
"""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ridgeline.engine import Game
from ridgeline.iface import Session
from bots.basic import Bot

PIECE = re.compile(r"[A-Za-z]+|\d+|[^\sA-Za-z\d]")


def est_tokens(s):
    n = 0
    for m in PIECE.findall(s):
        if m[0].isalpha(): n += (len(m) + 3) // 4
        elif m[0].isdigit(): n += (len(m) + 2) // 3
        else: n += 1
    return n


def main():
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    g = Game(); sess = [Session(g, 0), Session(g, 1)]; bots = [Bot(s) for s in sess]
    watch = Session(g, 0)        # a separate observer session on P0 so the bot's own calls don't disturb deltas
    rows = []
    while not g.over:
        if g.tick % 10 == 0:
            for b in bots: b.step()
        for s in sess: s.pre_tick()
        g.step()
        if g.tick % interval == 0:
            j = json.dumps(watch.obs_json(), separators=(",", ":"))
            watch._last = dict(watch._last); ev = watch._ev
            full = watch.obs("full"); watch._ev = ev
            delta = watch.obs("delta")
            n_own = sum(1 for e in g.ents.values() if e.owner == 0)
            rows.append((g.tick, n_own, len(g.players[0].vis_ents), est_tokens(j), est_tokens(full), est_tokens(delta)))
    brief = est_tokens(watch.brief())
    print("game: %d ticks, winner P%s, decision every %d ticks (%d decisions)" % (g.tick, g.winner, interval, len(rows)))
    print("brief (sent once, cacheable): ~%d tokens" % brief)
    print("%-6s %-5s %-5s %10s %10s %10s" % ("tick", "own", "seen", "json_full", "text_full", "text_delta"))
    step = max(1, len(rows) // 12)
    for r in rows[::step]: print("%-6d %-5d %-5d %10d %10d %10d" % r)
    tot = [sum(r[i] for r in rows) for i in (3, 4, 5)]
    mx = [max(r[i] for r in rows) for i in (3, 4, 5)]
    print("mean   %21s %10d %10d %10d" % ("", tot[0] // len(rows), tot[1] // len(rows), tot[2] // len(rows)))
    print("max    %21s %10d %10d %10d" % ("", mx[0], mx[1], mx[2]))
    print("total  %21s %10d %10d %10d" % ("", tot[0], tot[1], tot[2]))
    print("text_full is %.1fx smaller than json_full; text_delta is %.1fx smaller than json_full" % (tot[0] / tot[1], tot[0] / tot[2]))


if __name__ == "__main__":
    main()
