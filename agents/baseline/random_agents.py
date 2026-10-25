"""Random agents for both sides, used as a sanity-check baseline."""

import random

from agents.base import Agent
from engine import config as C


class RandomRed(Agent):
    side, name = "red", "Random Red"

    def __init__(self, seed=None):
        super().__init__()
        self.rng = random.Random(seed)

    def reset(self, seed=None):
        super().reset(seed)
        self.rng = random.Random(seed)

    def choose_action(self, obs):
        act = self.rng.choice(obs.legal)
        self.debug = {"next": act}
        return act


class RandomBlue(Agent):
    side, name = "blue", "Random Blue"

    def __init__(self, seed=None):
        super().__init__()
        self.rng = random.Random(seed)

    def reset(self, seed=None):
        super().reset(seed)
        self.rng = random.Random(seed)

    def choose_action(self, obs):
        net, rng = obs.net, self.rng
        ap, acts = obs.ap, []
        for _ in range(6):
            kind = rng.choice(list(C.COST))
            if C.COST[kind] > ap:
                continue
            target = rng.randrange(3) if kind == "monitor" else rng.randrange(net.n)
            acts.append((kind, target))
            ap -= C.COST[kind]
        self.debug = {"actions": acts}
        return acts
