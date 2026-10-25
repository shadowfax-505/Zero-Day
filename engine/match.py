"""One match between two agents. Shared by the UI and the headless runner."""

from engine.game import Game
from engine.mapgen import generate


class Match:
    def __init__(self, red, blue, seed=None, net=None):
        self.net = net or generate(seed)
        self.game = Game(self.net)
        self.red, self.blue = red, blue
        self.red.reset(self.net.seed * 31 + 7)
        self.blue.reset(self.net.seed * 17 + 3)
        self.red_debug, self.blue_debug = {}, {}
        self.located_round = None   # first round Blue's top guess was Red's real node

    @property
    def over(self):
        return self.game.winner is not None

    def ask_red(self):
        act = self.red.choose_action(self.game.red_observation())
        self.red_debug = dict(self.red.debug)
        return act

    def ask_blue(self):
        acts = self.blue.choose_action(self.game.blue_observation())
        self.blue_debug = dict(self.blue.debug)
        return acts

    def decide(self):
        """Ask both agents for their move (no state change). Returns (red_action, blue_actions)."""
        return self.ask_red(), self.ask_blue()

    def apply(self, red_act, blue_acts):
        g = self.game
        top = self.blue_debug.get("top_guess")
        if self.located_round is None and top is not None and top == g.red_pos and g.round > 1:
            self.located_round = g.round
        g.step(red_act, blue_acts)

    def play_round(self):
        self.apply(*self.decide())

    def play(self):
        while not self.over:
            self.play_round()
        g = self.game
        return {
            "seed": self.net.seed,
            "winner": g.winner,
            "reason": g.reason,
            "rounds": g.round,
            "located": self.located_round,
            "red": self.red.name,
            "blue": self.blue.name,
        }
