"""Small rendering helpers (text, rules, dashed lines, hatching, bars) and
short-lived effects. Effects are drawn as ink on paper: they fade towards the
paper colour instead of glowing."""

import math
import random

import pygame

from ui import theme as T


def text(surf, s, pos, size=14, color=T.TEXT, weight="regular", mono=False, anchor="topleft", alpha=None,
         display=False, bg=None):
    img = T.font(size, weight, mono, display).render(str(s), True, color)
    if alpha is not None:
        img.set_alpha(alpha)
    r = img.get_rect(**{anchor: pos})
    if bg is not None:
        pygame.draw.rect(surf, bg, r.inflate(4, -2))
    surf.blit(img, r)
    return r


def spaced(surf, s, pos, size=12, color=T.MUTED, weight="semibold", spacing=2, anchor="topleft", display=True):
    """Letter-spaced caps label (condensed display face by default)."""
    f = T.font(size, weight, display=display)
    glyphs = [f.render(ch, True, color) for ch in s]
    width = sum(g.get_width() for g in glyphs) + spacing * (len(glyphs) - 1)
    r = pygame.Rect(0, 0, width, f.get_height())
    setattr(r, anchor, pos)
    x = r.x
    for g in glyphs:
        surf.blit(g, (x, r.y))
        x += g.get_width() + spacing
    return r


def label(surf, s, pos, color=T.INK_2, anchor="topleft"):
    """Section label: condensed caps, slightly spaced."""
    return spaced(surf, s.upper(), pos, 14, color, "semibold", 1, anchor)


def hrule(surf, x0, x1, y, color=T.RULE, width=1):
    pygame.draw.line(surf, color, (x0, y), (x1, y), width)


def dashed_line(surf, color, a, b, width=2, dash=8, gap=6, offset=0.0):
    ax, ay = a
    bx, by = b
    length = math.hypot(bx - ax, by - ay)
    if length < 1:
        return
    ux, uy = (bx - ax) / length, (by - ay) / length
    period = dash + gap
    d = -(offset % period)
    while d < length:
        s0, s1 = max(0, d), min(length, d + dash)
        if s1 > s0:
            pygame.draw.line(surf, color, (ax + ux * s0, ay + uy * s0), (ax + ux * s1, ay + uy * s1), width)
        d += period


def dashed_circle(surf, color, center, r, width=1, n=20, rot=0.0):
    rect = pygame.Rect(0, 0, 2 * r, 2 * r)
    rect.center = center
    for i in range(0, n, 2):
        a0 = rot + i / n * 2 * math.pi
        pygame.draw.arc(surf, color, rect, a0, a0 + 2 * math.pi / n, width)


def hatch(surf, rect, color, step=7, width=1):
    """45-degree hatching inside rect (clipped)."""
    old = surf.get_clip()
    surf.set_clip(rect if old is None else rect.clip(old))
    for x in range(rect.x - rect.h, rect.right, step):
        pygame.draw.line(surf, color, (x, rect.bottom), (x + rect.h, rect.y), width)
    surf.set_clip(old)


def bar(surf, rect, frac, color, bg=T.PAPER_3, radius=0):
    pygame.draw.rect(surf, bg, rect, border_radius=radius)
    w = int(rect.w * max(0.0, min(1.0, frac)))
    if w > 0:
        pygame.draw.rect(surf, color, pygame.Rect(rect.x, rect.y, w, rect.h), border_radius=radius)


def arrowhead(surf, color, tip, frm, size=7):
    ang = math.atan2(tip[1] - frm[1], tip[0] - frm[0])
    pts = [tip,
           (tip[0] - size * math.cos(ang - 0.45), tip[1] - size * math.sin(ang - 0.45)),
           (tip[0] - size * math.cos(ang + 0.45), tip[1] - size * math.sin(ang + 0.45))]
    pygame.draw.polygon(surf, color, pts)


def diamond(surf, color, center, r, width=0):
    x, y = center
    pygame.draw.polygon(surf, color, [(x, y - r), (x + r, y), (x, y + r), (x - r, y)], width)


def tag(surf, s, center, color, size=11, fill=None):
    """Small label on a paper chip, used for floating notes on the map."""
    img = T.font(size, "semibold", display=True).render(s, True, color)
    r = img.get_rect(center=center).inflate(10, 2)
    pygame.draw.rect(surf, fill or T.PAPER, r)
    pygame.draw.rect(surf, color, r, 1)
    surf.blit(img, img.get_rect(center=r.center))
    return r


