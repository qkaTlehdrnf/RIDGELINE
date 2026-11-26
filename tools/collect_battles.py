"""Play policy-vs-policy games and append every assault episode to a JSONL file (the training data).

  python tools/collect_battles.py out.jsonl [seeds...] [--p0 policies/basic.py --p1 policies/immediate.py]
"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from ridgeline.match import run_match, BASIC

args = sys.argv[1:]; pol = [BASIC, BASIC]
for i, k in enumerate(("--p0", "--p1")):
    if k in args: j = args.index(k); pol[i] = args[j + 1]; del args[j:j + 2]
out = args[0]; seeds = [int(s) for s in args[1:]] or [0, 1, 2, 3]
with open(out, "a", encoding="utf-8") as f:
    for s in seeds:
        bl = []; r = run_match(policies=tuple(pol), seed=s, battle_log=bl, factions=("aurum", "sable"), size="small")
        for b in bl: f.write(json.dumps(b) + "\n")
        print("seed %d winner P%s ticks %d assaults %d (won %d)" % (s, r["winner"], r["ticks"], len(bl), sum(b["won"] for b in bl)))
