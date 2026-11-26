"""Controlled assaults for the no-war analysis: who wins, and what it costs, by force ratio x ground x fort x preparation."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenario as S
rows = []
for terrain in ("plain", "forest", "hill", "mountain"):
    for fort in (0, 1, 2, 3):
        for ratio in (1, 2, 3, 5, 8):
            for mix in ("inf", "combined"):
                for rdy, prep, label in ((35, 0, "hasty"), (90, 0, "rested"), (90, 36, "prepared")):
                    for dirs in (1, 3):
                        n = 6 * ratio; att = {"inf": n} if mix == "inf" else {"inf": n - 2 * (n // 3), "art": n // 3, "eng": n // 6, "grn": n // 3 - n // 6}
                        w = l = dl = h = 0
                        for seed in (3, 4, 5):
                            took, hrs, loss, left = S.run(att, {"inf": 6}, fort=fort, terrain=terrain, rdy=rdy, prep=prep, dirs=dirs, seed=seed)
                            w += took; l += loss; dl += 600 - left; h += hrs
                        rows.append(dict(terrain=terrain, fort=fort, ratio=ratio, mix=mix, prep=label, dirs=dirs, win=w / 3, att_loss=l / 3, def_loss=dl / 3, hours=h / 3))
json.dump(rows, open(sys.argv[1], "w"))
