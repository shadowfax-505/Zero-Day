"""Basic checks for the engine and the agents. Run with: python -m pytest -q"""

from engine import config as C
from engine.game import Game
from engine.mapgen import generate
from engine.match import Match
from agents.baseline.random_agents import RandomRed, RandomBlue


def test_maps_are_valid_and_repeatable():
    for seed in range(1, 40):
        net = generate(seed)
        assert 30 <= net.n <= 40
        # two node-disjoint routes from the gateway to the database
        p1 = net.bfs_path(net.gateway, net.database)
        assert p1 is not None
        assert net.bfs_path(net.gateway, net.database, blocked=set(p1[1:-1])) is not None
        assert generate(seed).pos == net.pos


def test_red_observation_hides_blue_defences():
    net = generate(5)
    g = Game(net)
    g.step(("scout",), [("decoy", net.adj[net.gateway][0]), ("monitor", 0)])
    obs = g.red_observation()
    assert not hasattr(obs, "decoys")
    for u, info in obs.nodes.items():
        assert info.weakness is None or 0 <= info.weakness <= 1
    # a decoy looks tempting to Red
    d = net.adj[net.gateway][0]
    assert obs.nodes[d].weakness == C.DECOY_APPARENT_WEAKNESS


def test_blue_observation_hides_red():
    net = generate(6)
    obs = Game(net).blue_observation()
    assert not hasattr(obs, "red_pos")
    assert not hasattr(obs, "red_held")


def test_random_matches_finish():
    for seed in range(1, 8):
        r = Match(RandomRed(seed), RandomBlue(seed), seed=seed).play()
        assert r["winner"] in ("red", "blue")
        assert r["rounds"] <= C.MAX_ROUNDS
