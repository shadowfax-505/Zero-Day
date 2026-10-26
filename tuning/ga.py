"""Genetic algorithm that tunes Blue's strategy weights (outline section 06, part 4).

Chromosome : Blue's real-valued weights (agents/blue/agent.py GENES)
Fitness    : Blue's win rate against the Red AI on random maps, plus a small
             bonus for locating Red early
Operators  : tournament selection (size 3), uniform crossover,
             Gaussian mutation, elitism (best 2 survive unchanged)

    python -m tuning.ga                       # outline settings: 30 x 40 gens x 30 matches
    python -m tuning.ga --pop 12 --gens 8 --matches 12     # quick run

Every individual in a generation plays the same maps, so they are compared
fairly. The best weights are written to tuning/best_weights.json, which the
Blue AI loads automatically, and the fitness curve to tuning/fitness.csv.
"""

import argparse
import csv
import json
import os
import random
import time
from multiprocessing import Pool

from agents.blue.agent import BlueAI, GENES, DEFAULT_WEIGHTS
from agents.red.agent import RedAI
from engine import config as C
from engine.match import Match

HERE = os.path.dirname(__file__)
NAMES = list(GENES)


def random_genome(rng):
    return [rng.uniform(GENES[k][1], GENES[k][2]) for k in NAMES]


def to_weights(genome):
    return {k: round(v, 4) for k, v in zip(NAMES, genome)}


def clip(genome):
    return [min(GENES[k][2], max(GENES[k][1], v)) for k, v in zip(NAMES, genome)]


def _eval(args):
    genome, seeds = args
    wins, bonus = 0, 0.0
    for s in seeds:
        m = Match(RedAI(time_limit=0.04, iterations=300), BlueAI(weights=to_weights(genome), particles=800), seed=s)
        r = m.play()
        if r["winner"] == "blue":
            wins += 1
        if r["located"]:
            bonus += (C.MAX_ROUNDS - r["located"]) / C.MAX_ROUNDS
    return wins / len(seeds) + 0.1 * bonus / len(seeds)


def tournament(rng, pop, fit, k=3):
    best = max(rng.sample(range(len(pop)), k), key=lambda i: fit[i])
    return pop[best]


def crossover(rng, a, b):
    return [x if rng.random() < 0.5 else y for x, y in zip(a, b)]


def mutate(rng, g, rate=0.2, scale=0.12):
    out = []
    for k, v in zip(NAMES, g):
        if rng.random() < rate:
            lo, hi = GENES[k][1], GENES[k][2]
            v += rng.gauss(0, scale * (hi - lo))
        out.append(v)
    return clip(out)


STATE = os.path.join(HERE, "ga_state.json")


def run(pop_size=30, gens=40, matches=30, seed=1, workers=None, resume=False, seed_files=()):
    rng = random.Random(seed)
    if resume and os.path.exists(STATE):
        with open(STATE) as f:
            st = json.load(f)
        pop, history, start = st["pop"], st["history"], st["next_gen"]
        best_overall = (st["best_fit"], st["best"])
        rng.setstate(_tuplify(st["rng"]))
        print(f"resuming at generation {start}", flush=True)
    else:
        pop = [[DEFAULT_WEIGHTS[k] for k in NAMES]]
        for path in seed_files:               # warm start from earlier runs' best weights
            with open(path) as f:
                w = json.load(f)["weights"]
            pop.append(clip([w.get(k, DEFAULT_WEIGHTS[k]) for k in NAMES]))
        pop += [random_genome(rng) for _ in range(pop_size - len(pop))]
        history, start, best_overall = [], 0, (-1.0, None)
    with Pool(workers or os.cpu_count()) as pool:
        for gen in range(start, gens):
            t = time.time()
            seeds = [rng.randrange(1, 10 ** 6) for _ in range(matches)]
            fit = pool.map(_eval, [(g, seeds) for g in pop])
            order = sorted(range(pop_size), key=lambda i: -fit[i])
            best, mean = fit[order[0]], sum(fit) / pop_size
            history.append({"generation": gen, "best": round(best, 4), "mean": round(mean, 4)})
            if best > best_overall[0]:
                best_overall = (best, pop[order[0]])
            print(f"gen {gen:2d}  best {best:.3f}  mean {mean:.3f}  [{time.time()-t:.0f}s]", flush=True)
            elite = [pop[i] for i in order[:2]]
            children = []
            while len(children) < pop_size - len(elite):
                a, b = tournament(rng, pop, fit), tournament(rng, pop, fit)
                children.append(mutate(rng, crossover(rng, a, b)))
            pop = elite + children
            # checkpoint every generation so a stopped run can continue with --resume
            _save(best_overall, history, pop_size, gens, matches)
            with open(STATE, "w") as f:
                json.dump({"pop": pop, "history": history, "next_gen": gen + 1, "best_fit": best_overall[0],
                           "best": best_overall[1], "rng": rng.getstate()}, f)

        # a single 30-match score is noisy, so re-test the finalists on a larger common set of maps
        finalists = [best_overall[1]] + [g for g in pop[:2] if g != best_overall[1]]
        seeds = [rng.randrange(1, 10 ** 6) for _ in range(2 * matches)]
        scores = pool.map(_eval, [(g, seeds) for g in finalists])
    k = max(range(len(finalists)), key=lambda i: scores[i])
    print("finalists:", [round(x, 3) for x in scores], flush=True)
    best_overall = (scores[k], finalists[k])
    _save(best_overall, history, pop_size, gens, matches)
    _plot(history)
    return to_weights(best_overall[1]), history


def _tuplify(x):
    return tuple(_tuplify(v) for v in x) if isinstance(x, list) else x


def _save(best_overall, history, pop_size, gens, matches):
    with open(os.path.join(HERE, "best_weights.json"), "w") as f:
        json.dump({"fitness": round(best_overall[0], 4), "pop": pop_size, "generations": len(history),
                   "planned_generations": gens, "matches_per_eval": matches,
                   "weights": to_weights(best_overall[1])}, f, indent=2)
    with open(os.path.join(HERE, "fitness.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["generation", "best", "mean"])
        w.writeheader()
        w.writerows(history)


def _plot(history):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return
    g = [h["generation"] for h in history]
    plt.figure(figsize=(7, 4))
    plt.plot(g, [h["best"] for h in history], label="best", color="#3b82f6", linewidth=2)
    plt.plot(g, [h["mean"] for h in history], label="mean", color="#94a3b8")
    plt.xlabel("generation")
    plt.ylabel("fitness (Blue win rate + detection bonus)")
    plt.title("Blue AI: genetic algorithm tuning")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(HERE, "fitness.png"), dpi=130)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pop", type=int, default=30)
    ap.add_argument("--gens", type=int, default=40)
    ap.add_argument("--matches", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--resume", action="store_true", help="continue a stopped run from tuning/ga_state.json")
    ap.add_argument("--seed-from", nargs="*", default=[], help="weights JSON files to put in the first population")
    a = ap.parse_args()
    run(a.pop, a.gens, a.matches, a.seed, resume=a.resume, seed_files=a.seed_from)


if __name__ == "__main__":
    main()
