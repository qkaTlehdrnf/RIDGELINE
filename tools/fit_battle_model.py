"""Learn 'will this assault succeed?' from earlier battles and save it as plain JSON a policy can use.

  python tools/collect_battles.py runs/battles.jsonl 0 1 2 3      # play games, append every assault episode
  python tools/fit_battle_model.py runs/battles.jsonl policies/model.json

The model is a logistic regression over things a commander can know before attacking. A policy receives the
JSON as api.model and evaluates it with model_p() below (copy the function into the policy; policies cannot import).
Anything fancier (trees, small neural nets, per-terrain tables) works the same way: train offline on the
battle log, export numbers as JSON, evaluate them inside tick(api).
"""
import json, math, random, sys

DFN = {"plain": 1.0, "forest": 1.25, "hill": 1.5, "mountain": 2.0}
FEATURES = ["log_ratio", "terrain_dfn", "fort", "city", "bonus", "att_rdy", "heavy_share", "dirs"]


def features(b):
    """b: a battle-log record, or the same fields estimated by a policy before attacking."""
    heavy = sum(b["att_types"].get(k, 0) for k in ("art", "eng", "arm")) / max(1, b["att_n"])
    return [math.log((max(0.0, b["att_str"]) + 1.0) / (max(0.0, b["def_str"]) + 1.0)), DFN[b["terrain"]], b["fort"], b["city"],
            b["att_bonus"] / 100.0, b["att_rdy"] / 100.0, heavy, b["dirs"]]


def model_p(model, x):
    z = model["b"] + sum(w * (v - m) / s for w, v, m, s in zip(model["w"], x, model["mean"], model["std"]))
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def fit(rows, epochs=800, lr=0.3, l2=1e-3):
    X = [features(r) for r in rows]; y = [r["won"] for r in rows]; n = len(X); k = len(X[0])
    mean = [sum(x[j] for x in X) / n for j in range(k)]
    std = [max(1e-6, (sum((x[j] - mean[j]) ** 2 for x in X) / n) ** 0.5) for j in range(k)]
    Z = [[(x[j] - mean[j]) / std[j] for j in range(k)] for x in X]
    w = [0.0] * k; b = 0.0
    for _ in range(epochs):
        gw = [0.0] * k; gb = 0.0
        for z, t in zip(Z, y):
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, b + sum(wi * zi for wi, zi in zip(w, z))))))
            e = p - t; gb += e
            for j in range(k): gw[j] += e * z[j]
        b -= lr * gb / n
        for j in range(k): w[j] -= lr * (gw[j] / n + l2 * w[j])
    return dict(features=FEATURES, w=[round(v, 4) for v in w], b=round(b, 4), mean=[round(v, 4) for v in mean],
                std=[round(v, 4) for v in std], n=n, base_rate=round(sum(y) / n, 3))


def main():
    rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
    rows = [r for r in rows if r["def_n"] > 0]
    random.Random(0).shuffle(rows)
    cut = int(len(rows) * 0.8); train, test = rows[:cut], rows[cut:]
    m = fit(train)
    def acc(rs): return sum((model_p(m, features(r)) >= 0.5) == bool(r["won"]) for r in rs) / max(1, len(rs))
    def brier(rs): return sum((model_p(m, features(r)) - r["won"]) ** 2 for r in rs) / max(1, len(rs))
    sc = [(model_p(m, features(r)), r["won"]) for r in test]; pos = [p for p, w in sc if w]; neg = [p for p, w in sc if not w]
    auc = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / max(1, len(pos) * len(neg))
    m["holdout"] = dict(auc=round(auc, 3), n=len(test), accuracy=round(acc(test), 3), brier=round(brier(test), 3),
                        always_no_accuracy=round(1 - sum(r["won"] for r in test) / max(1, len(test)), 3))
    json.dump(m, open(sys.argv[2], "w", encoding="utf-8"), indent=1)
    print("rows %d (train %d, holdout %d), success rate %.2f" % (len(rows), len(train), len(test), m["base_rate"]))
    for f, w in sorted(zip(FEATURES, m["w"]), key=lambda t: -abs(t[1])): print("  %-12s %+.3f" % (f, w))
    print("holdout:", m["holdout"])


if __name__ == "__main__":
    main()
