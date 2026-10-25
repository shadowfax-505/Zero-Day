"""Human players. The UI fills in the action; the engine treats them like any agent."""

from agents.base import Agent


class HumanRed(Agent):
    side, name = "red", "Human (Red)"

    def choose_action(self, obs):
        raise RuntimeError("the UI supplies the human's action")


class HumanBlue(Agent):
    side, name = "blue", "Human (Blue)"

    def choose_action(self, obs):
        raise RuntimeError("the UI supplies the human's action")
