"""Random network generator (outline section 02).

Each zone is built as a small random planar-ish graph (a Euclidean minimum
spanning tree plus a few short extra links), the zones are joined through
bridge links ("gates"), and breadth-first search checks that at least two
node-disjoint routes lead from the gateway to the database.
"""

import math
import random
from collections import deque

from engine.config import DMZ, OFFICE, DATACENTRE, ZONE_SIZES

ZONE_X = [(0.05, 0.27), (0.37, 0.63), (0.73, 0.95)]
Y_RANGE = (0.08, 0.92)
MIN_GAP = 0.085


class Network:
    """Static map: positions, links and node properties. Never changes in a match."""

    def __init__(self):
        self.n = 0
        self.pos = []          # (x, y) in the unit square
        self.zone = []
        self.kind = []         # gateway, database, bridge, server, workstation, fileserver, storage
        self.label = []
        self.value = []        # how bad it is for Blue if Red holds it (0..1)
        self.weakness = []     # base capture probability (0..1)
        self.sensitivity = []  # base alert sensitivity (0..1)
        self.adj = []
        self.gates = set()     # frozenset({u, v}) links that cross a zone border
        self.gateway = 0
        self.database = 0
        self.hops_to_db = []
        self.max_edge_len = 0.0
        self.seed = 0

    # -- helpers -----------------------------------------------------------
    def add_node(self, x, y, zone, kind):
        self.pos.append((x, y))
        self.zone.append(zone)
        self.kind.append(kind)
        self.adj.append([])
        self.n += 1
        return self.n - 1

    def add_edge(self, u, v):
        if v not in self.adj[u]:
            self.adj[u].append(v)
            self.adj[v].append(u)

    def is_gate(self, u, v):
        return frozenset((u, v)) in self.gates

    def edges(self):
        for u in range(self.n):
            for v in self.adj[u]:
                if u < v:
                    yield u, v

    def dist(self, u, v):
        (x1, y1), (x2, y2) = self.pos[u], self.pos[v]
        return math.hypot(x1 - x2, y1 - y2)

    def zone_nodes(self, z):
        return [i for i in range(self.n) if self.zone[i] == z]

    def bfs_hops(self, src, blocked=()):
        d = [math.inf] * self.n
        d[src] = 0
        q = deque([src])
        while q:
            u = q.popleft()
            for v in self.adj[u]:
                if d[v] == math.inf and v not in blocked:
                    d[v] = d[u] + 1
                    q.append(v)
        return d

    def bfs_path(self, src, dst, blocked=()):
        prev = {src: None}
        q = deque([src])
        while q:
            u = q.popleft()
            if u == dst:
                break
            for v in self.adj[u]:
                if v not in prev and v not in blocked:
                    prev[v] = u
                    q.append(v)
        if dst not in prev:
            return None
        path, u = [], dst
        while u is not None:
            path.append(u)
            u = prev[u]
        return path[::-1]


def _segments_cross(p1, p2, p3, p4):
    def orient(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2 = orient(p3, p4, p1), orient(p3, p4, p2)
    d3, d4 = orient(p1, p2, p3), orient(p1, p2, p4)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _crosses_any(net, u, v):
    pu, pv = net.pos[u], net.pos[v]
    for a, b in net.edges():
        if a in (u, v) or b in (u, v):
            continue
        if _segments_cross(pu, pv, net.pos[a], net.pos[b]):
            return True
    return False


def _sample_points(rng, k, xr, fixed):
    pts = list(fixed)
    tries = 0
    while len(pts) < k + len(fixed) and tries < 5000:
        tries += 1
        p = (rng.uniform(*xr), rng.uniform(*Y_RANGE))
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) >= MIN_GAP for q in pts):
            pts.append(p)
    return pts[len(fixed):]


def _build_zone(net, rng, ids):
    """Euclidean MST over the zone's nodes, then a few short extra links."""
    if len(ids) < 2:
        return
    in_tree = {ids[0]}
    while len(in_tree) < len(ids):
        best = None
        for u in in_tree:
            for v in ids:
                if v in in_tree:
                    continue
                d = net.dist(u, v)
                if best is None or d < best[0]:
                    best = (d, u, v)
        _, u, v = best
        net.add_edge(u, v)
        in_tree.add(v)
    extra = sorted(((net.dist(u, v), u, v) for i, u in enumerate(ids) for v in ids[i + 1:]))
    for d, u, v in extra:
        if d > 0.24 or v in net.adj[u]:
            continue
        if rng.random() < 0.45 and len(net.adj[u]) < 4 and len(net.adj[v]) < 4 and not _crosses_any(net, u, v):
            net.add_edge(u, v)


