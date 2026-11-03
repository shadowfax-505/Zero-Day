"""Online play through the relay server: room codes, pairing, lockstep match, leaving."""

import asyncio
import importlib.util
import os
import random
import threading
import time

import pytest

pytest.importorskip("websockets")

from agents.baseline.random_agents import RandomRed, RandomBlue
from engine.game import Game
from engine.mapgen import generate
from net.peer import fingerprint
from net.relay import RelayPeer
from net.session import Session

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def relay_url():
    spec = importlib.util.spec_from_file_location("relay_server", os.path.join(ROOT, "server", "relay.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    port = random.randrange(20000, 40000)
    threading.Thread(target=lambda: asyncio.run(mod.main(port)), daemon=True).start()
    time.sleep(0.5)
    return f"ws://127.0.0.1:{port}"


def _wait(cond, peers=(), timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        for p in peers:
            p.update()
        if cond():
            return
        time.sleep(0.005)
    raise AssertionError("timed out")


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


def test_room_codes_and_errors(relay_url):
    a, b = RelayPeer(relay_url), RelayPeer(relay_url)
    _wait(lambda: a.connected and b.connected)
    a.create("Alice", "red")
    _wait(lambda: a.code is not None, [a])
    b.list_rooms()
    _wait(lambda: b.rooms_t is not None, [b])
    assert (a.code, "Alice", "red") in b.rooms
    b.join("ZZZZ" if a.code != "ZZZZ" else "YYYY")
    _wait(lambda: b.notices, [b])
    assert "No open game" in b.notices[0]
    a.close()
    b.close()


def test_lockstep_match_through_relay(relay_url):
    hp, cp = RelayPeer(relay_url), RelayPeer(relay_url)
    _wait(lambda: hp.connected and cp.connected)
    hp.create("Alice", "blue")
    _wait(lambda: hp.code, [hp])
    cp.join(hp.code.lower())
    _wait(lambda: hp.accepted() and cp.accepted(), [hp, cp])
    assert cp.host_name == "Alice"

    host = Session(hp, "host", "Alice", side="blue")
    client = Session(cp, "client", "Bob")
    _pump([host, client], lambda e: host.greeted)
    host.start(4321)
    _pump([host, client], lambda e: client.seed == 4321)
    assert client.side == "red"

    games = {"host": Game(generate(4321)), "client": Game(generate(4321))}
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
        red_act, blue_act = host.remote_move(r), client.remote_move(r)
        for g in games.values():
            g.step(red_act, blue_act)
        assert fingerprint(games["host"]) == fingerprint(games["client"])
    assert host.desync_round is None and client.desync_round is None

    client.chat("gg")
    ev = _pump([host, client], lambda e: any(x[0] == "chat" for x in e[id(host)]))
    assert ("chat", "Bob", "gg") in ev[id(host)]

    client.close()
    _pump([host, client], lambda e: any(x[0] == "closed" for x in e[id(host)]))
    host.close()
