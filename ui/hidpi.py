"""Sharp drawing on any display.

The interface is laid out in fixed logical pixels (1600 x 900 on a computer).
Instead of drawing at that size and stretching the picture to the window, every
drawing call is scaled up by the window's real pixel density and drawn at full
resolution, so text and lines stay crisp on Retina, 4K, 1080p and small laptop
screens alike, in a window of any size or in fullscreen.

    Canvas        a surface that takes logical coordinates; .real is the pixel surface
    Surface()     drop-in for pygame.Surface, returns a Canvas at the current scale
    rect, line, circle, polygon, arc, lines
                  drop-ins for pygame.draw.*
    Font          a font that renders at the current scale (ui/theme.py hands these out)
    Display       the window: picks the scale, shows the canvas, maps the mouse back
    mouse_pos()   mouse position in logical coordinates

In the browser (pygbag) and with SDL's dummy driver (tests) the scale is 1 and
pygame's own SCALED window is used, as before. Set ZERO_DAY_HIDPI=0 to force
that on a computer too."""

import math
import os
import sys

import pygame

WEB = sys.platform == "emscripten"

K = 1.0               # logical px -> real px; set by Display
_display = None       # the open Display, for mouse_pos()


def _s(v, k):
    return int(round(v * k))


def _pt(p, k):
    return (p[0] * k, p[1] * k)


def _rect(r, k):
    """Scale a rect by its edges, so neighbouring rects still meet without gaps."""
    r = pygame.Rect(r)
    x0, y0, x1, y1 = _s(r.x, k), _s(r.y, k), _s(r.right, k), _s(r.bottom, k)
    return pygame.Rect(x0, y0, x1 - x0, y1 - y0)


def _width(w, k):
    return 0 if w <= 0 else max(1, _s(w, k))


class Canvas:
    """A pixel surface addressed in logical coordinates."""

    def __init__(self, real, k, size=None):
        self.real, self.k = real, k
        self._size = tuple(size) if size else (round(real.get_width() / k), round(real.get_height() / k))
        self._clip = None
        self._shared = False          # pixels shared with a cache: copy before changing them

    def _own(self):
        if self._shared:
            self.real, self._shared = self.real.copy(), False

    # size
    def get_size(self):
        return self._size

    def get_width(self):
        return self._size[0]

    def get_height(self):
        return self._size[1]

    def get_rect(self, **kw):
        r = pygame.Rect((0, 0), self._size)
        for name, v in kw.items():
            setattr(r, name, v)
        return r

    # pixels
    def blit(self, src, dest, area=None, special_flags=0):
        k = self.k
        if isinstance(dest, pygame.Rect) or len(dest) == 4:
            dx, dy = pygame.Rect(dest).topleft
        else:
            dx, dy = dest
        self._own()
        img = _real_at(src, k)
        a = None if area is None else _rect(area, k)
        got = self.real.blit(img, (_s(dx, k), _s(dy, k)), a, special_flags)
        return pygame.Rect(dx, dy, round(got.w / k), round(got.h / k))

    def fill(self, color, rect=None, special_flags=0):
        self._own()
        self.real.fill(color, None if rect is None else _rect(rect, self.k), special_flags)
        return self.get_rect() if rect is None else pygame.Rect(rect)

    def set_at(self, pos, color):
        self._own()
        self.real.fill(color, _rect((int(pos[0]), int(pos[1]), 1, 1), self.k))

    def get_at(self, pos):
        return self.real.get_at((min(self.real.get_width() - 1, _s(pos[0], self.k)),
                                 min(self.real.get_height() - 1, _s(pos[1], self.k))))

    def set_clip(self, rect=None):
        self._clip = None if rect is None else pygame.Rect(rect)
        self.real.set_clip(None if rect is None else _rect(rect, self.k))

    def get_clip(self):
        return pygame.Rect(self._clip) if self._clip is not None else self.get_rect()

    def subsurface(self, rect):
        r = pygame.Rect(rect)
        real = _rect(r, self.k).clip(self.real.get_rect())
        return Canvas(self.real.subsurface(real), self.k, r.size)

    def copy(self):
        return Canvas(self.real.copy(), self.k, self._size)

    def convert(self, *a):
        return Canvas(self.real.convert(*a), self.k, self._size)

    def convert_alpha(self, *a):
        return Canvas(self.real.convert_alpha(*a), self.k, self._size)

    def set_alpha(self, *a):
        self._own()
        self.real.set_alpha(*a)

    def get_alpha(self):
        return self.real.get_alpha()

    def set_colorkey(self, *a):
        self._own()
        self.real.set_colorkey(*a)

    def get_flags(self):
        return self.real.get_flags()