def _join_zones(net, rng, za, zb, count):
    a_nodes = sorted(net.zone_nodes(za), key=lambda i: -net.pos[i][0])
    b_nodes = net.zone_nodes(zb)
    used_a, used_b = set(), set()
    made = 0
    for u in a_nodes:
        if made >= count:
            break
        if net.kind[u] in ("gateway", "database"):
            continue
        cands = sorted((v for v in b_nodes if v not in used_b and net.kind[v] != "database"),
                       key=lambda v: net.dist(u, v))
        for v in cands[:3]:
            if not _crosses_any(net, u, v):
                net.add_edge(u, v)
                net.gates.add(frozenset((u, v)))
                net.kind[u] = "bridge"
                used_a.add(u)
                used_b.add(v)
                made += 1
                break
    return made


def _two_routes(net):
    p1 = net.bfs_path(net.gateway, net.database)
    if p1 is None:
        return False
    interior = set(p1[1:-1])
    return net.bfs_path(net.gateway, net.database, blocked=interior) is not None


def generate(seed=None, max_tries=200):
    seed = random.randrange(1, 10 ** 6) if seed is None else seed
    rng = random.Random(seed)
    for _ in range(max_tries):
        net = _try_generate(rng)
        if net is not None:
            net.seed = seed
            return net
    raise RuntimeError("could not generate a valid network")


def _try_generate(rng):
    net = Network()
    zone_ids = []
    for z in (DMZ, OFFICE, DATACENTRE):
        k = rng.randint(*ZONE_SIZES[z])
        fixed = []
        if z == DMZ:
            fixed = [(0.03, 0.5)]
        elif z == DATACENTRE:
            fixed = [(0.97, 0.5)]
        pts = _sample_points(rng, k - len(fixed), ZONE_X[z], fixed)
        ids = []
        if z == DMZ:
            net.gateway = net.add_node(0.03, 0.5, z, "gateway")
            ids.append(net.gateway)
        for (x, y) in pts:
            if z == DMZ:
                kind = "server"
            elif z == OFFICE:
                kind = "fileserver" if rng.random() < 0.25 else "workstation"
            else:
                kind = "storage"
            ids.append(net.add_node(x, y, z, kind))
        if z == DATACENTRE:
            net.database = net.add_node(0.97, 0.5, z, "database")
            ids.append(net.database)
        zone_ids.append(ids)

    for ids in zone_ids:
        _build_zone(net, rng, ids)

    # the database gets two or three links so it cannot be sealed off with one isolate
    near_db = sorted((v for v in zone_ids[2] if v != net.database), key=lambda v: net.dist(v, net.database))
    for v in near_db[:rng.randint(2, 3)]:
        if not _crosses_any(net, v, net.database):
            net.add_edge(v, net.database)
    # same for the gateway
    near_gw = sorted((v for v in zone_ids[0] if v != net.gateway), key=lambda v: net.dist(v, net.gateway))
    for v in near_gw[:3]:
        if not _crosses_any(net, v, net.gateway):
            net.add_edge(v, net.gateway)

    if _join_zones(net, rng, DMZ, OFFICE, rng.randint(2, 3)) < 2:
        return None
    if _join_zones(net, rng, OFFICE, DATACENTRE, rng.randint(2, 3)) < 2:
        return None
    if not _two_routes(net):
        return None

    _assign_properties(net, rng)
    return net


def _assign_properties(net, rng):
    net.hops_to_db = net.bfs_hops(net.database)
    far = max(h for h in net.hops_to_db if h != math.inf)
    counters = {}
    for i in range(net.n):
        z, kind = net.zone[i], net.kind[i]
        if kind == "gateway":
            w, s = 1.0, 0.75
        elif kind == "database":
            w, s = 0.5, 1.0
        elif z == DMZ:
            w, s = rng.uniform(0.6, 0.92), rng.uniform(0.55, 0.75)
        elif z == OFFICE:
            w, s = rng.uniform(0.55, 0.9), rng.uniform(0.40, 0.65)
        else:
            w, s = rng.uniform(0.45, 0.75), rng.uniform(0.70, 0.90)
        closeness = 1.0 - net.hops_to_db[i] / far
        v = 0.15 + 0.6 * closeness
        if kind == "fileserver":
            v += 0.1
        if kind == "bridge":
            v += 0.1
        if kind == "database":
            v = 1.0
        net.weakness.append(round(w, 2))
        net.sensitivity.append(round(s, 2))
        net.value.append(round(min(1.0, v), 2))
        prefix = {"gateway": "GW", "database": "DB", "bridge": "BR", "server": "SRV",
                  "workstation": "WS", "fileserver": "FS", "storage": "ST"}[kind]
        if kind in ("gateway", "database"):
            net.label.append(prefix)
        else:
            counters[prefix] = counters.get(prefix, 0) + 1
            net.label.append(f"{prefix}-{counters[prefix]:02d}")
    net.max_edge_len = max(net.dist(u, v) for u, v in net.edges())
