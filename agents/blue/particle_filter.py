"""Bayesian particle filter: where is Red? (outline section 06, part 1)

Each particle is one full guess about Red: the node it stands on and the set
of nodes it holds. Every round:
  predict   - each particle moves along a link or stays (biased toward the
              database); a node it moves onto joins its held set
  update    - weight each particle by P(observed alerts | Red at v) and by how
              well its held set explains Blue's isolate/restore feedback
  resample  - systematic resampling (positions and held sets together)
The share of particles on each node is Blue's belief about Red's position, and
the share whose held set contains a node is P(Red holds it now).
"""

import numpy as np

from engine import config as C

EXPECTED_NOISE = 0.45


class ParticleFilter:
    def __init__(self, net, n=2000, stay=0.5, toward_db=2.0, seed=None):
        self.net = net
        self.n = n
        self.stay = stay
        self.toward_db = toward_db
        self.rng = np.random.default_rng(seed)
        self.particles = np.full(n, net.gateway, dtype=np.int32)
        self.held = np.zeros((n, net.n), dtype=bool)   # held[i, v]: particle i says Red holds v
        self.held[:, net.gateway] = True
        self.rows = np.arange(n)
        self.hops_from_gw = net.bfs_hops(net.gateway)
        self.belief = np.zeros(net.n)
        self.belief[net.gateway] = 1.0
        # P(Red holds v right now), used to choose Restore targets
        self.held_prob = np.zeros(net.n)
        self.held_prob[net.gateway] = 1.0
        self.last_likelihood = np.ones(net.n)

    def _transition_cdf(self, isolated):
        net = self.net
        m = np.zeros((net.n, net.n))
        for u in range(net.n):
            m[u, u] = self.stay
            ws = []
            for v in net.adj[u]:
                if v in isolated or v == net.database:
                    continue
                w = self.toward_db if net.hops_to_db[v] < net.hops_to_db[u] else 0.5
                if net.is_gate(u, v):
                    w *= 0.45     # Red has to unlock first
                ws.append((v, w))
            tot = sum(w for _, w in ws)
            if tot > 0:
                for v, w in ws:
                    m[u, v] = (1 - self.stay) * w / tot
            else:
                m[u, u] = 1.0
        return np.cumsum(m / m.sum(axis=1, keepdims=True), axis=1)

    def predict(self, isolated):
        cdf = self._transition_cdf(isolated)
        u = self.rng.random(self.n)
        rows = cdf[self.particles]
        self.particles = np.minimum((rows < u[:, None]).sum(axis=1), self.net.n - 1).astype(np.int32)
        self.held[self.rows, self.particles] = True

    def likelihood(self, alerts, monitored, feedback, decoy_sprung, isolated, rnd):
        net = self.net
        lik = np.ones(net.n)
        alert_map = dict(alerts)
        ratio = np.ones(net.n)
        for v in range(net.n):
            mon = C.MONITOR_BOOST if net.zone[v] in monitored else 1.0
            pd = min(0.95, EXPECTED_NOISE * net.sensitivity[v] * mon)
            if v in alert_map:
                s = alert_map[v]
                f_real = np.exp(-((s - 0.6) ** 2) / (2 * 0.22 ** 2)) / 0.55
                f_false = 2.0 if s <= 0.56 else 0.05
                ratio[v] = (pd * f_real + C.FALSE_ALARM * f_false) / (C.FALSE_ALARM * f_false)
            else:
                ratio[v] = (1 - pd * 0.6) / (1 - C.FALSE_ALARM)   # Red is not always noisy
        for v in range(net.n):
            lik[v] = ratio[v]
            # a failed capture or an unlock rings at a neighbour while Red stays put
            spill = sum(ratio[a] - 1 for a in net.adj[v] if a in alert_map)
            if spill > 0:
                lik[v] += 0.3 * spill
        for kind, t, found in feedback:
            if found and kind == "isolate":
                boost = np.full(net.n, 0.15)
                for x in [t] + list(net.adj[t]):
                    boost[x] = 6.0
                lik *= boost
            elif found:
                # Red held this node; it is probably somewhere further along
                ahead = np.array([net.hops_to_db[v] <= net.hops_to_db[t] for v in range(net.n)])
                lik *= np.where(ahead, 2.0, 0.5)
            elif kind == "isolate":
                lik[t] *= 0.05
        for t in isolated:
            lik[t] *= 0.01
        reach = np.array([h <= rnd for h in self.hops_from_gw], dtype=float)
        lik *= np.where(reach > 0, 1.0, 0.001)
        if decoy_sprung is not None:
            lik = np.full(net.n, 1e-6)
            lik[decoy_sprung] = 1.0
        return lik

    def update(self, alerts, monitored, feedback, decoy_sprung, isolated, rnd):
        lik = self.likelihood(alerts, monitored, feedback, decoy_sprung, isolated, rnd)
        self.last_likelihood = lik
        w = lik[self.particles] * self._held_weight(feedback)
        if w.sum() <= 0:
            w = np.ones(self.n)
        w = w / w.sum()
        # systematic resampling
        positions = (self.rng.random() + np.arange(self.n)) / self.n
        idx = np.minimum(np.searchsorted(np.cumsum(w), positions), self.n - 1)
        self.particles = self.particles[idx]
        self.held = self.held[idx]
        # inject a few particles along plausible nodes so the filter can recover from surprises
        k = self.n // 50
        if decoy_sprung is None and k:
            cand = np.array([v for v in range(self.net.n)
                             if self.hops_from_gw[v] <= rnd and v not in isolated], dtype=np.int32)
            if len(cand):
                rows = self.rng.integers(0, self.n, k)
                self.particles[rows] = self.rng.choice(cand, k)
                self.held[rows, self.particles[rows]] = True
        # whatever Blue isolated or restored is no longer Red's, in every particle
        for kind, t, found in feedback:
            if kind in ("isolate", "restore"):
                self.held[:, t] = False
        self.held[self.rows, self.particles] = True
        self.belief = np.bincount(self.particles, minlength=self.net.n) / self.n
        self.held_prob = self.held.mean(axis=0)

    def _held_weight(self, feedback):
        """How well each particle's held set explains this round's isolate/restore results."""
        w = np.ones(self.n)
        for kind, t, found in feedback:
            had = self.held[:, t]
            on = self.particles == t
            if kind == "restore":
                if found:
                    w *= np.where(had & ~on, 3.0, 0.2)
                else:
                    # a restore fails if Red never held the node, or if Red stands on it
                    w *= np.where(had & ~on, 0.1, 1.0)
            elif kind == "isolate" and not found:
                w *= np.where(had, 0.1, 1.0)
        return w

    def entropy(self):
        p = self.belief[self.belief > 0]
        return float(-(p * np.log2(p)).sum())

    def sample(self, k):
        return self.particles[self.rng.integers(0, self.n, k)]
