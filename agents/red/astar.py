"""A* route planning for Red (outline section 05, part 1).

    cost(u -> v) = 1 + lambda * risk(v)
    risk(v)      = sensitivity(v) * (1 - weakness(v)) + P_decoy(v)

Red only knows part of the map, so every node whose links are not all known
yet (a "frontier" node) gets a virtual link straight to the database. Its cost
is the straight-line hop estimate, so A* happily plans "into the fog" when the
known map has no route yet.

h(v) = straight-line distance to the database / longest link length. Every
link is at most that long, so h never overestimates the number of hops left,
every step costs at least 1, and A* stays optimal.
"""

import heapq
import math

UNKNOWN_WEAKNESS = 0.5
GOAL = -1   # virtual goal id used for frontier links


def heuristic(obs, u):
    x, y = obs.nodes[u].pos
    dx, dy = x - obs.db_pos[0], y - obs.db_pos[1]
    return math.hypot(dx, dy) / obs.max_edge_len


def node_risk(obs, model, v, seen_per_zone):
    info = obs.nodes[v]
    if v in obs.held:
        return 0.2 * model.sensitivity(info.zone)
    w = model.weakness(v, info, UNKNOWN_WEAKNESS)
    return model.sensitivity(info.zone) * (1 - w) + model.p_decoy(v, info, seen_per_zone[info.zone])


def step_cost(obs, model, u, v, lam, seen_per_zone):
    c = 1.0 + lam * node_risk(obs, model, v, seen_per_zone)
    gate = frozenset((u, v))
    if gate in obs.gates and not obs.gates[gate]:
        c += lam * 0.6 * model.sensitivity(obs.nodes[v].zone) + 0.2  # unlock is louder
    if v not in obs.held and v != obs.database:
        w = model.weakness(v, obs.nodes[v], UNKNOWN_WEAKNESS)
        c += (1.0 / max(w, 0.15)) - 1.0                                    # expected retries
    return c


def plan(obs, model, lam=1.0, start=None):
    """Return (path, cost, reaches_db). path starts at Red's node; if it ends
    at a frontier node the rest of the route is still in the fog."""
    start = obs.pos if start is None else start
    seen = [0, 0, 0]
    for info in obs.nodes.values():
        seen[info.zone] += 1
    g = {start: 0.0}
    prev = {start: None}
    openq = [(heuristic(obs, start), 0.0, start)]
    closed = set()
    while openq:
        f, gu, u = heapq.heappop(openq)
        if u == GOAL or u == obs.database:
            path, x = [], (prev[GOAL] if u == GOAL else u)
            while x is not None:
                path.append(x)
                x = prev[x]
            return path[::-1], gu, u == obs.database
        if u in closed:
            continue
        closed.add(u)
        for v in obs.edges.get(u, ()):
            if v not in obs.nodes or obs.nodes[v].isolated:
                continue
            ng = gu + step_cost(obs, model, u, v, lam, seen)
            if ng < g.get(v, math.inf):
                g[v] = ng
                prev[v] = u
                heapq.heappush(openq, (ng + heuristic(obs, v), ng, v))
        if u not in obs.expanded:
            ng = gu + frontier_cost(obs, u, lam)
            if ng < g.get(GOAL, math.inf):
                g[GOAL] = ng
                prev[GOAL] = u
                heapq.heappush(openq, (ng, ng, GOAL))
    return [start], math.inf, False


def frontier_cost(obs, u, lam):
    """Optimistic cost from a frontier node to the database through the fog."""
    hops = max(1.0, math.ceil(heuristic(obs, u)))
    gates_left = 2 - obs.nodes[u].zone
    return hops * (1.3 + lam * 0.45) + gates_left * 1.5 + 1.0


def cost_to_go(obs, model, lam=1.0):
    """Backward Dijkstra from the database (and the fog) over Red's known map.
    Returns (cost, next_node) for every known node: the same costs A* uses, so
    IS-MCTS rollouts follow A*'s route and score progress along it."""
    seen = [0, 0, 0]
    for info in obs.nodes.values():
        seen[info.zone] += 1
    ctg, nxt = {}, {}
    pq = []
    if obs.database in obs.nodes:
        ctg[obs.database] = 0.0
        pq.append((0.0, obs.database))
    for u in obs.nodes:
        if u not in obs.expanded and u != obs.database and not obs.nodes[u].isolated:
            c = frontier_cost(obs, u, lam)
            if c < ctg.get(u, math.inf):
                ctg[u] = c
                nxt[u] = GOAL
                pq.append((c, u))
    heapq.heapify(pq)
    done = set()
    while pq:
        cv, v = heapq.heappop(pq)
        if v in done:
            continue
        done.add(v)
        for u in obs.edges.get(v, ()):
            if u not in obs.nodes or obs.nodes[u].isolated and u != obs.pos:
                continue
            c = cv + step_cost(obs, model, u, v, lam, seen)
            if c < ctg.get(u, math.inf):
                ctg[u] = c
                nxt[u] = v
                heapq.heappush(pq, (c, u))
    return ctg, nxt


def action_for_step(obs, path):
    """Turn the first step of a path into a Red action."""
    if len(path) < 2:
        return ("scout",)
    u, v = path[0], path[1]
    if v == obs.database:
        return ("claim",)
    if v in obs.held:
        return ("advance", v)
    gate = frozenset((u, v))
    if gate in obs.gates and not obs.gates[gate]:
        return ("unlock", v)
    return ("capture", v)
