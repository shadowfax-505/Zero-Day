"""Sharp drawing (ui/hidpi.py): logical coordinates land on the right real pixels at any scale."""

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402
import pytest  # noqa: E402

from ui import hidpi  # noqa: E402
from ui import theme as T  # noqa: E402


@pytest.fixture
def scale(monkeypatch):
    pygame.init()

    def at(k):
        monkeypatch.setattr(hidpi, "K", k)
        return k
    return at


def test_canvas_keeps_logical_size_and_scales_pixels(scale):
    scale(2.0)
    c = hidpi.Surface((100, 50))
    assert c.get_size() == (100, 50) and c.real.get_size() == (200, 100)
    c.fill((0, 0, 0))
    hidpi.rect(c, (255, 0, 0), (10, 10, 5, 5))
    assert c.real.get_at((20, 20))[:3] == (255, 0, 0)       # logical (10, 10) is real (20, 20)
    assert c.real.get_at((29, 29))[:3] == (255, 0, 0)
    assert c.real.get_at((30, 30))[:3] == (0, 0, 0)
    assert c.get_at((12, 12))[:3] == (255, 0, 0)


def test_neighbouring_rects_meet_at_fractional_scale(scale):
    scale(1.62)
    c = hidpi.Surface((30, 10))
    c.fill((0, 0, 0))
    for x in range(0, 30, 3):
        c.fill((255, 255, 255), (x, 0, 3, 10))
    row = [c.real.get_at((i, 5))[:3] for i in range(c.real.get_width() - 1)]
    assert all(p == (255, 255, 255) for p in row)            # no black gaps between them


def test_blit_and_clip_use_logical_coordinates(scale):
    scale(1.5)
    dst = hidpi.Surface((200, 100))
    src = hidpi.Surface((20, 20))
    src.fill((0, 255, 0))
    r = dst.blit(src, (40, 30))
    assert r.topleft == (40, 30) and r.size == (20, 20)
    assert dst.real.get_at((61, 46))[:3] == (0, 255, 0)
    dst.set_clip(pygame.Rect(5, 5, 10, 10))
    assert dst.get_clip() == pygame.Rect(5, 5, 10, 10)
    dst.set_clip(None)
    assert dst.get_clip() == dst.get_rect()


def test_text_is_rendered_at_full_resolution_but_measured_in_logical_px(scale):
    scale(1.0)
    w1, h1 = T.font(16).size("Zero Day")
    scale(2.0)
    img = T.font(16).render("Zero Day", True, (0, 0, 0))
    assert img.real.get_height() >= 2 * h1 - 2               # really drawn bigger...
    assert abs(img.get_width() - w1) <= 2                    # ...but the layout sees the same size
    assert abs(T.font(16).size("Zero Day")[0] - w1) <= 2


def test_cached_text_is_not_changed_by_set_alpha(scale):
    scale(1.0)
    a = T.font(14).render("cache", True, (0, 0, 0))
    a.set_alpha(10)
    b = T.font(14).render("cache", True, (0, 0, 0))
    assert b.get_alpha() in (None, 255)


def test_plain_window_on_the_dummy_driver_is_scale_1(scale):
    d = hidpi.Display("test")
    assert not d.hidpi
    s = d.open((1600, 900), False)
    assert hidpi.K == 1.0 and s.get_size() == (1600, 900)
    assert d.to_logical((123, 45)) == (123, 45)
    assert d.refit() is False
