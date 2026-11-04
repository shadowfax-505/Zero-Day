"""Information-Set Monte Carlo Tree Search for Red (outline section 05, part 2).

Red cannot see decoys, patches or which zones Blue watches. Each iteration
therefore samples ("determinises") one complete hidden state that fits what
Red has seen, using the opponent model's probabilities, and then runs a normal
MCTS iteration inside that sample. Statistics are shared across samples, so
the chosen move is the one that works best on average over everything Blue
might be hiding (single-observer IS-MCTS with availability counts).

The simulation runs on the part of the map Red knows. Blue is played by a fast
rollout policy learned from logged Red AI vs Blue AI matches
(tuning/learn_blue_policy.py): how often Blue isolates Red's node when Red has
just been noisy, blocks Red's obvious next step, patches or baits it, restores
nodes Red left behind and watches the zone Red is heading into. The opponent
model scales those numbers up or down with what Blue has done in this match.
"""

import json
import math
import os
import random
import time

from engine import config as C
from agents.red.astar import heuristic, cost_to_go, frontier_cost, GOAL, UNKNOWN_WEAKNESS
from agents.red.opponent_model import ZONE_SENSITIVITY

UCT_C = 1.4

POLICY_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "tuning", "blue_policy.json")
DEFAULT_POLICY = {
    "iso_pos|hot": 0.48, "iso_pos|cold": 0.30,
    "iso_next|route_hot": 0.29, "iso_next|route_cold": 0.12, "iso_next|off_route": 0.11,
    "patch_next|route": 0.33, "patch_next|off_route": 0.23,
    "decoy_next|route": 0.03, "decoy_next|off_route": 0.01,
    "restore_held": 0.12, "monitor_zone|hot": 0.79, "monitor_zone|cold": 0.75,
}


VALUE_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "tuning", "red_value.json")
VALUE_FEATURES = ["bias", "cost_left", "rounds_left", "pace", "held", "heard"]


def value_features(cost_left, rounds_left, held, hot):
    """What the leaf value looks at. Everything here is something Red knows."""
    rl = max(1, rounds_left)
    return [1.0, cost_left / 10.0, rl / 40.0, min(3.0, cost_left / rl), min(held, 8) / 8.0, float(hot)]


def load_value():
    try:
        with open(VALUE_FILE) as f:
            d = json.load(f)
        if d.get("features") == VALUE_FEATURES:
            return [float(x) for x in d["weights"]]
    except (OSError, ValueError, KeyError):
        pass
    return None


def load_policy():
    try:
        with open(POLICY_FILE) as f:
            p = json.load(f)["p"]
        return {k: float(p.get(k, v)) for k, v in DEFAULT_POLICY.items()}
    except (OSError, ValueError, KeyError):
        return dict(DEFAULT_POLICY)


class SimState:
    __slots__ = ("pos", "held", "opened", "hot", "isolated", "iso_wait", "decoys", "weak", "patched",
                 "spotted", "spotted_now", "claimed", "info_bonus", "depth", "fog")

    def copy(self):
        s = SimState.__new__(SimState)
        for k in SimState.__slots__:
            setattr(s, k, getattr(self, k, None))
        s.held, s.opened, s.isolated = set(self.held), set(self.opened), dict(self.isolated)
        s.decoys, s.patched = set(self.decoys), set(self.patched)
        return s


class TreeNode:
    __slots__ = ("action", "parent", "children", "n", "w", "avail")

    def __init__(self, action=None, parent=None):
        self.action, self.parent = action, parent
        self.children = {}
        self.n, self.w, self.avail = 0, 0.0, 1


