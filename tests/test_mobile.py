"""Phone layouts: picked from the screen shape, every key action has a button, and rotating works."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "offscreen")   # "dummy" crashes when SCALED changes size
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from ui import device, mobile  # noqa: E402


def test_pick_layouts():
    assert device.pick(1920, 1080).name == "desktop"
    assert device.pick(1280, 760).name == "desktop"
    p = device.pick(390, 844)
    assert p.name == "portrait" and p.h > p.w
    lnd = device.pick(844, 390)
    assert lnd.name == "landscape" and lnd.w > lnd.h
    assert device.pick(0, 0).name == "desktop"


_APP = []


@pytest.fixture
def app(tmp_path, monkeypatch):
    """One App for the whole file (pygame only likes being set up once per process), back on the menu
    in portrait for each test."""
    monkeypatch.setenv("ZERO_DAY_VIEWPORT", "390x844")
    if not _APP:
        from ui.app import App
        _APP.append(App(seed=7, settings_path=str(tmp_path / "s.json")))
    a = _APP[0]
    a._set_layout(device.pick(390, 844))
    a._leave_online()
    a.state, a.overlay, a.lobby = "menu", None, None
    return a


def _tap(app, pos):
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=pos, button=1, touch=True))
    app.handle(pygame.event.Event(pygame.MOUSEBUTTONUP, pos=pos, button=1, touch=True))


def _button(app, bid):
    app.draw()
    return next(b for b in app._bar if b.id == bid)


def test_portrait_menu_and_pause_by_touch(app):
    assert app.layout == "portrait"
    app.draw()
    _tap(app, mobile.menu_geometry(app)["items"][0].center)          # AI VS AI
    assert app.state == "match" and app.mode == "ai"
    _tap(app, _button(app, "play").rect.center)
    assert app.paused
    _tap(app, _button(app, "menu").rect.center)                        # the Esc key's job
    assert app.overlay == "pause"
    app.draw()
    from ui import overlays as O
    _, rects = O.pause_rects(app)
    _tap(app, rects[1].center)                                         # Settings
    assert app.state == "settings"
    app.draw()
    _, r = O.settings_row_rects(app)
    _tap(app, r["back"].center)                                        # back without a keyboard
    assert app.state == "match" and app.overlay == "pause"
    _tap(app, rects[0].center)                                         # Resume
    assert app.overlay is None


def test_blue_buttons_and_tabs(app):
    app.start_match("blue")
    for _ in range(5):
        app.update(1 / 30)
    _tap(app, _button(app, "monitor").rect.center)
    assert app.human_tool == "monitor"
    node = app.board.pts[0]
    _tap(app, node)
    assert app.human_blue_acts
    _tap(app, _button(app, "undo").rect.center)
    assert not app.human_blue_acts
    _tap(app, _button(app, "end").rect.center)
    assert app.pending_blue == []
    R = mobile.match_rects(app)
    log_tab = dict(mobile.tab_rects(app, R))["log"]
    _tap(app, log_tab.center)
    assert app.pane_tab == "log"


def test_rotate_rebuilds_layout(app, monkeypatch):
    app.start_match("red")
    monkeypatch.setenv("ZERO_DAY_VIEWPORT", "844x390")
    app.update(1.0)
    assert app.layout == "landscape" and app.size[0] > app.size[1]
    assert app.board.rect.right <= app.size[0]
    app.draw()
    monkeypatch.setenv("ZERO_DAY_VIEWPORT", "1600x900")
    app.update(1.0)
    assert app.layout == "desktop"
    app.draw()


def test_lobby_fits_and_back_by_touch(app):
    app._open_lobby()
    app.update(1 / 30)
    app.draw()
    back_row = app.lobby._row_rects(len(app.lobby._rows()))[app.lobby.ROWS.index("back")]
    src, dst = mobile.lobby_places(app)[0]
    k = dst.w / src.w
    pos = (int(dst.x + (back_row.centerx - src.x) * k), int(dst.y + (back_row.centery - src.y) * k))
    _tap(app, pos)
    assert app.state == "menu"
