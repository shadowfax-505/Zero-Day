"""Genetic algorithm that tunes either side's strategy weights (outline section 06, part 4).

Chromosome : real-valued weights (agents/blue/agent.py GENES or agents/red/agent.py GENES)
Fitness    : the side's win rate against the other side's current AI on random
             maps; Blue also gets a small bonus for locating Red early
Operators  : tournament selection (size 3), uniform crossover,
             Gaussian mutation, elitism (best 2 survive unchanged)
Racing     : every generation plays its maps in three rounds. All individuals
             play the first third, only the better half plays the second third,
             and only the best quarter plays all of them. Bad genomes are
             dropped early, so the same compute buys three times as many
             matches for the candidates that matter (a cleaner fitness).

    python -m tuning.ga                              # Blue: 30 x 40 gens x 30 matches
    python -m tuning.ga --side red --pop 16 --gens 10 --matches 36
    python -m tuning.ga --side blue --seed-from tuning/best_weights.json   # warm start

Every individual in a generation plays the same maps, so they are compared
fairly. Blue's best weights go to tuning/best_weights.json and Red's to
tuning/red_weights.json; the AIs load them automatically. Fitness curves go to
tuning/fitness.csv (Blue) and tuning/fitness_red.csv (Red).
"""

import argparse
import csv
import json
import os
import random
import time
from multiprocessing import Pool

from agents.blue import agent as blue_agent
from agents.blue.agent import BlueAI
from agents.red import agent as red_agent
from agents.red.agent import RedAI
from engine import config as C
from engine.match import Match

HERE = os.path.dirname(__file__)
SIDES = {
    "blue": {"genes": blue_agent.GENES, "weights": "best_weights.json", "csv": "fitness.csv",
             "png": "fitness.png", "state": "ga_state.json"},
    "red": {"genes": red_agent.GENES, "weights": "red_weights.json", "csv": "fitness_red.csv",
            "png": "fitness_red.png", "state": "ga_state_red.json"},
}
SIDE = "blue"
GENES = blue_agent.GENES
NAMES = list(GENES)
DEFAULT_WEIGHTS = {k: v[0] for k, v in GENES.items()}


def set_side(side):
    global SIDE, GENES, NAMES, DEFAULT_WEIGHTS, STATE
    SIDE = side
    GENES = SIDES[side]["genes"]
    NAMES = list(GENES)
    DEFAULT_WEIGHTS = {k: v[0] for k, v in GENES.items()}
    STATE = os.path.join(HERE, SIDES[side]["state"])


def random_genome(rng):
    return [rng.uniform(GENES[k][1], GENES[k][2]) for k in NAMES]


def to_weights(genome):
    return {k: round(v, 4) for k, v in zip(NAMES, genome)}


def clip(genome):
    return [min(GENES[k][2], max(GENES[k][1], v)) for k, v in zip(NAMES, genome)]


def _eval(args):
    """Total score over the given maps (summed, so racing rounds can be added up)."""
    side, genome, seeds = args
    set_side(side)
    total = 0.0
    for s in seeds:
        if side == "blue":
            red, blue = RedAI(time_limit=0.04, iterations=300), BlueAI(weights=to_weights(genome), particles=800)
        else:
            red, blue = RedAI(time_limit=0.04, iterations=300, weights=to_weights(genome)), BlueAI(particles=800)
        r = Match(red, blue, seed=s).play()
        if r["winner"] == side:
            total += 1
        if side == "blue" and r["located"]:
            total += 0.1 * (C.MAX_ROUNDS - r["located"]) / C.MAX_ROUNDS
    return total


def race(pool, pop, seeds):
    """Successive halving: returns (fitness per individual, matches played per individual)."""
    n = len(pop)
    thirds = [seeds[i::3] for i in range(3)]
    score, played = [0.0] * n, [0] * n
    alive = list(range(n))
    for k, part in enumerate(thirds):
        res = pool.map(_eval, [(SIDE, pop[i], part) for i in alive])
        for i, r in zip(alive, res):
            score[i] += r
            played[i] += len(part)
        alive.sort(key=lambda i: -score[i] / played[i])
        alive = alive[:max(2, len(alive) // 2)]
    return [score[i] / played[i] for i in range(n)], played


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


def run(pop_size=30, gens=40, matches=30, seed=1, workers=None, resume=False, seed_files=(), side="blue"):
    set_side(side)
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
            fit, played = race(pool, pop, seeds)
            # rank the fully tested genomes first; the ones dropped early keep their partial score
            order = sorted(range(pop_size), key=lambda i: (-played[i], -fit[i]))
            best, mean = fit[order[0]], sum(fit) / pop_size
            history.append({"generation": gen, "best": round(best, 4), "mean": round(mean, 4)})
            if best > best_overall[0]:
                best_overall = (best, pop[order[0]])
            print(f"gen {gen:2d}  best {best:.3f}  mean {mean:.3f}  "
                  f"matches {sum(played)}  [{time.time()-t:.0f}s]", flush=True)
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
        scores = [x / len(seeds) for x in pool.map(_eval, [(SIDE, g, seeds) for g in finalists])]
    k = max(range(len(finalists)), key=lambda i: scores[i])
    print("finalists:", [round(x, 3) for x in scores], flush=True)
    best_overall = (scores[k], finalists[k])
    _save(best_overall, history, pop_size, gens, matches)
    _plot(history)
    return to_weights(best_overall[1]), history


def _tuplify(x):
    return tuple(_tuplify(v) for v in x) if isinstance(x, list) else x


def _save(best_overall, history, pop_size, gens, matches):
    with open(os.path.join(HERE, SIDES[SIDE]["weights"]), "w") as f:
        json.dump({"side": SIDE, "fitness": round(best_overall[0], 4), "pop": pop_size,
                   "generations": len(history), "planned_generations": gens, "matches_per_eval": matches,
                   "racing": True, "weights": to_weights(best_overall[1])}, f, indent=2)
    with open(os.path.join(HERE, SIDES[SIDE]["csv"]), "w", newline="") as f:
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
    plt.plot(g, [h["best"] for h in history], label="best", color="#3b82f6" if SIDE == "blue" else "#c43422",
             linewidth=2)
    plt.plot(g, [h["mean"] for h in history], label="mean", color="#94a3b8")
    plt.xlabel("generation")
    plt.ylabel("fitness (Blue win rate + detection bonus)" if SIDE == "blue" else "fitness (Red win rate)")
    plt.title(f"{SIDE.title()} AI: genetic algorithm tuning")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(HERE, SIDES[SIDE]["png"]), dpi=130)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--side", choices=SIDES, default="blue", help="which AI to tune")
    ap.add_argument("--pop", type=int, default=30)
    ap.add_argument("--gens", type=int, default=40)
    ap.add_argument("--matches", type=int, default=30)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--resume", action="store_true", help="continue a stopped run from tuning/ga_state.json")
    ap.add_argument("--seed-from", nargs="*", default=[], help="weights JSON files to put in the first population")
    a = ap.parse_args()
    run(a.pop, a.gens, a.matches, a.seed, resume=a.resume, seed_files=a.seed_from, side=a.side)


if __name__ == "__main__":
    main()
