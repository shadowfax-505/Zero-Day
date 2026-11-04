"""Red AI: A* proposes a route, IS-MCTS decides the move, the opponent model adapts."""

import json
import os
import random

from agents.base import Agent
from agents.red.astar import plan, action_for_step, node_risk, heuristic
from agents.red.ismcts import ISMCTS
from agents.red.opponent_model import OpponentModel
from engine import config as C

# The genome the GA tunes for Red (tuning/ga.py --side red). (default, low, high)
GENES = {
    "margin":     (0.02, 0.0, 0.15),   # least average gain before MCTS overrides A*'s step
    "z":          (2.0, 1.0, 4.0),     # ...and how many standard errors clear of zero it must be
    "lam_base":   (1.0, 0.4, 2.0),     # how much A* cares about risk at all
    "lam_caught": (1.2, 0.0, 2.5),     # extra caution right after Blue hits Red
    "lam_late":   (0.6, 0.0, 1.5),     # how much boldness grows late in the match
    "late_round": (25.0, 12.0, 35.0),  # when "late" starts
}
DEFAULT_WEIGHTS = {k: v[0] for k, v in GENES.items()}
WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "tuning", "red_weights.json")


def load_tuned_weights():
    try:
        with open(WEIGHTS_FILE) as f:
            data = json.load(f)
        w = dict(DEFAULT_WEIGHTS)
        w.update({k: float(v) for k, v in data.get("weights", {}).items() if k in GENES})
        return w
    except (OSError, ValueError):
        return dict(DEFAULT_WEIGHTS)


class RedAI(Agent):
    side = "red"

    def __init__(self, use_mcts=True, iterations=1000, time_limit=0.2, seed=None, weights=None, name=None):
        super().__init__()
        self.use_mcts = use_mcts
        self.weights = dict(weights) if weights else load_tuned_weights()
        self.iterations, self.time_limit = iterations, time_limit
        self.name = name or ("Red AI" if use_mcts else "Red A* only")
        self.reset(seed)

    def reset(self, seed=None):
        super().reset(seed)
        self.rng = random.Random(seed)
        self.model = OpponentModel()
        self.mcts = ISMCTS(self.iterations, self.time_limit, rng=self.rng)
        self.last_zone = None
        self.last_risk = 0.0
        self.gateway = None
        self.lam = 1.0

    def choose_action(self, obs):
        if self.gateway is None:
            self.gateway = obs.pos          # Red always starts on the gateway
        self.model.observe(obs, self.last_zone)
        # careful after being caught, bolder late in the match
        w = self.weights
        late = max(0.0, obs.round - w["late_round"]) / max(1.0, 40 - w["late_round"])
        self.lam = max(0.1, w["lam_base"] + w["lam_caught"] * min(1.0, self.model.recent_caught) - w["lam_late"] * late)
        path, cost, reaches = plan(obs, self.model, self.lam)
        route_action = action_for_step(obs, path)
        legal = [tuple(a) for a in obs.legal]
        if route_action not in legal:
            route_action = ("scout",)

        stats, iters, secs = [], 0, 0.0
        act = route_action
        frontier_scout = route_action == ("scout",) and obs.pos not in obs.expanded
        if self.use_mcts and not frontier_scout:
            cands = legal
            if all(obs.nodes[v].weakness is not None for v in obs.edges.get(obs.pos, ())):
                cands = [x for x in legal if x != ("scout",)] or legal   # nothing left to learn here
            # stepping back onto held nodes never gets Red closer; leave those to A*
            h = heuristic(obs, obs.pos)
            cands = [x for x in cands if x[0] != "advance" or heuristic(obs, x[1]) < h] or cands
            if route_action not in cands:
                cands = [route_action] + cands
            stats, iters, secs = self.mcts.search(obs, self.model, cands, self.lam,
                                                  p_hot=self.last_risk, gateway=self.gateway)
            if stats and route_action in self.mcts.rewards:
                # MCTS overrides A*'s step only when the paired samples say it is
                # better by a clear margin AND the gain is statistically solid
                best = stats[0][0]
                gain, se = self.mcts.paired_gain(best, route_action)
                if best != route_action and gain > w["margin"] and gain > w["z"] * se:
                    act = best
        if act not in legal:
            act = route_action

        if len(act) > 1:
            self.model.moves += 1
        target = act[1] if len(act) > 1 else (obs.database if act[0] == "claim" else obs.pos)
        zone = obs.nodes[target].zone if target in obs.nodes else 2
        self.last_zone = zone
        sens = self.model.sensitivity(zone)
        risk = min(0.99, C.NOISE[act[0]] * sens)
        self.last_risk = risk
        seen = [0, 0, 0]
        for info in obs.nodes.values():
            seen[info.zone] += 1
        self.debug = {
            "route": path,
            "route_cost": cost,
            "reaches_db": reaches,
            "next": act,
            "astar_next": route_action,
            "mcts": stats[:5],
            "iterations": iters,
            "think_ms": int(secs * 1000),
            "risk": risk,
            "lambda": round(self.lam, 2),
            "model": self.model.summary(),
            "pos": obs.pos,
            "decoy_suspects": sorted(
                ((u, self.model.p_decoy(u, info, seen[info.zone])) for u, info in obs.nodes.items()
                 if u not in obs.held), key=lambda t: -t[1])[:3],
        }
        return act