def _real_at(src, k):
    """The pixel surface of src, drawn at scale k (a canvas made at another scale, or a plain
    pygame surface, is resampled so it still lands at the right size)."""
    if isinstance(src, Canvas):
        if abs(src.k - k) < 1e-6:
            return src.real
        w, h = src.get_size()
        return pygame.transform.smoothscale(src.real, (max(1, _s(w, k)), max(1, _s(h, k))))
    if abs(k - 1.0) < 1e-6:
        return src
    w, h = src.get_size()
    return pygame.transform.smoothscale(src, (max(1, _s(w, k)), max(1, _s(h, k))))


def Surface(size, flags=0, *args):            # noqa: N802 (drop-in for pygame.Surface)
    w, h = int(size[0]), int(size[1])
    real = pygame.Surface((max(1, math.ceil(w * K)), max(1, math.ceil(h * K))), flags, *args)
    return Canvas(real, K, (w, h))


def wrap(surf):
    """A pygame surface as a 1:1 canvas."""
    return surf if isinstance(surf, Canvas) else Canvas(surf, 1.0)


def real(surf):
    return surf.real if isinstance(surf, Canvas) else surf


def smoothscale(surf, size):
    """pygame.transform.smoothscale for canvases (size in logical px)."""
    if not isinstance(surf, Canvas):
        return pygame.transform.smoothscale(surf, size)
    k = surf.k
    out = pygame.transform.smoothscale(surf.real, (max(1, _s(size[0], k)), max(1, _s(size[1], k))))
    return Canvas(out, k, size)


def save(surf, path):
    pygame.image.save(real(surf), path)


# -- pygame.draw drop-ins -------------------------------------------------------------
def rect(surf, color, r, width=0, border_radius=0, border_top_left_radius=-1, border_top_right_radius=-1,
         border_bottom_left_radius=-1, border_bottom_right_radius=-1):
    if not isinstance(surf, Canvas):
        return pygame.draw.rect(surf, color, r, width, border_radius, border_top_left_radius,
                                border_top_right_radius, border_bottom_left_radius, border_bottom_right_radius)
    k = surf.k

    def rad(v):
        return v if v < 0 else _s(v, k)

    pygame.draw.rect(surf.real, color, _rect(r, k), _width(width, k), rad(border_radius),
                     rad(border_top_left_radius), rad(border_top_right_radius),
                     rad(border_bottom_left_radius), rad(border_bottom_right_radius))
    return pygame.Rect(r)


def line(surf, color, a, b, width=1):
    if not isinstance(surf, Canvas):
        return pygame.draw.line(surf, color, a, b, width)
    k = surf.k
    w = _width(width, k)
    pa, pb = _pt(a, k), _pt(b, k)
    if w <= 1:
        pygame.draw.aaline(surf.real, color, pa, pb)
    else:
        pygame.draw.line(surf.real, color, pa, pb, w)
    return pygame.Rect(min(a[0], b[0]), min(a[1], b[1]), abs(b[0] - a[0]) + 1, abs(b[1] - a[1]) + 1)


