"""Online play: two sessions on localhost run the same match in lockstep and must agree."""

import json
import random
import time

from agents.baseline.random_agents import RandomRed, RandomBlue
from engine.game import Game
from engine.mapgen import generate
from net.peer import Peer, fingerprint
from net.session import Session


def _pump(sessions, until, timeout=5.0):
    end = time.time() + timeout
    events = {id(s): [] for s in sessions}
    while time.time() < end:
        for s in sessions:
            events[id(s)] += s.poll()
        if until(events):
            return events
        time.sleep(0.005)
    raise AssertionError("timed out")


def test_lockstep_match_over_localhost():
    port = random.randrange(20000, 40000)
    hp = Peer.host(port)
    host = Session(hp, "host", "Alice", side="blue")
    client = Session(Peer.join("127.0.0.1", port), "client", "Bob")
    _pump([host, client], lambda e: host.greeted)
    assert host.remote_name == "Bob"

    host.start(1234)
    _pump([host, client], lambda e: client.seed == 1234)
    assert client.side == "red" and client.remote_name == "Alice"

    games = {"host": Game(generate(1234)), "client": Game(generate(1234))}
    agents = {"host": RandomBlue(), "client": RandomRed()}
    agents["host"].reset(1)
    agents["client"].reset(2)
    sess = {"host": host, "client": client}
    while games["host"].winner is None:
        r = games["host"].round
        for k in ("host", "client"):
            g = games[k]
            obs = g.blue_observation() if k == "host" else g.red_observation()
            sess[k].send_move(g, agents[k].choose_action(obs))
        _pump([host, client], lambda e: host.remote_move(r) is not None and client.remote_move(r) is not None)
        red_act = host.remote_move(r)
        blue_act = client.remote_move(r)
        for g in games.values():
            g.step(red_act, blue_act)
        assert fingerprint(games["host"]) == fingerprint(games["client"])
    assert host.desync_round is None and client.desync_round is None
    assert games["host"].winner == games["client"].winner

    client.chat("gg")
    ev = _pump([host, client], lambda e: any(x[0] == "chat" for x in e[id(host)]))
    assert ("chat", "Bob", "gg") in ev[id(host)]

    client.close()
    ev = _pump([host, client], lambda e: any(x[0] == "closed" for x in e[id(host)]))
    host.close()


def test_desync_is_repaired_from_the_host_state():
    """If the client's copy drifts, the host ships its state and both carry on in sync."""
    port = random.randrange(20000, 40000)
    host = Session(Peer.host(port), "host", "Alice", side="blue")
    client = Session(Peer.join("127.0.0.1", port), "client", "Bob")
    _pump([host, client], lambda e: host.greeted)
    host.start(77)
    _pump([host, client], lambda e: client.seed == 77)

    games = {"host": Game(generate(77)), "client": Game(generate(77))}
    agents = {"host": RandomBlue(), "client": RandomRed()}
    agents["host"].reset(1)
    agents["client"].reset(2)
    sess = {"host": host, "client": client}
    broke_at = None
    while games["host"].winner is None:
        r = games["host"].round
        if r == 4:
            games["client"].weakness[5] = 0.99      # simulate a drift on the client only
            broke_at = r
        for k in ("host", "client"):
            g = games[k]
            obs = g.blue_observation() if k == "host" else g.red_observation()
            sess[k].send_move(g, agents[k].choose_action(obs))
        _pump([host, client], lambda e: host.remote_move(r) is not None and client.remote_move(r) is not None)
        client.adopt_state(games["client"])
        red_act, blue_act = host.remote_move(r), client.remote_move(r)
        for g in games.values():
            g.step(red_act, blue_act)
    assert broke_at == 4
    assert host.resyncs >= 1 and client.resyncs >= 1
    assert fingerprint(games["host"]) == fingerprint(games["client"])
    assert games["host"].winner == games["client"].winner
    host.close()
    client.close()


def test_snapshot_round_trip():
    g = Game(generate(5))
    a = RandomRed()
    b = RandomBlue()
    a.reset(1)
    b.reset(2)
    for _ in range(6):
        g.step(a.choose_action(g.red_observation()), b.choose_action(g.blue_observation()))
    h = Game(generate(5))
    h.restore(json.loads(json.dumps(g.snapshot())))
    assert fingerprint(h) == fingerprint(g)
    assert h.red_observation() == g.red_observation()
