"""Stackelberg minimax: choose the defence (outline section 06, part 3).

The defender commits first and the intruder reacts. Blue builds candidate
allocations of its 3 action points over the highest-threat nodes and, for
each one, assumes Red answers with its best response:

    choose argmax_a  sum_p belief(p) * min_r U_Blue(a, p, r)

where p ranges over Blue's most likely Red positions. The search looks two
rounds ahead (Blue, Red, Blue, Red) with alpha-beta pruning in the min/max
layers. Red's reply set is a fast A*-style best response on Blue's full map:
step to the neighbours with the cheapest remaining route to the database.
"""

import heapq
import itertools
import math

from engine import config as C

GAMMA = 0.6


class PlanState:
    """Blue's hypothetical view of the board inside the search."""
    __slots__ = ("weak", "isolated", "decoys", "monitored", "hit")

    def __init__(self, weak, isolated, decoys, monitored=(), hit=0.0):
        self.weak, self.isolated, self.decoys = weak, isolated, decoys
        self.monitored, self.hit = frozenset(monitored), hit

    def key(self):
        return (self.isolated, tuple(round(w, 3) for w in self.weak))


class Stackelberg:
    def __init__(self, net, weights):
        self.net = net
        self.w = weights
        self._dist_cache = {}
        self.evaluated = 0

    # -- Red's remaining route cost on Blue's map -------------------------------
    def dist_to_db(self, st):
        key = st.key()
        d = self._dist_cache.get(key)
        if d is not None:
            return d
        net = self.net
        d = [math.inf] * net.n
        d[net.database] = 0.0
        pq = [(0.0, net.database)]
        while pq:
            du, u = heapq.heappop(pq)
            if du > d[u]:
                continue
            for v in net.adj[u]:
                if v in st.isolated:
                    continue
                # cost for Red to step v -> u: expected tries to take u, plus a gate
                c = 1.0 / max(st.weak[u], 0.08) if u != net.database else 1.5
                if net.is_gate(u, v):
                    c += 0.4
                if du + c < d[v]:
                    d[v] = du + c
                    heapq.heappush(pq, (d[v], v))
        if len(self._dist_cache) > 4000:
            self._dist_cache.clear()
        self._dist_cache[key] = d
        return d

    # -- applying actions -----------------------------------------------------------
    def apply(self, st, alloc, red_pos=None):
        weak = list(st.weak)
        isolated, decoys, monitored = set(st.isolated), set(st.decoys), set()
        hit = 0.0
        for kind, t in alloc:
            if kind == "patch":
                weak[t] *= C.PATCH_FACTOR
            elif kind == "isolate":
                isolated.add(t)
                if red_pos is not None and t == red_pos:
                    hit += 1.0

            elif kind == "decoy":
                decoys.add(t)
            elif kind == "monitor":
                monitored.add(t)
        return PlanState(weak, frozenset(isolated), frozenset(decoys), monitored, hit)

    def replies(self, st, p):
        net = self.net
        d = self.dist_to_db(st)
        moves = [q for q in net.adj[p] if q not in st.isolated]
        moves.sort(key=lambda q: d[q])
        out = [("move", q) for q in moves[:3]]
        out.append(("stay", p))
        return out

    def utility(self, st, p, r):
        """Blue's payoff for one round in which Red at p plays reply r."""
        net, w = self.net, self.w
        d = self.dist_to_db(st)
        dmax = max(x for x in d if x != math.inf) or 1.0
        if st.hit:
            return w["catch"] * st.hit + w["path"] * min(1.0, (d[p] if d[p] != math.inf else dmax) / dmax)
        q = r[1]
        mon = C.MONITOR_BOOST if net.zone[q] in st.monitored else 1.0
        if r[0] == "stay":
            pd = C.NOISE["scout"] * net.sensitivity[p] * mon
            dp = d[p] if d[p] != math.inf else dmax
            return w["path"] * dp / dmax + w["detect"] * pd
        if q == net.database:
            cap = C.CLAIM_BASE + C.CLAIM_SCALE * st.weak[q]
            return -w["value"] * 3.0 * cap + w["detect"] * C.NOISE["claim"] * net.sensitivity[q] * mon
        cap = 1.0 if q in st.decoys else st.weak[q]
        pd = min(1.0, C.NOISE["capture"] * net.sensitivity[q] * mon)
        if q in st.decoys:
            pd = 1.0
        dq = d[q] if d[q] != math.inf else dmax
        dp = d[p] if d[p] != math.inf else dmax
        dist_after = cap * dq + (1 - cap) * dp
        u = w["path"] * dist_after / dmax + w["detect"] * pd - w["value"] * net.value[q] * cap
        if q in st.decoys:
            u += w["decoy"]
        return u

    def advance(self, st, p, r):
        """State and likely Red position one round later."""
        q = r[1]
        if r[0] == "move" and q != self.net.database:
            cap = 1.0 if q in st.decoys else st.weak[q]
            p2 = q if cap >= 0.5 else p
        else:
            p2 = p
        nxt = PlanState(st.weak, st.isolated, st.decoys - {q}, (), 0.0)
        return nxt, p2

    # -- minimax with alpha-beta -------------------------------------------------
    def red_min(self, st, p, depth, alpha, beta, cand_fn):
        best = math.inf
        for r in self.replies(st, p):
            self.evaluated += 1
            u = self.utility(st, p, r)
            if st.hit:
                return u
            if depth > 1:
                st2, p2 = self.advance(st, p, r)
                u += GAMMA * self.blue_max(st2, p2, depth - 1, -math.inf, math.inf, cand_fn)
            best = min(best, u)
            beta = min(beta, best)
            if best <= alpha:
                break
        return best

    def blue_max(self, st, p, depth, alpha, beta, cand_fn):
        best = -math.inf
        for alloc in cand_fn(st, p):
            v = self.red_min(self.apply(st, alloc, p), p, depth, alpha, beta, cand_fn)
            best = max(best, v)
            alpha = max(alpha, best)
            if best >= beta:
                break
        return best

    def lookahead_allocs(self, st, p):
        """Small allocation set for the second Blue move, when p is assumed known."""
        net = self.net
        d = self.dist_to_db(st)
        nxt = sorted((q for q in net.adj[p] if q not in st.isolated), key=lambda q: d[q])[:2]
        acts = []
        if p not in (net.gateway, net.database) and p not in st.isolated:
            acts.append(("isolate", p))
        for q in nxt:
            if q not in (net.gateway, net.database):
                acts.append(("isolate", q))
            acts.append(("patch", q))
        acts.append(("monitor", net.zone[p]))
        return _allocations(acts, C.BLUE_AP, net.gateway)[:6]

    def choose(self, base, positions, root_allocs, depth=2):
        """positions: [(node, prob)]. Returns (best_alloc, score, scored list)."""
        self.evaluated = 0
        scored = []
        for alloc in root_allocs:
            total = 0.0
            for p, bp in positions:
                st = self.apply(base, alloc, p)
                total += bp * self.red_min(st, p, depth, -math.inf, math.inf, self.lookahead_allocs)
            scored.append((total, alloc))
        scored.sort(key=lambda t: -t[0])
        if not scored:
            return [], 0.0, []
        return scored[0][1], scored[0][0], scored


def _allocations(actions, ap, gateway=None):
    """All sets of distinct actions with total cost <= ap, larger spends first."""
    out = []
    uniq = list(dict.fromkeys(actions))
    for k in (3, 2, 1):
        for combo in itertools.combinations(uniq, k):
            cost = sum(C.action_cost(a[0], a[1], gateway) for a in combo)
            targets = [a[1] for a in combo if a[0] != "monitor"]
            if cost <= ap and len(targets) == len(set(targets)):
                out.append(list(combo))
    out.sort(key=lambda al: -sum(C.action_cost(a[0], a[1], gateway) for a in al))
    return out


allocations = _allocations
