"""Information-Set Monte Carlo Tree Search for Red (outline section 05, part 2).

Red cannot see decoys, patches or which zones Blue watches. Each iteration
therefore samples ("determinises") one complete hidden state that fits what
Red has seen, using the opponent model's probabilities, and then runs a normal
MCTS iteration inside that sample. Statistics are shared across samples, so
the chosen move is the one that works best on average over everything Blue
might be hiding (single-observer IS-MCTS with availability counts).

The simulation runs on the part of the map Red knows. Blue is played by a fast
rollout policy that isolates the node with the most alert "heat".
"""

import math
import random
import time

from engine import config as C
from agents.red.astar import heuristic, cost_to_go, frontier_cost, GOAL, UNKNOWN_WEAKNESS

UCT_C = 1.4


class SimState:
    __slots__ = ("pos", "held", "opened", "heat", "isolated", "decoys", "weak", "mon_p",
                 "spotted", "claimed", "info_bonus", "depth", "fog")

    def copy(self):
        s = SimState.__new__(SimState)
        s.pos, s.held, s.opened = self.pos, set(self.held), set(self.opened)
        s.heat, s.isolated = dict(self.heat), dict(self.isolated)
        s.decoys, s.weak, s.mon_p = set(self.decoys), self.weak, self.mon_p
        s.spotted, s.claimed, s.info_bonus, s.depth = self.spotted, self.claimed, self.info_bonus, self.depth
        s.fog = self.fog
        return s


class TreeNode:
    __slots__ = ("action", "parent", "children", "n", "w", "avail")

    def __init__(self, action=None, parent=None):
        self.action, self.parent = action, parent
        self.children = {}
        self.n, self.w, self.avail = 0, 0.0, 1


class ISMCTS:
    def __init__(self, iterations=1000, time_limit=0.2, horizon=9, rng=None):
        self.iterations = iterations
        self.time_limit = time_limit
        self.horizon = horizon
        self.rng = rng or random.Random()

    # -- determinisation ----------------------------------------------------
    def determinise(self, obs, model, seen):
        rng = self.rng
        s = SimState()
        s.pos, s.held = obs.pos, set(obs.held)
        s.opened = {g for g, is_open in obs.gates.items() if is_open}
        s.heat = {obs.pos: 0.6 * model.recent_caught} if model.recent_caught > 0.3 else {}
        s.isolated = {u: 2 for u, info in obs.nodes.items() if info.isolated}
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
        s.mon_p = [model.p_monitor(z) for z in range(3)]
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
        rng = self.rng
        s.depth += 1
        # Blue's rollout policy acts first: isolate the hottest node, watch its zone ...
        monitored = [rng.random() < p for p in s.mon_p]
        hot = max(s.heat, key=s.heat.get) if s.heat else None
        if hot is not None and s.heat[hot] > 0.35 and not s.isolated and hot != obs.database and \
                obs.nodes[hot].kind != "gateway" and rng.random() < self.p_hunt:
            s.isolated[hot] = 2
            s.heat[hot] = 0.0
            s.held.discard(hot)
            monitored[obs.nodes[hot].zone] = True
            if hot == s.pos:
                s.fog = 0
                near = [v for v in obs.edges.get(hot, ()) if v in s.held]
                s.pos = near[0] if near else next(iter(s.held), s.pos)
                self._tick(s)
                return   # Red's action is cancelled this round
        # ... or it reads Red's obvious next step off the route and blocks it
        elif not s.isolated and len(act) > 1 and act[1] == self.nxt.get(s.pos) and \
                act[1] != obs.database and rng.random() < self.p_block:
            s.isolated[act[1]] = 2
            self._tick(s)
            return
        self._tick(s)

        kind = act[0]
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
                    s.spotted = True
                    s.heat[v] = s.heat.get(v, 0) + 1.5
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
                s.spotted = True
                s.heat[act[1]] = s.heat.get(act[1], 0) + 1.5
        elif kind == "claim":
            noise_at = obs.database
            if rng.random() < C.CLAIM_BASE + C.CLAIM_SCALE * s.weak[obs.database]:
                s.claimed = True

        for u in list(s.heat):
            s.heat[u] *= 0.6
        zone = obs.nodes[noise_at].zone if noise_at in obs.nodes else 2
        sens = model.sensitivity(zone) / (1 + (C.MONITOR_BOOST - 1) * model.p_monitor(zone))
        p = noise * sens * (C.MONITOR_BOOST if monitored[zone] else 1.0)
        if rng.random() < p:
            s.heat[noise_at] = s.heat.get(noise_at, 0) + noise + 0.1

    @staticmethod
    def _tick(s):
        for u in list(s.isolated):
            s.isolated[u] -= 1
            if s.isolated[u] <= 0:
                del s.isolated[u]

    def reward(self, obs, s, h0):
        if s.claimed:
            return 1.0 - 0.025 * s.depth     # sooner is better
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
    def search(self, obs, model, candidates, lam=1.0):
        seen = [0, 0, 0]
        for info in obs.nodes.values():
            seen[info.zone] += 1
        self.ctg, self.nxt = cost_to_go(obs, model, lam)
        self.p_hunt = model.p_hunt()
        self.p_block = model.p_block()
        h0 = max(1.0, self.ctg.get(obs.pos, 10.0) + 2.0)
        root = TreeNode()
        cand = set(candidates)
        t0 = time.perf_counter()
        it = 0
        while it < self.iterations and time.perf_counter() - t0 < self.time_limit:
            it += 1
            s = self.determinise(obs, model, seen)
            node = root
            # selection / expansion
            while not s.claimed and s.depth < self.horizon:
                acts = self.legal(obs, s)
                if node is root:
                    acts = [a for a in acts if a in cand] or acts
                for a in acts:
                    if a in node.children:
                        node.children[a].avail += 1
                untried = [a for a in acts if a not in node.children]
                if untried:
                    a = self.rng.choice(untried)
                    child = TreeNode(a, node)
                    node.children[a] = child
                    self.step(obs, s, a, model)
                    node = child
                    break
                logn = math.log(max(1, node.n))
                best, best_u = None, -math.inf
                for a in acts:
                    c = node.children[a]
                    u = c.w / c.n + UCT_C * math.sqrt(math.log(max(1, c.avail)) / c.n)
                    if u > best_u:
                        best, best_u = c, u
                self.step(obs, s, best.action, model)
                node = best
            # rollout
            while not s.claimed and s.depth < self.horizon:
                self.step(obs, s, self.rollout_action(obs, s, self.legal(obs, s)), model)
            r = self.reward(obs, s, h0)
            while node is not None:
                node.n += 1
                node.w += r
                node = node.parent
        stats = sorted(((c.action, c.n, c.w / c.n) for c in root.children.values()), key=lambda t: -t[1])
        return stats, it, time.perf_counter() - t0
