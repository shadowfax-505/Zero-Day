"""Headless batch runner (outline section 09).

    python -m experiments.run_batch --red ai --blue ai --matches 100
    python -m experiments.run_batch --suite          # the full evaluation table

Matches use fixed seeds (1..N) so results are repeatable.
"""

import argparse
import csv
import os
import statistics
import time
from multiprocessing import Pool

from engine.match import Match
from experiments.agents_registry import RED, BLUE

OUT_DIR = os.path.join(os.path.dirname(__file__), "results")


def _play(args):
    red, blue, seed, fast = args
    m = Match(RED[red](fast), BLUE[blue](fast), seed=seed)
    return m.play()


def run(red, blue, matches, start_seed=1, fast=False, workers=None):
    jobs = [(red, blue, s, fast) for s in range(start_seed, start_seed + matches)]
    with Pool(workers or os.cpu_count()) as pool:
        return pool.map(_play, jobs)


def summarise(results):
    n = len(results)
    red_wins = [r for r in results if r["winner"] == "red"]
    blue_wins = [r for r in results if r["winner"] == "blue"]
    removed = [r for r in blue_wins if "removed" in r["reason"]]
    located = [r["located"] for r in results if r["located"]]
    return {
        "matches": n,
        "red_win_rate": len(red_wins) / n,
        "blue_win_rate": len(blue_wins) / n,
        "blue_by_removal": len(removed) / n,
        "avg_rounds_red_win": statistics.mean([r["rounds"] for r in red_wins]) if red_wins else None,
        "avg_rounds_blue_win": statistics.mean([r["rounds"] for r in blue_wins]) if blue_wins else None,
        "avg_detection_round": statistics.mean(located) if located else None,
    }


def fmt(s):
    def f(x):
        return "-" if x is None else (f"{x:.1f}" if isinstance(x, float) else str(x))
    return (f"Red {s['red_win_rate']*100:5.1f}%  Blue {s['blue_win_rate']*100:5.1f}% "
            f"(removal {s['blue_by_removal']*100:4.1f}%)  rounds R/B {f(s['avg_rounds_red_win'])}/"
            f"{f(s['avg_rounds_blue_win'])}  first located r{f(s['avg_detection_round'])}")


SUITE = [
    ("ai", "ai", "Red AI vs Blue AI"),
    ("ai", "random", "Red AI vs random Blue"),
    ("random", "ai", "Random Red vs Blue AI"),
    ("astar", "ai", "Ablation: Red A* only (no MCTS)"),
    ("ai", "nofilter", "Ablation: Blue without particle filter"),
    ("ai", "untuned", "Ablation: Blue before GA tuning"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--red", default="ai", choices=RED)
    ap.add_argument("--blue", default="ai", choices=BLUE)
    ap.add_argument("--matches", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--fast", action="store_true", help="smaller search budgets")
    ap.add_argument("--suite", action="store_true", help="run every pairing in the evaluation table")
    args = ap.parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    pairs = SUITE if args.suite else [(args.red, args.blue, f"{args.red} vs {args.blue}")]
    rows = []
    for red, blue, title in pairs:
        t = time.time()
        res = run(red, blue, args.matches, args.seed, args.fast)
        s = summarise(res)
        print(f"{title:42s} {fmt(s)}   [{time.time()-t:.0f}s]", flush=True)
        rows.append({"pairing": title, "red": red, "blue": blue, **s})
        with open(os.path.join(OUT_DIR, f"matches_{red}_vs_{blue}.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(res[0]))
            w.writeheader()
            w.writerows(res)
    if args.suite:
        with open(os.path.join(OUT_DIR, "summary.csv"), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    main()
