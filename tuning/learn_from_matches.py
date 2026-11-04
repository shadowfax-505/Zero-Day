"""Learn the two models inside Red's IS-MCTS from logged matches.

1. Blue's response policy. Red's search needs a fast stand-in for Blue inside
   every rollout. A hand-written "isolate the hottest node" rule was much weaker
   than the real Blue AI, so every sampled future looked equally rosy and MCTS
   could not tell moves apart. We log what Blue actually did in each situation
   Red can recognise and save the frequencies to tuning/blue_policy.json.

2. A leaf value. Where a rollout stops, a hand-made "progress along the route"
   score ignored the 40-round clock, so MCTS liked slow, quiet moves that lose
   on time. We fit a logistic regression P(Red wins | what Red knows) on the
   same logged states and save it to tuning/red_value.json.

Situations are described only with things Red's simulation also tracks:
  hot       - one of Red's own actions near its node raised an alert last round
  on_route  - Red's move heads for one of the two neighbours nearest the
              database (straight-line), which is what Blue predicts
  ready     - Blue's isolate is recharged

    python -m tuning.learn_from_matches --matches 200
"""

import argparse
import json
import os
from multiprocessing import Pool

import numpy as np

from agents.blue.agent import BlueAI
from agents.red.agent import RedAI
from agents.red.astar import cost_to_go
from agents.red.ismcts import value_features, VALUE_FEATURES
from engine import config as C
from engine.match import Match

HERE = os.path.dirname(__file__)
OUT = os.path.join(HERE, "blue_policy.json")
VALUE_OUT = os.path.join(HERE, "red_value.json")

# (event, condition) -> [hits, trials]
KEYS = [
    "iso_pos|hot", "iso_pos|cold",
    "iso_next|route_hot", "iso_next|route_cold", "iso_next|off_route",
    "patch_next|route", "patch_next|off_route",
    "decoy_next|route", "decoy_next|off_route",
    "restore_held", "monitor_zone|hot", "monitor_zone|cold",
]


def obvious_steps(net, pos, k=2):
    """The k neighbours of pos closest to the database in a straight line."""
    dx, dy = net.pos[net.database]
    near = sorted(net.adj[pos], key=lambda v: (net.pos[v][0] - dx) ** 2 + (net.pos[v][1] - dy) ** 2)
    return set(near[:k])


def _log_match(seed):
    m = Match(RedAI(time_limit=0.04, iterations=300), BlueAI(particles=1000), seed=seed)
    g, net = m.game, m.net
    c = {k: [0, 0] for k in KEYS}
    rows = []

    def count(key, hit):
        c[key][0] += int(hit)
        c[key][1] += 1

    while not m.over:
        obs = g.red_observation()
        red_act, blue_acts = m.decide()
        pos = g.red_pos
        near = {pos, *net.adj[pos]}
        last = g.history[-1].alerts if g.history else []
        hot = any(real and u in near for u, _, real in last)
        target = red_act[1] if len(red_act) > 1 else (net.database if red_act[0] == "claim" else None)
        on_route = target is not None and target in obvious_steps(net, pos)
        ready = g.round >= g.isolate_ready and not g.isolated
        kinds = {(k, t) for k, t in blue_acts}
        isolated = {t for k, t in kinds if k == "isolate"}
        if ready and pos not in (net.gateway,):
            count("iso_pos|hot" if hot else "iso_pos|cold", pos in isolated)
        if ready and target is not None and target != net.database:
            key = ("iso_next|route_hot" if hot else "iso_next|route_cold") if on_route else "iso_next|off_route"
            count(key, target in isolated)
        if target is not None and target not in g.patched:
            count("patch_next|route" if on_route else "patch_next|off_route", ("patch", target) in kinds)
        if target is not None and target != net.database and target not in g.red_held:
            count("decoy_next|route" if on_route else "decoy_next|off_route", ("decoy", target) in kinds)
        behind = [v for v in g.red_held if v not in (pos, net.gateway)]
        if behind:
            count("restore_held", any(k == "restore" and t in behind for k, t in kinds))
        if target is not None:
            count("monitor_zone|hot" if hot else "monitor_zone|cold", ("monitor", net.zone[target]) in kinds)
        ctg, _ = cost_to_go(obs, m.red.model, m.red.lam)
        rows.append(value_features(ctg.get(pos, 30.0), C.MAX_ROUNDS - g.round, len(g.red_held), hot))
        m.apply(red_act, blue_acts)
    won = 1.0 if g.winner == "red" else 0.0
    return c, [(r, won) for r in rows]


def fit_logistic(x, y, l2=1e-3, iters=50):
    """Newton's method for L2-regularised logistic regression."""
    w = np.zeros(x.shape[1])
    for _ in range(iters):
        p = 1 / (1 + np.exp(-x @ w))
        grad = x.T @ (p - y) + l2 * w
        hess = (x * (p * (1 - p))[:, None]).T @ x + l2 * np.eye(len(w))
        step = np.linalg.solve(hess, grad)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def learn(matches=200, start_seed=5001, workers=None):
    with Pool(workers or os.cpu_count()) as pool:
        out = pool.map(_log_match, range(start_seed, start_seed + matches))
    logs = [c for c, _ in out]
    samples = [s for _, ss in out for s in ss]
    x = np.array([r for r, _ in samples], dtype=float)
    y = np.array([w for _, w in samples], dtype=float)
    w = fit_logistic(x, y)
    p = 1 / (1 + np.exp(-x @ w))
    acc = float(((p > 0.5) == (y > 0.5)).mean())
    brier = float(((p - y) ** 2).mean())
    with open(VALUE_OUT, "w") as f:
        json.dump({"features": VALUE_FEATURES, "weights": [round(float(v), 5) for v in w],
                   "samples": len(y), "accuracy": round(acc, 3), "brier": round(brier, 4)}, f, indent=2)
    tot = {k: [sum(c[k][0] for c in logs), sum(c[k][1] for c in logs)] for k in KEYS}
    # Laplace smoothing so a rare situation never gets a hard 0 or 1
    probs = {k: round((h + 1) / (n + 2), 4) for k, (h, n) in tot.items()}
    data = {"matches": matches, "seeds": [start_seed, start_seed + matches - 1],
            "p": probs, "counts": tot}
    with open(OUT, "w") as f:
        json.dump(data, f, indent=2)
    data["value"] = {"accuracy": acc, "brier": brier, "samples": len(y),
                     "weights": dict(zip(VALUE_FEATURES, np.round(w, 3).tolist()))}
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matches", type=int, default=200)
    ap.add_argument("--seed", type=int, default=5001, help="first map seed (kept apart from the test seeds 1-100)")
    a = ap.parse_args()
    data = learn(a.matches, a.seed)
    for k, p in data["p"].items():
        h, n = data["counts"][k]
        print(f"{k:22s} {p:.3f}   ({h}/{n})")
    v = data["value"]
    print(f"leaf value: {v['samples']} states, accuracy {v['accuracy']:.3f}, Brier {v['brier']:.4f}")
    print("  weights:", v["weights"])


if __name__ == "__main__":
    main()
