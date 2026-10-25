"""Common agent interface: choose_action(observation) -> action.

A human player is just another agent whose action comes from the UI, which is
how Human vs AI mode works without special cases in the engine.
"""


class Agent:
    side = None          # "red" or "blue"
    name = "agent"

    def __init__(self):
        self.debug = {}  # what the UI panels show about the agent's reasoning

    def reset(self, seed=None):
        self.debug = {}

    def choose_action(self, obs):
        raise NotImplementedError