def lines(surf, color, closed, points, width=1):
    if not isinstance(surf, Canvas):
        return pygame.draw.lines(surf, color, closed, points, width)
    k = surf.k
    pygame.draw.lines(surf.real, color, closed, [_pt(p, k) for p in points], _width(width, k))
    return _bounds(points)


def circle(surf, color, center, radius, width=0, draw_top_right=None, draw_top_left=None,
           draw_bottom_left=None, draw_bottom_right=None):
    quarters = {name: v for name, v in (("draw_top_right", draw_top_right), ("draw_top_left", draw_top_left),
                                        ("draw_bottom_left", draw_bottom_left),
                                        ("draw_bottom_right", draw_bottom_right)) if v is not None}
    if not isinstance(surf, Canvas):
        return pygame.draw.circle(surf, color, center, radius, width, **quarters)
    k = surf.k
    pygame.draw.circle(surf.real, color, _pt(center, k), radius * k, _width(width, k), **quarters)
    return pygame.Rect(center[0] - radius, center[1] - radius, 2 * radius, 2 * radius)


def polygon(surf, color, points, width=0):
    if not isinstance(surf, Canvas):
        return pygame.draw.polygon(surf, color, points, width)
    k = surf.k
    pygame.draw.polygon(surf.real, color, [_pt(p, k) for p in points], _width(width, k))
    return _bounds(points)


def arc(surf, color, r, start, stop, width=1):
    if not isinstance(surf, Canvas):
        return pygame.draw.arc(surf, color, r, start, stop, width)
    k = surf.k
    pygame.draw.arc(surf.real, color, _rect(r, k), start, stop, _width(width, k))
    return pygame.Rect(r)


def _bounds(points):
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return pygame.Rect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


# -- fonts ---------------------------------------------------------------------------
class Font:
    """A font that renders at the current scale. Sizes and widths it reports are logical."""

    def __init__(self, load, size):
        self._load, self.size_px = load, size
        self._real = {}
        self._cache = {}              # most text is the same from frame to frame

    def _at(self, k):
        px = max(1, _s(self.size_px, k))
        f = self._real.get(px)
        if f is None:
            f = self._real[px] = self._load(px)
        return f

    def render(self, text, antialias=True, color=(0, 0, 0), background=None):
        k = K
        key = (text, antialias, tuple(color), None if background is None else tuple(background), k)
        img = self._cache.get(key)
        if img is None:
            if len(self._cache) > 512:
                self._cache.clear()
            img = self._cache[key] = self._at(k).render(text, antialias, color, background)
        c = Canvas(img, k)
        c._shared = True
        return c

    def size(self, text):
        w, h = self._at(K).size(text)
        return round(w / K), round(h / K)

    def get_height(self):
        return round(self._at(K).get_height() / K)

    def get_linesize(self):
        return round(self._at(K).get_linesize() / K)

    def get_ascent(self):
        return round(self._at(K).get_ascent() / K)

    def get_descent(self):
        return round(self._at(K).get_descent() / K)


# -- the window ------------------------------------------------------------------------
def mouse_pos():
    """Mouse position in logical coordinates."""
    p = pygame.mouse.get_pos()
    return _display.to_logical(p) if _display is not None else p


def _want_hidpi():
    if WEB or os.environ.get("ZERO_DAY_HIDPI", "1") == "0":
        return False
    return pygame.display.get_driver() not in ("dummy", "offscreen")


