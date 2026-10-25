"""Blue AI: particle filter -> fuzzy triage -> Stackelberg minimax, tuned by a GA."""

import json
import os

import numpy as np

from agents.base import Agent
from agents.blue.fuzzy import FuzzyTriage
from agents.blue.particle_filter import ParticleFilter
from agents.blue.stackelberg import Stackelberg, PlanState, allocations
from engine import config as C

# The genome the GA tunes (tuning/ga.py). Bounds are (low, high).
GENES = {
    "path":      (1.0, 0.2, 3.0),     # value of a longer route for Red
    "detect":    (0.8, 0.1, 2.5),     # value of a likely alert
    "catch":     (2.5, 0.5, 5.0),     # value of cutting Red off the node it stands on
    "value":     (0.6, 0.1, 2.0),     # cost of Red taking a valuable node
    "decoy":     (0.9, 0.0, 2.5),     # bonus for Red stepping on a decoy
    "patch_pref": (1.0, 0.2, 2.0),
    "restore_pref": (1.0, 0.2, 2.0),
    "watch":     (35.0, 15.0, 50.0),  # fuzzy threshold: start watching
    "act":       (65.0, 50.0, 85.0),  # fuzzy threshold: act on it
    "alert_mid": (0.45, 0.2, 0.8),    # fuzzy membership peak for "medium alert"
    "conf_mid":  (0.35, 0.1, 0.7),    # fuzzy membership peak for "medium confidence"
    "stay":      (0.5, 0.2, 0.8),     # particle motion: chance Red stays put
    "toward_db": (2.0, 1.0, 4.0),     # particle motion: bias toward the database
}
DEFAULT_WEIGHTS = {k: v[0] for k, v in GENES.items()}
WEIGHTS_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "tuning", "best_weights.json")


def load_tuned_weights():
    try:
        with open(WEIGHTS_FILE) as f:
            data = json.load(f)
        w = dict(DEFAULT_WEIGHTS)
        w.update({k: float(v) for k, v in data.get("weights", {}).items() if k in GENES})
        return w
    except (OSError, ValueError):
        return dict(DEFAULT_WEIGHTS)


