"""Just enough game state to draw a map on the menu."""


class MenuGame:
    def __init__(self, net):
        self.red_known = set(range(net.n))
        self.red_known_edges = {}
        self.open_gates = set()
        self.red_held = set()
        self.red_pos = net.gateway
        self.isolated = {}
        self.patched = set()
        self.decoys = set()
        self.red_intel_weak = {}
        self.winner = "blue"
        self.monitored = set()
        self.history = []
