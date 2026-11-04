"""Unit checks for the AI parts that the batch suite only tests end to end."""

import numpy as np

from agents.blue.particle_filter import ParticleFilter
from agents.red import agent as red_agent
from agents.red.agent import RedAI
from agents.red.ismcts import ISMCTS, load_policy, load_value, value_features, DEFAULT_POLICY
from engine.game import Game
from engine.mapgen import generate


def test_particles_carry_held_sets():
    net = generate(3)
    pf = ParticleFilter(net, n=400, seed=1)
    assert pf.held[:, net.gateway].all()
    for rnd in range(2, 6):
        pf.predict(set())
        pf.update([], set(), [], None, set(), rnd)
    # every particle holds the node it stands on, and P(held) is a proper share
    assert pf.held[np.arange(pf.n), pf.particles].all()
    assert ((pf.held_prob >= 0) & (pf.held_prob <= 1)).all()
    # a node Blue restored is nobody's any more
    v = int(np.argmax(pf.held_prob * (np.arange(net.n) != net.gateway)))
    pf.predict(set())
    pf.update([], set(), [("restore", v, True)], None, set(), 6)
    assert pf.held_prob[v] == 0 or (pf.particles == v).any()


def test_failed_restore_lowers_particles_that_held_the_node():
    net = generate(4)
    pf = ParticleFilter(net, n=200, seed=2)
    v = net.adj[net.gateway][0]
    pf.held[:100, v] = True
    w = pf._held_weight([("restore", v, False)])
    assert w[:100][pf.particles[:100] != v].max() < w[100:].min()


def test_red_weights_have_defaults_and_bounds():
    for k, (d, lo, hi) in red_agent.GENES.items():
        assert lo <= d <= hi, k
    r = RedAI(weights=red_agent.DEFAULT_WEIGHTS)
    assert r.weights == red_agent.DEFAULT_WEIGHTS
    assert set(RedAI().weights) == set(red_agent.GENES)


def test_learned_models_load():
    pol = load_policy()
    assert set(pol) == set(DEFAULT_POLICY)
    assert all(0 < p < 1 for p in pol.values())
    w = load_value()
    assert w is None or len(w) == len(value_features(10, 20, 3, False))


def test_paired_search_scores_every_candidate_on_the_same_samples():
    net = generate(9)
    g = Game(net)
    red = RedAI(iterations=120, time_limit=5.0)
    red.choose_action(g.red_observation())
    m = red.mcts
    counts = {len(v) for v in m.rewards.values()}
    assert len(counts) == 1                      # same number of shared samples per move
    a, b = list(m.rewards)[:2] if len(m.rewards) > 1 else (list(m.rewards)[0],) * 2
    gain, se = m.paired_gain(a, b)
    assert se >= 0
    assert isinstance(m, ISMCTS)