class BlueAI(Agent):
    side = "blue"

    def __init__(self, weights=None, use_filter=True, particles=2000, depth=2, seed=None, name=None):
        super().__init__()
        self.weights = dict(weights) if weights else load_tuned_weights()
        self.use_filter = use_filter
        self.n_particles = particles
        self.depth = depth
        self.name = name or ("Blue AI" if use_filter else "Blue (no filter)")
        self.seed = seed
        self.reset(seed)

    def reset(self, seed=None):
        super().reset(seed)
        self.seed = seed
        self.pf = None
        self.net = None
        self.last_monitored = set()
        self.alert_mem = None
        self.located_round = None

    def _init(self, net):
        w = self.weights
        self.net = net
        self.pf = ParticleFilter(net, self.n_particles, stay=w["stay"], toward_db=w["toward_db"], seed=self.seed)
        self.fuzzy = FuzzyTriage(w["alert_mid"], w["conf_mid"], w["watch"], w["act"])
        self.planner = Stackelberg(net, w)
        self.alert_mem = np.zeros(net.n)

    # -- belief ------------------------------------------------------------------
    def _belief(self, obs):
        net = self.net
        if self.use_filter:
            if obs.round > 1:
                self.pf.predict(obs.isolated)
                self.pf.update(obs.alerts, self.last_monitored, obs.feedback, obs.decoy_sprung,
                               obs.isolated, obs.round)
            return self.pf.belief
        # ablation: no filter, believe the latest alerts directly
        b = np.full(net.n, 0.01)
        for v, s in obs.alerts:
            b[v] += s
        if obs.decoy_sprung is not None:
            b[:] = 0.0
            b[obs.decoy_sprung] = 1.0
        return b / b.sum()

    def choose_action(self, obs):
        if self.net is not obs.net:
            self._init(obs.net)
        net, w = self.net, self.weights
        belief = self._belief(obs)
        self.alert_mem *= 0.5
        for v, s in obs.alerts:
            self.alert_mem[v] = max(self.alert_mem[v], s)

        # fuzzy threat per node
        neigh_alert = np.array([max([self.alert_mem[v]] + [0.6 * self.alert_mem[a] for a in net.adj[v]])
                                for v in range(net.n)])
        conf = np.array([min(1.0, 3.0 * (belief[v] + 0.4 * sum(belief[a] for a in net.adj[v])))
                         for v in range(net.n)])
        threat = np.array([self.fuzzy.score(neigh_alert[v], net.value[v], conf[v]) for v in range(net.n)])

        # most likely Red positions
        order = np.argsort(-belief)
        positions = [(int(v), float(belief[v])) for v in order[:3] if belief[v] > 0.02]
        mass = sum(p for _, p in positions) or 1.0
        positions = [(v, p / mass) for v, p in positions] or [(net.gateway, 1.0)]

        base = PlanState(list(obs.weakness), frozenset(obs.isolated), frozenset(obs.decoys))
        cands = self._candidates(obs, belief, threat, positions, base)
        root_allocs = self._prune(allocations(cands, C.BLUE_AP, net.gateway), belief, threat)
        alloc, score, scored = self.planner.choose(base, positions, root_allocs, self.depth)
        self.last_monitored = {t for k, t in alloc if k == "monitor"}

        top = int(order[0])
        self.debug = {
            "belief": belief.copy(),
            "top": [(int(v), float(belief[v])) for v in order[:5]],
            "threat": threat,
            "threat_top": sorted(((int(v), float(threat[v]), self.fuzzy.level(threat[v]))
                                  for v in range(net.n)), key=lambda t: -t[1])[:5],
            "actions": alloc,
            "score": score,
            "options": len(root_allocs),
            "evaluated": self.planner.evaluated,
            "entropy": self.pf.entropy() if self.use_filter else 0.0,
            "particles": self.pf.sample(500) if self.use_filter else None,
            "decoys": len(obs.decoys) + sum(1 for k, _ in alloc if k == "decoy"),
            "top_guess": top,
            "max_threat": float(threat.max()),
        }
        return alloc

    def _candidates(self, obs, belief, threat, positions, base):
        net, w = self.net, self.weights
        acts = []
        d = self.planner.dist_to_db(base)
        immune = set(obs.immune) | set(obs.isolated)

        def can_isolate(v):
            return (v not in (net.gateway, net.database) and v not in immune
                    and len(obs.isolated) < C.MAX_ISOLATED and obs.round >= obs.isolate_ready)

        # isolate where the fuzzy system says act, or where belief is concentrated
        for v in np.argsort(-threat)[:6]:
            v = int(v)
            if (threat[v] >= w["act"] or belief[v] > 0.3) and can_isolate(v):
                acts.append(("isolate", v))
        for v, _ in positions:
            if can_isolate(v) and belief[v] > 0.12:
                acts.append(("isolate", v))
        # predicted next steps of Red from its likely positions
        nxt = []
        for p, _ in positions:
            nxt += sorted((q for q in net.adj[p] if q not in obs.isolated), key=lambda q: d[q])[:2]
        nxt = list(dict.fromkeys(nxt))
        for q in nxt:
            if q != net.gateway and (threat[q] >= w["watch"] or q in net.adj[net.database]):
                if q not in obs.patched and obs.weakness[q] > C.PATCH_FLOOR:
                    acts.append(("patch", q))
            if q not in (net.gateway, net.database) and q not in obs.decoys and len(obs.decoys) < C.MAX_DECOYS \
                    and q not in obs.isolated:
                acts.append(("decoy", q))
        # restore nodes Red has probably held for a while
        hp = self.pf.held_prob if self.use_filter else belief
        for v in np.argsort(-(hp * np.array(net.value)))[:3]:
            v = int(v)
            if hp[v] > 0.35 and v != net.database and (v != net.gateway or obs.round > C.GATEWAY_GRACE):
                acts.append(("restore", v))
        # watch the zone with most belief mass and the zone Red is heading into
        zone_mass = [sum(belief[v] for v in range(net.n) if net.zone[v] == z) for z in range(3)]
        acts.append(("monitor", int(np.argmax(zone_mass))))
        if nxt:
            acts.append(("monitor", net.zone[nxt[0]]))
        if net.database not in obs.patched and belief[[q for q in net.adj[net.database]]].sum() > 0.1:
            acts.append(("patch", net.database))
        return list(dict.fromkeys(acts))[:12]

    def _prune(self, allocs, belief, threat, keep=20):
        w = self.weights

        def quick(a):
            kind, t = a
            if kind == "isolate":
                return w["catch"] * belief[t] + threat[t] / 100
            if kind == "restore":
                return 0.4 * w["restore_pref"] * (self.pf.held_prob[t] if self.use_filter else belief[t])
            if kind == "patch":
                return 0.3 * w["patch_pref"] * threat[t] / 100 + 0.05
            if kind == "decoy":
                return 0.3 * w["decoy"] * threat[t] / 100 + 0.05
            if kind == "monitor":
                return 0.15 * w["detect"]
            return 0.0

        scored = sorted(allocs, key=lambda al: -sum(quick(a) for a in al))
        return scored[:keep]
