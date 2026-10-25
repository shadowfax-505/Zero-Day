"""Game state and rule resolution (outline sections 03 and 04).

The engine owns the true state. Agents only ever receive their own partial
observation (RedObservation / BlueObservation) and return an action, so
neither AI can read hidden information.

Red action:   ("scout",) | ("capture", v) | ("unlock", v) | ("advance", v) | ("claim",)
Blue actions: list of (kind, target) with kind in monitor/patch/decoy/isolate/restore.
              monitor targets a zone id, everything else a node id.
"""

import random
from collections import deque
from dataclasses import dataclass, field

from engine import config as C


@dataclass
class NodeIntel:
    """What Red knows about one node."""
    pos: tuple
    zone: int
    kind: str
    label: str
    weakness: float = None     # None until scouted or held
    isolated: bool = False


@dataclass
class RedObservation:
    round: int
    pos: int
    held: frozenset
    database: int
    db_pos: tuple
    max_edge_len: float
    nodes: dict                 # node -> NodeIntel, only nodes Red has seen
    edges: dict                 # node -> list of known neighbours
    expanded: frozenset         # nodes whose links are all known (held or scouted from)
    gates: dict                 # frozenset(u, v) -> open?
    events: list                # what happened to Red last round
    legal: list


@dataclass
class BlueObservation:
    round: int
    net: object                 # the full static map
    weakness: list
    patched: frozenset
    decoys: frozenset
    isolated: dict
    immune: dict
    alerts: list                # [(node, strength)] from last round
    feedback: list              # [(kind, node, found)] results of Blue's own actions
    decoy_sprung: int = None    # node where Red walked into a decoy last round
    isolate_ready: int = 1      # first round an isolate is allowed again
    ap: int = C.BLUE_AP


@dataclass
class RoundRecord:
    round: int
    red_action: tuple
    blue_actions: list
    red_result: str
    alerts: list
    events: list = field(default_factory=list)


