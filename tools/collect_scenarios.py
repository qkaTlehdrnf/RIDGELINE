"""Randomised assault experiments as training data: forces, terrain, forts, readiness and planning time are drawn
at random, so the model sees what preparation does on its own (game logs alone only show what the current
policy happened to try).

  python tools/collect_scenarios.py runs/battles.jsonl 600
"""
import json, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scenario import run

out = sys.argv[1]; n = int(sys.argv[2]) if len(sys.argv) > 2 else 400
rng = random.Random(7); won = tot = 0
with open(out, "a", encoding="utf-8") as f:
    for i in range(n):
        nd = rng.randint(1, 10); ratio = rng.choice((0.7, 1.0, 1.5, 2.0, 3.0, 4.0)); na = max(1, round(nd * ratio))
        att = {}; dfd = {}
        for _ in range(na): t = rng.choice(("inf",) * 5 + ("art", "art", "arm", "eng", "mot", "mtn")); att[t] = att.get(t, 0) + 1
        for _ in range(nd): t = rng.choice(("inf",) * 5 + ("mil", "mil", "art", "eng")); dfd[t] = dfd.get(t, 0) + 1
        log = []
        run(att, dfd, fort=rng.randint(0, 3), terrain=rng.choice(("plain", "plain", "forest", "hill", "mountain")),
            rdy=rng.choice((20, 40, 60, 80, 100)), prep=rng.choice((0, 0, 24, 48, 72)), stock=rng.choice((40, 150, 400)),
            hours=200, seed=rng.randint(0, 5), dirs=rng.randint(1, 3), log=log)
        for b in log: f.write(json.dumps(b) + "\n"); tot += 1; won += b["won"]
print("scenario assaults %d, won %d" % (tot, won))