class ISMCTS:
    def __init__(self, iterations=1000, time_limit=0.2, horizon=9, rng=None, policy=None):
        self.iterations = iterations
        self.time_limit = time_limit
        self.horizon = horizon
        self.rng = rng or random.Random()
        self.pol = policy or load_policy()
        self.value_w = load_value()
        self.p_hot = 0.3

    # -- determinisation ----------------------------------------------------
    def determinise(self, obs, model, seen):
        rng = self.rng
        s = SimState()
        s.pos, s.held = obs.pos, set(obs.held)
        s.opened = {g for g, is_open in obs.gates.items() if is_open}
        # was Red's last action heard? Red cannot see alerts, so sample it
        s.hot = rng.random() < self.p_hot
        s.isolated = {u: 2 for u, info in obs.nodes.items() if info.isolated}
        # Blue's isolate recharges after each use; Red only sees isolations while they last
        s.iso_wait = (C.ISOLATE_ROUNDS + C.ISOLATE_RECHARGE) if s.isolated else \
            (0 if rng.random() < 0.6 else rng.randint(1, C.ISOLATE_RECHARGE))
        s.patched = set()
        s.decoys = set()
        weak = {}
        for u, info in obs.nodes.items():
            if info.weakness is None:
                w = rng.uniform(0.3, 0.7)
            else:
                w = info.weakness
                if u not in obs.held and rng.random() < 0.15:
                    w *= 0.5      # Blue may have patched it since Red looked
            weak[u] = w
            if (u not in obs.held and u != obs.database and info.kind != "gateway"
                    and len(s.decoys) < C.MAX_DECOYS and rng.random() < model.p_decoy(u, info, seen[info.zone])):
                s.decoys.add(u)
        weak.setdefault(obs.database, UNKNOWN_WEAKNESS * (0.5 if rng.random() < 0.3 else 1.0))
        s.weak = weak
        s.spotted, s.claimed, s.info_bonus, s.depth = False, False, 0.0, 0
        s.fog = 0
        return s

    # -- rules inside the sample -------------------------------------------
    def legal(self, obs, s):
        acts = [("scout",)]
        if s.pos not in obs.expanded or s.fog:
            # past the edge of Red's map: abstract "push on into the fog" steps
            acts.append(("fog",))
            if s.fog:
                return acts
        for v in obs.edges.get(s.pos, ()):
            if v in s.isolated:
                continue
            if v == obs.database:
                acts.append(("claim",))
            elif v in s.held:
                acts.append(("advance", v))
            elif frozenset((s.pos, v)) in obs.gates and frozenset((s.pos, v)) not in s.opened:
                acts.append(("unlock", v))
            else:
                acts.append(("capture", v))
        return acts

    def step(self, obs, s, act, model):
        rng, pol = self.rng, self.pol
        s.depth += 1
        # -- Blue moves first, sampled from the learned policy --------------------
        target = act[1] if len(act) > 1 else (obs.database if act[0] == "claim" else None)
        on_route = target is not None and target in self._obvious(obs, s.pos)
        s.iso_wait -= 1
        self._tick(s)
        if s.iso_wait <= 0 and not s.isolated:
            if s.pos != self.gateway and rng.random() < pol["iso_pos|hot" if s.hot else "iso_pos|cold"] * self.k_hunt:
                # Blue cuts Red off the node it stands on: Red falls back, its action is lost
                s.isolated[s.pos] = C.ISOLATE_ROUNDS
                s.iso_wait = C.ISOLATE_ROUNDS + C.ISOLATE_RECHARGE
                s.held.discard(s.pos)
                s.fog = 0
                near = [v for v in obs.edges.get(s.pos, ()) if v in s.held]
                s.pos = near[0] if near else next(iter(s.held), s.pos)
                s.hot = False
                return
            if target is not None and target != obs.database:
                key = ("iso_next|route_hot" if s.hot else "iso_next|route_cold") if on_route else "iso_next|off_route"
                if rng.random() < pol[key] * self.k_block:
                    # Blue guessed Red's step and closed it first
                    s.isolated[target] = C.ISOLATE_ROUNDS
                    s.iso_wait = C.ISOLATE_ROUNDS + C.ISOLATE_RECHARGE
                    s.hot = False
                    return
        if target is not None and target not in s.patched and \
                rng.random() < pol["patch_next|route" if on_route else "patch_next|off_route"]:
            s.patched.add(target)
            s.weak = dict(s.weak)
            s.weak[target] = max(C.PATCH_FLOOR, s.weak.get(target, UNKNOWN_WEAKNESS) * C.PATCH_FACTOR)
        if target is not None and target not in s.held and target != obs.database and \
                rng.random() < pol["decoy_next|route" if on_route else "decoy_next|off_route"]:
            s.decoys.add(target)
        if len(s.held) > 2 and rng.random() < pol["restore_held"]:
            behind = [v for v in s.held if v != s.pos and v != self.gateway]
            if behind:
                s.held.discard(rng.choice(behind))
        watched = target is not None and target in obs.nodes and \
            rng.random() < pol["monitor_zone|hot" if s.hot else "monitor_zone|cold"]

        kind = act[0]
        s.spotted_now = False
        noise_at, noise = s.pos, C.NOISE.get(kind, C.NOISE["capture"])
        if kind == "fog":
            left = heuristic(obs, s.pos) - s.fog + 0.5 * (2 - obs.nodes[s.pos].zone)
            if left <= 1.0:
                noise = C.NOISE["claim"]
                if rng.random() < C.CLAIM_BASE + C.CLAIM_SCALE * s.weak[obs.database] * 0.8:
                    s.claimed = True
            elif rng.random() < 0.5:
                s.fog += 1
        elif kind == "scout":
            unknown = sum(1 for v in obs.edges.get(s.pos, ()) if obs.nodes[v].weakness is None)
            if unknown and s.depth == 1:
                s.info_bonus += 0.006 * unknown
        elif kind == "capture":
            v = act[1]
            noise_at = v
            if v in s.decoys or rng.random() < s.weak.get(v, UNKNOWN_WEAKNESS):
                s.held.add(v)
                s.pos = v
                if v in s.decoys:
                    s.decoys.discard(v)
                    s.spotted = s.spotted_now = True
        elif kind == "unlock":
            v = act[1]
            noise_at = v
            if v in s.decoys or rng.random() < s.weak.get(v, UNKNOWN_WEAKNESS) * C.UNLOCK_SUCCESS:
                s.opened.add(frozenset((s.pos, v)))
                s.held.add(v)
                s.pos = v
        elif kind == "advance":
            s.pos = act[1]
            noise_at = act[1]
            if act[1] in s.decoys:
                s.decoys.discard(act[1])
                s.spotted = s.spotted_now = True
        elif kind == "claim":
            noise_at = obs.database
            if rng.random() < C.CLAIM_BASE + C.CLAIM_SCALE * s.weak[obs.database]:
                s.claimed = True

        zone = obs.nodes[noise_at].zone if noise_at in obs.nodes else 2
        sens = ZONE_SENSITIVITY[zone] * (C.MONITOR_BOOST if watched else 1.0)
        s.hot = s.spotted_now or rng.random() < noise * sens

    def _obvious(self, obs, u):
        """The two known neighbours of u nearest the database: Blue's best guess at Red's next step."""
        got = self.obvious.get(u)
        if got is None:
            got = set(sorted(obs.edges.get(u, ()), key=lambda v: heuristic(obs, v))[:2])
            self.obvious[u] = got
        return got

    @staticmethod
    def _tick(s):
        for u in list(s.isolated):
            s.isolated[u] -= 1
            if s.isolated[u] <= 0:
                del s.isolated[u]

    def reward(self, obs, s, h0):
        if s.claimed:
            return 1.0 - 0.025 * s.depth     # sooner is better
        if self.value_w is not None:
            # learned leaf value: P(Red wins) from where the rollout stopped
            left = max(0.0, self.ctg.get(s.pos, h0) - 2.0 * s.fog)
            x = value_features(left, C.MAX_ROUNDS - obs.round - s.depth, len(s.held), s.hot or s.spotted)
            z = sum(a * b for a, b in zip(self.value_w, x))
            return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
        if len(s.held) == 1 and len(obs.held) > 1:
            return 0.05      # pushed all the way back to the gateway
        left = max(0.0, self.ctg.get(s.pos, h0) - 2.0 * s.fog)
        progress = 1.0 - min(1.0, left / h0)
        r = 0.12 + 0.55 * progress + 0.10 * min(len(s.held), 6) / 6 + s.info_bonus
        if s.spotted:
            r -= 0.15
        return max(0.0, min(0.95, r))

    def rollout_action(self, obs, s, acts):
        rng = self.rng
        for a in acts:
            if a[0] == "claim":
                return a
        if ("fog",) in acts and (s.fog or self.nxt.get(s.pos) == GOAL) and rng.random() < 0.85:
            return ("fog",)
        # follow A*'s route with some randomness
        v = self.nxt.get(s.pos)
        if v is not None and v != GOAL and rng.random() < 0.8:
            for a in acts:
                if len(a) > 1 and a[1] == v or (a[0] == "claim" and v == obs.database):
                    return a
        if rng.random() < 0.5:
            best, best_h = None, math.inf
            for a in acts:
                if len(a) < 2:
                    continue
                hv = heuristic(obs, a[1]) + (0.5 if a[0] == "unlock" else 0.0) + rng.random() * 0.6
                if hv < best_h:
                    best, best_h = a, hv
            if best:
                return best
        return rng.choice(acts)

    # -- search --------------------------------------------------------------
    def search(self, obs, model, candidates, lam=1.0, p_hot=0.3, gateway=None):
        seen = [0, 0, 0]
        for info in obs.nodes.values():
            seen[info.zone] += 1
        self.ctg, self.nxt = cost_to_go(obs, model, lam)
        # the learned numbers describe the Blue AI; scale them by how this Blue has played so far
        self.k_hunt = min(1.6, max(0.5, model.p_hunt() / 0.45))
        self.k_block = min(1.6, max(0.5, model.p_block() / 0.15))
        self.p_hot = p_hot
        self.gateway = gateway if gateway is not None else obs.pos
        self.obvious = {}
        h0 = max(1.0, self.ctg.get(obs.pos, 10.0) + 2.0)
        root = TreeNode()
        cands = list(dict.fromkeys(candidates))
        for a in cands:
            root.children[a] = TreeNode(a, root)
        rewards = {a: [] for a in cands}
        master, sim = self.rng, random.Random()
        t0 = time.perf_counter()
        it = 0
        # Paired sampling: every candidate first move is tried on the SAME sampled
        # hidden state with the same random numbers, so the comparison between
        # moves is not drowned by the luck of the draw (common random numbers).
        while it < self.iterations and time.perf_counter() - t0 < self.time_limit:
            seed = master.getrandbits(48)
            sim.seed(seed)
            self.rng = sim
            s0 = self.determinise(obs, model, seen)
            for a in cands:
                it += 1
                sim.seed(seed + 1)
                s = s0.copy()
                node = root.children[a]
                self.step(obs, s, a, model)
                # selection / expansion below the first move (UCT with availability counts)
                while not s.claimed and s.depth < self.horizon:
                    acts = self.legal(obs, s)
                    for b in acts:
                        if b in node.children:
                            node.children[b].avail += 1
                    untried = [b for b in acts if b not in node.children]
                    if untried:
                        b = sim.choice(untried)
                        child = TreeNode(b, node)
                        node.children[b] = child
                        self.step(obs, s, b, model)
                        node = child
                        break
                    best, best_u = None, -math.inf
                    for b in acts:
                        c = node.children[b]
                        u = c.w / c.n + UCT_C * math.sqrt(math.log(max(1, c.avail)) / c.n)
                        if u > best_u:
                            best, best_u = c, u
                    self.step(obs, s, best.action, model)
                    node = best
                # rollout
                while not s.claimed and s.depth < self.horizon:
                    self.step(obs, s, self.rollout_action(obs, s, self.legal(obs, s)), model)
                r = self.reward(obs, s, h0)
                rewards[a].append(r)
                while node is not None:
                    node.n += 1
                    node.w += r
                    node = node.parent
        self.rng = master
        k = min(len(v) for v in rewards.values()) if rewards else 0
        stats = sorted(((a, len(rewards[a]), sum(rewards[a]) / len(rewards[a]))
                        for a in cands if rewards[a]), key=lambda t: -t[2])
        self.samples = k
        self.rewards = rewards
        return stats, it, time.perf_counter() - t0

    def paired_gain(self, a, base):
        """Mean and standard error of reward(a) - reward(base) over the shared samples."""
        ra, rb = self.rewards.get(a, []), self.rewards.get(base, [])
        k = min(len(ra), len(rb))
        if k < 2:
            return 0.0, math.inf
        d = [x - y for x, y in zip(ra[:k], rb[:k])]
        m = sum(d) / k
        var = sum((x - m) ** 2 for x in d) / (k - 1)
        return m, math.sqrt(var / k)