class Game:
    def __init__(self, net, seed=None):
        self.net = net
        self.rng = random.Random(seed if seed is not None else net.seed * 7919 + 1)
        self.round = 1
        self.red_pos = net.gateway
        self.red_held = {net.gateway}
        self.weakness = list(net.weakness)
        self.decoys = set()
        self.patched = set()      # a node can only be patched once
        self.isolate_ready = 1    # first round Blue may isolate again
        self.isolated = {}
        self.immune = {}
        self.monitored = set()
        self.open_gates = set()
        self.winner = None
        self.reason = ""
        self.history = []

        # Red's knowledge
        self.red_known = set()
        self.red_known_edges = {}
        self.red_intel_weak = {}
        self.red_expanded = set()
        self.red_tries = {}       # failed capture attempts per node
        self.red_events = []
        self._reveal_around(net.gateway, scouted=False)
        self.red_intel_weak[net.gateway] = net.weakness[net.gateway]

        # Blue's last-round info
        self.last_alerts = []
        self.blue_feedback = []
        self.decoy_sprung = None
        self.first_located = None   # first round Blue's top guess was Red's true node

    # -- knowledge ---------------------------------------------------------
    def _reveal_node(self, u):
        self.red_known.add(u)
        self.red_known_edges.setdefault(u, set())

    def _reveal_around(self, u, scouted):
        self._reveal_node(u)
        self.red_expanded.add(u)
        for v in self.net.adj[u]:
            self._reveal_node(v)
            self.red_known_edges[u].add(v)
            self.red_known_edges[v].add(u)
            if scouted:
                # scouting maps the neighbours and their own links
                w = C.DECOY_APPARENT_WEAKNESS if v in self.decoys else self.weakness[v]
                self.red_intel_weak[v] = round(w, 2)
                self.red_expanded.add(v)
                for x in self.net.adj[v]:
                    self._reveal_node(x)
                    self.red_known_edges[v].add(x)
                    self.red_known_edges[x].add(v)

    # -- legality ----------------------------------------------------------
    def gate_closed(self, u, v):
        e = frozenset((u, v))
        return e in self.net.gates and e not in self.open_gates

    def red_legal(self):
        net, p = self.net, self.red_pos
        acts = [("scout",)]
        for v in net.adj[p]:
            if v in self.isolated:
                continue
            if v == net.database:
                acts.append(("claim",))
                continue
            if v in self.red_held:
                acts.append(("advance", v))
            elif self.gate_closed(p, v):
                acts.append(("unlock", v))
            else:
                acts.append(("capture", v))
        return acts

    def blue_can(self, kind, target):
        net = self.net
        if kind == "monitor":
            return target in (C.DMZ, C.OFFICE, C.DATACENTRE)
        if not (0 <= target < net.n):
            return False
        if kind == "patch":
            return target not in self.patched and self.weakness[target] > C.PATCH_FLOOR
        if kind == "decoy":
            return (target not in (net.gateway, net.database) and target not in self.decoys
                    and target not in self.isolated and len(self.decoys) < C.MAX_DECOYS)
        if kind == "isolate":
            return (target not in (net.gateway, net.database) and target not in self.isolated
                    and target not in self.immune and len(self.isolated) < C.MAX_ISOLATED
                    and self.round >= self.isolate_ready)
        if kind == "restore":
            return target != net.database
        return False

    # -- observations ------------------------------------------------------
    def red_observation(self):
        nodes = {}
        for u in self.red_known:
            w = self.red_intel_weak.get(u)
            nodes[u] = NodeIntel(self.net.pos[u], self.net.zone[u], self.net.kind[u], self.net.label[u],
                                 w, u in self.isolated)
        edges = {u: sorted(vs) for u, vs in self.red_known_edges.items()}
        gates = {}
        for u, vs in self.red_known_edges.items():
            for v in vs:
                e = frozenset((u, v))
                if e in self.net.gates:
                    gates[e] = e in self.open_gates
        return RedObservation(self.round, self.red_pos, frozenset(self.red_held), self.net.database,
                              self.net.pos[self.net.database], self.net.max_edge_len,
                              nodes, edges, frozenset(self.red_expanded), gates, list(self.red_events),
                              self.red_legal())

    def blue_observation(self):
        return BlueObservation(self.round, self.net, list(self.weakness), frozenset(self.patched),
                               frozenset(self.decoys),
                               dict(self.isolated), dict(self.immune), list(self.last_alerts),
                               list(self.blue_feedback), self.decoy_sprung, self.isolate_ready)

    # -- resolution --------------------------------------------------------
    def step(self, red_action, blue_actions):
        """Resolve one round. Blue's actions apply first, then Red's."""
        assert self.winner is None
        rng, net = self.rng, self.net
        self.red_events = []
        self.blue_feedback = []
        self.decoy_sprung = None
        events = []

        # 1. Blue
        ap = C.BLUE_AP
        applied = []
        for kind, target in blue_actions:
            cost = C.action_cost(kind, target, net.gateway)
            if cost > ap or not self.blue_can(kind, target):
                continue
            ap -= cost
            applied.append((kind, target))
            if kind == "monitor":
                self.monitored.add(target)
            elif kind == "patch":
                self.weakness[target] = round(max(C.PATCH_FLOOR, self.weakness[target] * C.PATCH_FACTOR), 3)
                self.patched.add(target)
            elif kind == "decoy":
                self.decoys.add(target)
            elif kind == "isolate":
                self.isolated[target] = C.ISOLATE_ROUNDS
                self.isolate_ready = self.round + C.ISOLATE_ROUNDS + C.ISOLATE_RECHARGE
                found = target in self.red_held or target == self.red_pos
                on_it = target == self.red_pos
                self._take_back(target)
                self.blue_feedback.append(("isolate", target, found))
                if found:
                    events.append(f"Blue isolated {net.label[target]} and cut Red off it")
                    self.red_events.append(("lost", target, "isolate"))
                    if on_it:
                        self.red_events.append(("hit", target))
            elif kind == "restore":
                if target == net.gateway and (self.round <= C.GATEWAY_GRACE or len(self.red_held) > 1):
                    # the gateway can only be sealed once Red holds nothing else
                    self.blue_feedback.append(("restore", target, False))
                    continue
                # restore cleans up nodes Red has left behind; it cannot pull Red off the
                # node it is standing on (that takes an isolate)
                found = target in self.red_held and target != self.red_pos
                if found:
                    self._take_back(target)
                    events.append(f"Blue restored {net.label[target]} from Red")
                    self.red_events.append(("lost", target, "restore"))
                self.blue_feedback.append(("restore", target, found))

        displaced = self._settle_red()
        if self.winner:
            self._finish_round(red_action, applied, "removed", [], events)
            return

        # 2. Red
        result = "cancelled"
        noise_at = None
        noise = 0.0
        if displaced:
            self.red_events.append(("displaced", self.red_pos))
        elif tuple(red_action) in [tuple(a) for a in self.red_legal()]:
            result, noise_at, noise = self._apply_red(red_action, events)
        else:
            result = "blocked"
            if len(red_action) > 1:
                self.red_events.append(("blocked", red_action[1]))

        # 3. Detect
        alerts = {}
        if noise_at is not None:
            mon = C.MONITOR_BOOST if net.zone[noise_at] in self.monitored else 1.0
            p = min(0.97, noise * net.sensitivity[noise_at] * mon)
            if rng.random() < p:
                alerts[noise_at] = (max(0.05, min(1.0, noise + 0.1 + rng.gauss(0, 0.12))), True)
        for u in range(net.n):
            if rng.random() < C.FALSE_ALARM:
                s = rng.uniform(0.05, 0.55)
                if u not in alerts or alerts[u][1] is False and alerts[u][0] < s:
                    alerts[u] = (s, False)
        alert_list = sorted(((u, round(s, 2), real) for u, (s, real) in alerts.items()), key=lambda a: -a[1])

        self._finish_round(red_action, applied, result, alert_list, events)

    def _apply_red(self, act, events):
        net, rng = self.net, self.rng
        kind = act[0]
        p = self.red_pos
        if kind == "scout":
            self._reveal_around(p, scouted=True)
            return "scouted", p, C.NOISE["scout"]
        v = act[1] if len(act) > 1 else net.database
        if kind == "capture":
            # each failed try teaches Red something about the node
            chance = 1.0 if v in self.decoys else min(0.95, self.weakness[v] + C.RETRY_BONUS * self.red_tries.get(v, 0))
            if rng.random() < chance:
                self.red_held.add(v)
                self.red_pos = v
                self.red_intel_weak.setdefault(v, round(self.weakness[v], 2))
                self._reveal_around(v, scouted=False)
                self.red_events.append(("captured", v))
                events.append(f"Red captured {net.label[v]}")
                self._check_decoy(v, events)
                return "captured", v, C.NOISE["capture"]
            self.red_tries[v] = self.red_tries.get(v, 0) + 1
            self.red_events.append(("failed", v))
            return "failed", v, C.NOISE["capture"]
        if kind == "unlock":
            # forcing a zone border: the gate opens and Red takes the node behind it
            chance = 1.0 if v in self.decoys else min(0.95, self.weakness[v] * C.UNLOCK_SUCCESS
                                                      + C.RETRY_BONUS * self.red_tries.get(v, 0))
            if rng.random() < chance:
                self.open_gates.add(frozenset((p, v)))
                self.red_held.add(v)
                self.red_pos = v
                self.red_intel_weak.setdefault(v, round(self.weakness[v], 2))
                self._reveal_around(v, scouted=False)
                self.red_events.append(("unlocked", v))
                events.append(f"Red unlocked {net.label[p]} > {net.label[v]} into the {C.ZONE_NAMES[net.zone[v]]}")
                self._check_decoy(v, events)
                return "unlocked", v, C.NOISE["unlock"]
            self.red_tries[v] = self.red_tries.get(v, 0) + 1
            self.red_events.append(("failed", v))
            return "unlock failed", v, C.NOISE["unlock"]
        if kind == "advance":
            self.red_pos = v
            self._check_decoy(v, events)
            return "advanced", v, C.NOISE["advance"]
        if kind == "claim":
            db = net.database
            chance = C.CLAIM_BASE + C.CLAIM_SCALE * self.weakness[db]
            if rng.random() < chance:
                self.winner, self.reason = "red", "Red claimed the database"
                self.red_held.add(db)
                self.red_pos = db
                events.append("Red claimed the database")
                return "claimed", db, C.NOISE["claim"]
            self.red_events.append(("claim_failed", db))
            return "claim failed", db, C.NOISE["claim"]
        return "illegal", None, 0.0

    def _check_decoy(self, v, events):
        if v in self.decoys:
            self.decoys.discard(v)
            self.decoy_sprung = v
            self.red_events.append(("decoy", v))
            self.red_intel_weak[v] = round(self.weakness[v], 2)
            events.append(f"Red walked into the decoy on {self.net.label[v]}")

    def _take_back(self, v):
        self.red_held.discard(v)

    def _settle_red(self):
        """After Blue acts: if Red lost the node it stands on, it falls back to its nearest held node."""
        if not self.red_held:
            self.winner, self.reason = "blue", "Red was removed from the network"
            return True
        if self.red_pos in self.red_held:
            return False
        dist = {self.red_pos: 0}
        q = deque([self.red_pos])
        while q:
            u = q.popleft()
            if u in self.red_held:
                self.red_pos = u
                return True
            for v in self.net.adj[u]:
                if v not in dist:
                    dist[v] = dist[u] + 1
                    q.append(v)
        self.red_pos = next(iter(self.red_held))
        return True

    def _finish_round(self, red_action, applied, result, alerts, events):
        self.history.append(RoundRecord(self.round, tuple(red_action), applied, result, alerts, events))
        self.last_alerts = [(u, s) for u, s, _ in alerts]
        self.monitored = set()
        for d in (self.isolated, self.immune):
            for u in list(d):
                d[u] -= 1
                if d[u] <= 0:
                    del d[u]
                    if d is self.isolated:
                        self.immune[u] = C.ISOLATE_COOLDOWN
        if self.winner is None:
            if self.round >= C.MAX_ROUNDS:
                self.winner, self.reason = "blue", "Blue held out for 40 rounds"
            else:
                self.round += 1
