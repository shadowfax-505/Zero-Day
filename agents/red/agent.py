"""Red AI: A* proposes a route, IS-MCTS decides the move, the opponent model adapts."""

import random

from agents.base import Agent
from agents.red.astar import plan, action_for_step, node_risk
from agents.red.ismcts import ISMCTS
from agents.red.opponent_model import OpponentModel
from engine import config as C

OVERRIDE_MARGIN = 0.03


class RedAI(Agent):
    side = "red"

    def __init__(self, use_mcts=True, iterations=1000, time_limit=0.2, seed=None):
        super().__init__()
        self.use_mcts = use_mcts
        self.iterations, self.time_limit = iterations, time_limit
        self.name = "Red AI" if use_mcts else "Red A* only"
        self.reset(seed)

    def reset(self, seed=None):
        super().reset(seed)
        self.rng = random.Random(seed)
        self.model = OpponentModel()
        self.mcts = ISMCTS(self.iterations, self.time_limit, rng=self.rng)
        self.last_zone = None
        self.lam = 1.0

    def choose_action(self, obs):
        self.model.observe(obs, self.last_zone)
        # careful after being caught, bolder late in the match
        self.lam = 1.0 + 1.2 * min(1.0, self.model.recent_caught) - 0.6 * max(0, obs.round - 25) / 15
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
            stats, iters, secs = self.mcts.search(obs, self.model, cands, self.lam)
            if stats:
                # MCTS overrides A*'s step only when it is clearly better on average
                # over the sampled hidden states
                q = {a: (n, v) for a, n, v in stats}
                best = max(stats, key=lambda t: t[2] if t[1] >= 0.1 * iters / len(stats) else -1)
                base = q.get(route_action, (0, -1.0))[1]
                act = best[0] if best[2] > base + OVERRIDE_MARGIN else route_action
        if act not in legal:
            act = route_action

        if len(act) > 1:
            self.model.moves += 1
        target = act[1] if len(act) > 1 else (obs.database if act[0] == "claim" else obs.pos)
        zone = obs.nodes[target].zone if target in obs.nodes else 2
        self.last_zone = zone
        sens = self.model.sensitivity(zone)
        risk = min(0.99, C.NOISE[act[0]] * sens)
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
