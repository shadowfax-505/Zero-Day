"""Red stuck on a dead-end node whose only link is isolated must still be able to end its turn."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from engine import config as C
from engine.game import Game
from engine.mapgen import generate


def _cut_off_game():
    """A game where Red stands on a dead-end node and Blue has isolated its only neighbour."""
    for seed in range(1, 200):
        net = generate(seed)
        for v in range(net.n):
            if len(net.adj[v]) == 1 and v not in (net.gateway, net.database):
                u = next(iter(net.adj[v]))
                if u in (net.gateway, net.database):
                    continue
                g = Game(net)
                g.red_pos = v
                g.red_held = {net.gateway, v}
                g.isolated = {u: C.ISOLATE_ROUNDS}
                return g, u
    raise AssertionError("no dead-end node found")


def test_cut_off_red_can_only_scout_and_the_round_moves_on():
    g, u = _cut_off_game()
    assert g.red_legal() == [("scout",)]
    r = g.round
    g.step(("scout",), [])
    assert g.round == r + 1 and g.winner is None
    g.step(("scout",), [])
    assert u not in g.isolated          # the isolation wears off and the way out reopens
    assert any(len(a) > 1 and a[1] == u for a in g.red_legal())


def test_human_red_can_click_to_pass_when_cut_off(tmp_path):
    import pygame
    from ui.app import App

    app = App(mode="red", seed=7, windowed=True, settings_path=str(tmp_path / "s.json"))
    g, _ = _cut_off_game()
    app.match.game = g
    app.match.net = g.net
    from ui.board import Board
    app.board = Board(g.net)
    app.pending_red = None

    assert app._red_cut_off()
    targets = app._human_red_targets()
    assert targets == {g.red_pos: ("scout",)}   # your own node is clickable even with no way out

    app.draw()                                   # the SCOUT AND PASS bar renders
    click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=app._red_bar_rect().center)
    app.handle(click)
    assert app.pending_red == ("scout",)

    app.pending_red = None
    click = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=app.board.pts[g.red_pos])
    app.handle(click)
    assert app.pending_red == ("scout",)