class Display:
    """The game window. On a computer: a high-DPI window that the canvas is fitted into
    (letterboxed to keep the shape), drawn at the window's real pixel size. Elsewhere:
    pygame's SCALED display at scale 1."""

    def __init__(self, title):
        global _display
        self.title = title
        self.hidpi = _want_hidpi()
        self.window = self.renderer = None
        self.logical = (1600, 900)
        self.fullscreen = False
        self.screen = None
        self.dest = None
        self._pixels = None
        _display = self

    # setup
    def open(self, logical, fullscreen):
        """(Re)open for a logical size. Returns the canvas to draw on."""
        global K
        self.logical, self.fullscreen = tuple(logical), fullscreen
        if self.hidpi and self.window is None:
            try:
                self._open_window()
            except Exception as e:  # noqa: BLE001 (no renderer: fall back to the plain window)
                print("Zero Day: high-DPI window unavailable, using a scaled one:", e)
                self.hidpi = False
        if not self.hidpi:
            K = 1.0
            if pygame.display.get_surface() is not None and pygame.display.get_driver() in ("dummy", "offscreen"):
                pygame.display.quit()        # SDL's software-only drivers crash if a SCALED window changes size
                pygame.display.init()
            flags = pygame.SCALED | (pygame.FULLSCREEN if fullscreen else pygame.RESIZABLE)
            self.screen = Canvas(pygame.display.set_mode(self.logical, flags), 1.0, self.logical)
            pygame.display.set_caption(self.title)
            return self.screen
        self._pixels = None
        self.refit()
        return self.screen

    def _open_window(self):
        from pygame._sdl2.video import Window, Renderer
        dw, dh = pygame.display.get_desktop_sizes()[0]
        lw, lh = self.logical
        w = min(dw * 0.9, dh * 0.9 * lw / lh)            # the biggest window of the game's shape that fits
        size = (int(w), int(w * lh / lw))
        self.window = Window(self.title, size=size, position=pygame.WINDOWPOS_CENTERED, resizable=True,
                             allow_high_dpi=True)
        self.window.minimum_size = (480, 270)
        self.renderer = Renderer(self.window, accelerated=-1, vsync=False)
        if self.fullscreen:
            self.window.set_fullscreen(desktop=True)

    def _pixel_size(self):
        self.renderer.set_viewport(None)
        r = self.renderer.get_viewport()
        return r.w, r.h

    def refit(self):
        """Match the canvas to the window's current pixel size. True if the scale changed
        (anything drawn ahead of time at the old scale should then be redrawn)."""
        global K
        if not self.hidpi:
            return False
        px = self._pixel_size()
        if px == self._pixels and self.screen is not None:
            return False
        self._pixels = px
        lw, lh = self.logical
        k = max(0.25, min(px[0] / lw, px[1] / lh))
        old = K
        K = k
        self.screen = Surface(self.logical)
        rw, rh = self.screen.real.get_size()
        self.dest = pygame.Rect((px[0] - rw) // 2, (px[1] - rh) // 2, rw, rh)
        return abs(old - k) > 1e-6

    def toggle_fullscreen(self, on):
        self.fullscreen = on
        if not self.hidpi:
            try:
                pygame.display.toggle_fullscreen()
            except pygame.error:
                pass
            return
        if on:
            self.window.set_fullscreen(desktop=True)
        else:
            self.window.set_windowed()

    # every frame
    def present(self):
        if not self.hidpi:
            pygame.display.flip()
            return
        from pygame._sdl2.video import Texture
        r = self.renderer
        bar = self.screen.real.get_at((0, 0))
        r.draw_color = (bar.r, bar.g, bar.b, 255)
        r.clear()
        Texture.from_surface(r, self.screen.real).draw(dstrect=self.dest)
        r.present()

    def to_logical(self, pos):
        if not self.hidpi or self.dest is None:
            return pos
        ww, wh = self.window.size
        pw, ph = self._pixels
        x = pos[0] * pw / max(1, ww)
        y = pos[1] * ph / max(1, wh)
        return int((x - self.dest.x) / K), int((y - self.dest.y) / K)

    def map_event(self, ev):
        """The event with its mouse position in logical coordinates."""
        if not self.hidpi or not hasattr(ev, "pos"):
            return ev
        d = dict(ev.dict)
        d["pos"] = self.to_logical(ev.pos)
        if "rel" in d and self._pixels:
            sx = self._pixels[0] / max(1, self.window.size[0]) / K
            d["rel"] = (int(d["rel"][0] * sx), int(d["rel"][1] * sx))
        return pygame.event.Event(ev.type, d)
