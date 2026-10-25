"""Small rendering helpers: additive glow sprites, text, dashed lines and
short-lived visual effects (ripples, beams, bursts, floating text)."""

import math
import random

import pygame

from ui import theme as T

_glow_cache = {}


def glow(radius, color, intensity=1.0):
    """A soft radial glow sprite, meant to be blitted with BLEND_RGB_ADD."""
    key = (int(radius), color, round(intensity, 2))
    s = _glow_cache.get(key)
    if s is None:
        r = max(2, int(radius))
        s = pygame.Surface((r * 2, r * 2))
        s.fill((0, 0, 0))
        for i in range(r, 0, -1):
            t = i / r
            k = intensity * (1 - t) ** 2.2
            pygame.draw.circle(s, T.scale(color, k), (r, r), i)
        _glow_cache[key] = s
    return s


def blit_glow(surf, pos, radius, color, intensity=1.0):
    g = glow(radius, color, intensity)
    surf.blit(g, (pos[0] - g.get_width() // 2, pos[1] - g.get_height() // 2), special_flags=pygame.BLEND_RGB_ADD)


def text(surf, s, pos, size=14, color=T.TEXT, weight="regular", mono=False, anchor="topleft", alpha=None):
    img = T.font(size, weight, mono).render(str(s), True, color)
    if alpha is not None:
        img.set_alpha(alpha)
    r = img.get_rect(**{anchor: pos})
    surf.blit(img, r)
    return r


def spaced(surf, s, pos, size=12, color=T.MUTED, weight="semibold", spacing=2, anchor="topleft"):
    """Letter-spaced small caps style label."""
    f = T.font(size, weight)
    glyphs = [f.render(ch, True, color) for ch in s]
    width = sum(g.get_width() for g in glyphs) + spacing * (len(glyphs) - 1)
    r = pygame.Rect(0, 0, width, f.get_height())
    setattr(r, anchor, pos)
    x = r.x
    for g in glyphs:
        surf.blit(g, (x, r.y))
        x += g.get_width() + spacing
    return r


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


def rounded_panel(surf, rect, fill=T.PANEL, border=T.PANEL_EDGE, radius=12, alpha=235):
    s = pygame.Surface(rect.size, pygame.SRCALPHA)
    pygame.draw.rect(s, (*fill, alpha), s.get_rect(), border_radius=radius)
    pygame.draw.rect(s, (*border, 255), s.get_rect(), 1, border_radius=radius)
    surf.blit(s, rect.topleft)


def bar(surf, rect, frac, color, bg=(22, 34, 62), radius=3):
    pygame.draw.rect(surf, bg, rect, border_radius=radius)
    w = int(rect.w * max(0.0, min(1.0, frac)))
    if w > 0:
        pygame.draw.rect(surf, color, pygame.Rect(rect.x, rect.y, w, rect.h), border_radius=radius)


def hexagon(surf, color, center, r, width=2, rot=0.0):
    pts = [(center[0] + r * math.cos(rot + i * math.pi / 3), center[1] + r * math.sin(rot + i * math.pi / 3))
           for i in range(6)]
    pygame.draw.polygon(surf, color, pts, width)


def diamond(surf, color, center, r, width=2):
    x, y = center
    pygame.draw.polygon(surf, color, [(x, y - r), (x + r, y), (x, y + r), (x - r, y)], width)


# -- effects --------------------------------------------------------------------
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
    def __init__(self, pos, color, max_r=46, duration=1.1, width=2, dashed=False):
        super().__init__(duration)
        self.pos, self.color, self.max_r, self.width, self.dashed = pos, color, max_r, width, dashed

    def draw(self, surf):
        k = self.k
        r = 8 + (self.max_r - 8) * (1 - (1 - k) ** 2)
        c = T.scale(self.color, 1 - k)
        if self.dashed:
            n = 16
            for i in range(0, n, 2):
                a0, a1 = i / n * 2 * math.pi, (i + 1) / n * 2 * math.pi
                rect = pygame.Rect(0, 0, 2 * r, 2 * r)
                rect.center = self.pos
                pygame.draw.arc(surf, c, rect, a0, a1, self.width)
        else:
            pygame.draw.circle(surf, c, self.pos, int(r), self.width)


class Beam(Effect):
    def __init__(self, a, b, color, duration=0.7, success=True):
        super().__init__(duration)
        self.a, self.b, self.color, self.success = a, b, color, success
        self.seed = random.random() * 1000

    def draw(self, surf):
        k = self.k
        rng = random.Random(self.seed + int(self.t * 30))
        reach = min(1.0, k * 2.2) if self.success else min(0.7, k * 2.2)
        ax, ay = self.a
        bx, by = self.b
        ex, ey = ax + (bx - ax) * reach, ay + (by - ay) * reach
        pts = [(ax, ay)]
        n = 7
        for i in range(1, n):
            t = i / n
            jitter = 6 * (1 - k)
            pts.append((ax + (ex - ax) * t + rng.uniform(-jitter, jitter), ay + (ey - ay) * t + rng.uniform(-jitter, jitter)))
        pts.append((ex, ey))
        fade = 1 - max(0.0, (k - 0.5) * 2)
        pygame.draw.lines(surf, T.scale(self.color, 0.5 * fade), False, pts, 6)
        pygame.draw.lines(surf, T.scale(T.mix(self.color, T.WHITE, 0.5), fade), False, pts, 2)
        blit_glow(surf, (int(ex), int(ey)), 26, self.color, 0.8 * fade)


class Burst(Effect):
    def __init__(self, pos, color, n=26, speed=140, duration=0.9):
        super().__init__(duration)
        self.pos, self.color = pos, color
        self.parts = []
        for _ in range(n):
            a = random.uniform(0, 2 * math.pi)
            v = random.uniform(0.3, 1.0) * speed
            self.parts.append([pos[0], pos[1], math.cos(a) * v, math.sin(a) * v])

    def update(self, dt):
        super().update(dt)
        for p in self.parts:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[2] *= 0.92
            p[3] *= 0.92

    def draw(self, surf):
        fade = 1 - self.k
        c = T.scale(self.color, fade)
        for x, y, _, _ in self.parts:
            pygame.draw.circle(surf, c, (int(x), int(y)), 2)
        if self.k < 0.35:
            blit_glow(surf, self.pos, int(30 + 50 * self.k), self.color, 1.2 * (1 - self.k / 0.35))


class FloatText(Effect):
    def __init__(self, pos, s, color, size=13, duration=1.6):
        super().__init__(duration)
        self.pos, self.s, self.color, self.size = pos, s, color, size

    def draw(self, surf):
        k = self.k
        a = int(255 * (1 - max(0.0, (k - 0.6) / 0.4)))
        y = self.pos[1] - 28 * (1 - (1 - k) ** 3)
        text(surf, self.s, (self.pos[0], y), self.size, self.color, "bold", anchor="midbottom", alpha=a)


class Flash(Effect):
    def __init__(self, color, duration=0.5, strength=90):
        super().__init__(duration)
        self.color, self.strength = color, strength

    def draw(self, surf):
        a = int(self.strength * (1 - self.k))
        s = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        s.fill((*self.color, a))
        surf.blit(s, (0, 0))
