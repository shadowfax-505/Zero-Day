"""Red's opponent model (outline section 05, part 3).

Counts where Blue's defences have shown up so far and turns the counts into
probabilities with Laplace smoothing. They feed the A* step cost (P_decoy) and
the sampling of hidden state in Information-Set MCTS.
"""

from engine import config as C

# Red does not see sensitivity, but it knows what each kind of zone is like
ZONE_SENSITIVITY = [0.75, 0.55, 0.85]


class OpponentModel:
    def __init__(self):
        self.zone_acts = [0, 0, 0]       # rounds Red acted in each zone
        self.zone_caught = [0, 0, 0]     # times Blue took a node from Red in each zone
        self.decoys_found = [0, 0, 0]
        self.decoy_nodes = set()         # nodes where a decoy has been sprung before
        self.isolated_kinds = {}
        self.seen_isolated = set()
        self.recent_caught = 0.0         # decays; makes Red more careful after a hit
        self.fails = {}                  # failed captures per node: it may have been patched
        self.blocked = 0                 # times Blue isolated the very node Red was about to take
        self.moves = 0

    def observe(self, obs, last_action_zone):
        if last_action_zone is not None:
            self.zone_acts[last_action_zone] += 1
        self.recent_caught *= 0.7
        for ev in obs.events:
            if ev[0] == "lost":
                z = obs.nodes[ev[1]].zone if ev[1] in obs.nodes else 1
                self.zone_caught[z] += 1
                self.recent_caught += 1.0
            elif ev[0] == "blocked":
                self.blocked += 1
            elif ev[0] == "failed":
                self.fails[ev[1]] = self.fails.get(ev[1], 0) + 1
            elif ev[0] == "decoy":
                z = obs.nodes[ev[1]].zone if ev[1] in obs.nodes else 1
                self.decoys_found[z] += 1
                self.decoy_nodes.add(ev[1])
                self.recent_caught += 1.5
        for u, info in obs.nodes.items():
            if info.isolated and u not in self.seen_isolated:
                self.seen_isolated.add(u)
                self.isolated_kinds[info.kind] = self.isolated_kinds.get(info.kind, 0) + 1

    # -- probabilities -----------------------------------------------------
    def p_monitor(self, zone):
        """Chance Blue watches this zone in a given round."""
        return min(0.85, (self.zone_caught[zone] + 1) / (self.zone_acts[zone] + 4) * 1.6)

    def p_decoy(self, node, info, seen_in_zone):
        """Chance a node Red has not stood on is a decoy."""
        base = (self.decoys_found[info.zone] + 0.6) / (seen_in_zone + 6)
        if info.weakness is not None and info.weakness >= C.DECOY_APPARENT_WEAKNESS - 0.01:
            base *= 3.0      # too good to be true
        if node in self.decoy_nodes:
            base = max(base, 0.5)    # Blue likes to re-arm the same spot
        return min(0.8, base)

    def weakness(self, node, info, unknown=0.5):
        """Red's estimate of a node's weakness, lowered after each failed capture."""
        w = info.weakness if info.weakness is not None else unknown
        f = self.fails.get(node, 0)
        # repeated failures hint at a patch, but each try also adds the retry bonus
        return min(0.95, w * (0.8 ** f) + C.RETRY_BONUS * f)

    def p_block(self):
        """How often Blue guesses Red's next step and isolates it first."""
        return min(0.8, (self.blocked + 0.3) / (self.moves + 3))

    def p_hunt(self):
        """How readily Blue reacts to alerts by cutting nodes off, learned from how often Red got hit."""
        acts = sum(self.zone_acts)
        hits = sum(self.zone_caught) + sum(self.decoys_found)
        return min(0.9, 0.3 + 2.0 * hits / (acts + 4))

    def sensitivity(self, zone):
        return ZONE_SENSITIVITY[zone] * (1 + (C.MONITOR_BOOST - 1) * self.p_monitor(zone))

    def summary(self):
        return {
            "p_monitor": [round(self.p_monitor(z), 2) for z in range(3)],
            "decoys_found": sum(self.decoys_found),
            "caught": sum(self.zone_caught),
        }