# -- effects --------------------------------------------------------------------
def _ease(k):
    return 1 - (1 - k) ** 3


class Effect:
    def __init__(self, duration):
        self.t, self.duration = 0.0, duration

    @property
    def done(self):
        return self.t >= self.duration

    def update(self, dt):
        self.t += dt

    @property
    def k(self):
        return min(1.0, self.t / self.duration)


class Ripple(Effect):
    """A single ring that opens out and fades into the paper."""

    def __init__(self, pos, color, max_r=46, duration=1.1, width=2, dashed=False):
        super().__init__(duration)
        self.pos, self.color, self.max_r, self.width, self.dashed = pos, color, max_r, width, dashed

    def draw(self, surf):
        k = self.k
        r = int(10 + (self.max_r - 10) * _ease(k))
        c = T.fade(self.color, k ** 1.5)
        if self.dashed:
            dashed_circle(surf, c, self.pos, r, self.width, 18)
        else:
            pygame.draw.circle(surf, c, self.pos, r, self.width)


class Beam(Effect):
    """A pen stroke from a to b. A failed move stops short and is struck out."""

    def __init__(self, a, b, color, duration=0.7, success=True):
        super().__init__(duration)
        self.a, self.b, self.color, self.success = a, b, color, success

    def draw(self, surf):
        k = self.k
        reach = _ease(min(1.0, k * 1.8)) * (1.0 if self.success else 0.62)
        ax, ay = self.a
        bx, by = self.b
        ex, ey = ax + (bx - ax) * reach, ay + (by - ay) * reach
        c = T.fade(self.color, max(0.0, (k - 0.6) / 0.4))
        pygame.draw.line(surf, c, self.a, (ex, ey), 3)
        if reach > 0.05:
            arrowhead(surf, c, (ex, ey), self.a, 9)
        if not self.success and k > 0.4:
            x, y = ex, ey
            s = 6
            pygame.draw.line(surf, c, (x - s + 8, y - s), (x + s + 8, y + s), 2)
            pygame.draw.line(surf, c, (x - s + 8, y + s), (x + s + 8, y - s), 2)


class Burst(Effect):
    """A short 'stamp': a ring snaps in and eight ticks spread out."""

    def __init__(self, pos, color, n=26, speed=140, duration=0.9):
        super().__init__(duration)
        self.pos, self.color = pos, color
        self.size = max(18, min(48, speed / 5))

    def draw(self, surf):
        k = self.k
        c = T.fade(self.color, k ** 1.3)
        x, y = self.pos
        r0 = self.size * (0.6 + 0.6 * _ease(k))
        for i in range(8):
            a = i * math.pi / 4 + math.pi / 8
            p0 = (x + math.cos(a) * r0, y + math.sin(a) * r0)
            p1 = (x + math.cos(a) * (r0 + 7), y + math.sin(a) * (r0 + 7))
            pygame.draw.line(surf, c, p0, p1, 2)
        if k < 0.5:
            pygame.draw.circle(surf, c, self.pos, int(self.size * 0.55), 2)


class FloatText(Effect):
    def __init__(self, pos, s, color, size=13, duration=1.6):
        super().__init__(duration)
        self.pos, self.s, self.color, self.size = pos, s, color, size

    def draw(self, surf):
        k = self.k
        a = int(255 * (1 - max(0.0, (k - 0.7) / 0.3)))
        y = self.pos[1] - 22 - 14 * _ease(k)
        img = T.font(self.size + 2, "bold", display=True).render(self.s, True, self.color)
        r = img.get_rect(midbottom=(self.pos[0], y)).inflate(10, 0)
        chip = pygame.Surface(r.size, pygame.SRCALPHA)
        chip.fill((*T.PAPER, 240))
        pygame.draw.rect(chip, (*self.color, 255), chip.get_rect(), 1)
        chip.blit(img, img.get_rect(center=(r.w // 2, r.h // 2)))
        chip.set_alpha(a)
        surf.blit(chip, r)


class Flash(Effect):
    """A brief wash of colour over the whole screen."""

    def __init__(self, color, duration=0.5, strength=90):
        super().__init__(duration)
        self.color, self.strength = color, strength * 0.45

    def draw(self, surf):
        a = int(self.strength * (1 - self.k) ** 2)
        if a <= 0:
            return
        s = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        s.fill((*self.color, a))
        surf.blit(s, (0, 0))
