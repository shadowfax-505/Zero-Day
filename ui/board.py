"""Network renderer: zones, links, nodes, Red's route, Blue's belief map and
per-view fog of war."""

import math
import random

import pygame

from engine import config as C
from engine.mapgen import ZONE_X
from ui import fx
from ui import theme as T

VIEWS = ["red", "full", "blue"]
VIEW_NAMES = {"red": "RED'S VIEW", "full": "FULL VIEW", "blue": "BLUE'S VIEW"}


class Board:
    def __init__(self, net, rect=T.BOARD):
        self.net = net
        self.rect = rect
        pad_x, pad_y = 30, 46
        self.inner = rect.inflate(-2 * pad_x, -2 * pad_y)
        self.inner.y += 10
        self.pts = [self.to_screen(p) for p in net.pos]
        self.pulses = []
        self.rng = random.Random(net.seed)
        self.particle_jitter = [(self.rng.uniform(-1, 1), self.rng.uniform(-1, 1)) for _ in range(600)]
        self.zone_rects = []
        for z, (x0, x1) in enumerate(ZONE_X):
            a = self.to_screen((x0 - 0.035, 0.02))
            b = self.to_screen((x1 + 0.035, 0.98))
            self.zone_rects.append(pygame.Rect(a[0], a[1] - 18, b[0] - a[0], b[1] - a[1] + 18))
        self.edges = list(net.edges())
        self._static = None

    def to_screen(self, p):
        return (int(self.inner.x + p[0] * self.inner.w), int(self.inner.y + p[1] * self.inner.h))

    def node_at(self, pos, visible=None):
        best, bd = None, 22
        for i, p in enumerate(self.pts):
            if visible is not None and i not in visible:
                continue
            d = math.hypot(p[0] - pos[0], p[1] - pos[1])
            if d < bd:
                best, bd = i, d
        return best

    def radius(self, u):
        k = self.net.kind[u]
        return 19 if k == "database" else 15 if k == "gateway" else 12 if k == "bridge" else 11

    # -- drawing -------------------------------------------------------------------
    def draw(self, surf, g, view, t, red_dbg=None, blue_dbg=None, highlight=(), hover=None, monitored_preview=()):
        net = self.net
        red_dbg = red_dbg or {}
        blue_dbg = blue_dbg or {}
        show_red = view in ("red", "full")
        show_blue = view in ("blue", "full")
        visible = set(range(net.n)) if view != "red" else set(g.red_known) | {net.database}
        known_edges = None
        if view == "red":
            known_edges = {frozenset((u, v)) for u, vs in g.red_known_edges.items() for v in vs}

        self._draw_zones(surf, g, view, t, monitored_preview)

        # links
        for u, v in self.edges:
            e = frozenset((u, v))
            if known_edges is not None and e not in known_edges:
                continue
            a, b = self.pts[u], self.pts[v]
            gate = e in net.gates
            opened = e in g.open_gates
            held_both = show_red and u in g.red_held and v in g.red_held
            if held_both:
                col = T.scale(T.RED, 0.55)
                pygame.draw.line(surf, col, a, b, 3)
            elif gate and not opened:
                fx.dashed_line(surf, T.scale(T.EDGE_LIT, 0.9), a, b, 2, 6, 5)
            else:
                pygame.draw.line(surf, T.EDGE if not gate else T.EDGE_LIT, a, b, 2)
            if gate:
                m = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
                lock_col = T.RED_SOFT if opened and show_red else T.BLUE_SOFT
                pygame.draw.circle(surf, T.BG, m, 6)
                pygame.draw.circle(surf, lock_col, m, 6, 2)
                if not opened:
                    pygame.draw.line(surf, lock_col, (m[0] - 2, m[1]), (m[0] + 2, m[1]), 2)

        self._draw_pulses(surf, known_edges, t)
        if view == "red":
            self._draw_fog(surf, visible, t)

        # Blue's belief: halos and particles
        if show_blue and blue_dbg.get("belief") is not None:
            b = blue_dbg["belief"]
            for u in range(net.n):
                if b[u] > 0.01:
                    fx.blit_glow(surf, self.pts[u], int(26 + 70 * min(1.0, b[u] * 1.6)), T.BLUE, 0.35 + 0.9 * min(1.0, b[u] * 2))
            parts = blue_dbg.get("particles")
            if parts is not None:
                for i, u in enumerate(parts[:600]):
                    jx, jy = self.particle_jitter[i % len(self.particle_jitter)]
                    wob = math.sin(t * 2 + i) * 3
                    p = self.pts[int(u)]
                    surf.set_at((int(p[0] + jx * 20 + wob), int(p[1] + jy * 20)), T.BLUE_SOFT)

        # Red's planned route
        if show_red and red_dbg.get("route"):
            route = red_dbg["route"]
            for i in range(len(route) - 1):
                fx.dashed_line(surf, T.RED, self.pts[route[i]], self.pts[route[i + 1]], 3, 10, 7, offset=-t * 40)
            if not red_dbg.get("reaches_db") and route:
                fx.dashed_line(surf, T.scale(T.RED, 0.45), self.pts[route[-1]], self.pts[net.database], 1, 3, 7,
                               offset=-t * 25)

        # nodes
        for u in range(net.n):
            if u not in visible:
                continue
            self._draw_node(surf, g, u, view, t, show_red, show_blue, u in highlight, u == hover, red_dbg)

        # last round's alerts (Blue sees these, never whether they are real)
        if show_blue and g.history:
            for u, strength, real in g.history[-1].alerts:
                p = self.pts[u]
                x, y = p[0] + self.radius(u) + 4, p[1] - self.radius(u) - 4
                col = T.AMBER if (real or view == "blue") else T.DIM
                pygame.draw.polygon(surf, col, [(x, y - 8), (x + 7, y + 5), (x - 7, y + 5)])
                fx.text(surf, "!", (x, y + 1), 10, T.BG, "black", anchor="center")

        # Red's marker
        if show_red and g.winner != "blue":
            p = self.pts[g.red_pos]
            pulse = 0.5 + 0.5 * math.sin(t * 5)
            fx.blit_glow(surf, p, int(40 + 10 * pulse), T.RED, 1.1)
            pygame.draw.circle(surf, T.RED, p, int(self.radius(g.red_pos) + 7 + 3 * pulse), 2)
            # chevron above
            x, y = p[0], p[1] - self.radius(g.red_pos) - 16 - 3 * pulse
            pygame.draw.polygon(surf, T.RED, [(x - 7, y - 6), (x + 7, y - 6), (x, y + 2)])

    def _draw_zones(self, surf, g, view, t, monitored_preview):
        mon = set(monitored_preview)
        for z, r in enumerate(self.zone_rects):
            s = pygame.Surface(r.size, pygame.SRCALPHA)
            pygame.draw.rect(s, (*T.ZONE_TINT[z], 46), s.get_rect(), border_radius=18)
            if z in mon and view != "red":
                a = int(90 + 60 * math.sin(t * 4))
                pygame.draw.rect(s, (*T.BLUE, a), s.get_rect(), 2, border_radius=18)
            else:
                pygame.draw.rect(s, (*T.ZONE_TINT[z], 140), s.get_rect(), 1, border_radius=18)
            surf.blit(s, r.topleft)
            label = f"ZONE {z + 1} · {C.ZONE_NAMES[z]}"
            fx.spaced(surf, label, (r.x + 16, r.y + 10), 11, T.MUTED, "semibold", 2)
            if z in mon and view != "red":
                fx.spaced(surf, "MONITORED", (r.centerx, r.bottom - 12), 10, T.BLUE_SOFT, "bold", 3,
                          anchor="midbottom")

    def _draw_fog(self, surf, visible, t):
        """Fog of war over everything Red has not seen yet."""
        key = frozenset(visible)
        if getattr(self, "_fog_key", None) != key:
            self._fog_key = key
            fog = pygame.Surface(self.rect.size, pygame.SRCALPHA)
            fog.fill((6, 11, 26, 215))
            hole = pygame.Surface((240, 240), pygame.SRCALPHA)
            hole.fill((6, 11, 26, 215))
            for i in range(120, 0, -3):
                a = int(215 * (i / 120) ** 1.6)
                pygame.draw.circle(hole, (6, 11, 26, a), (120, 120), i)
            for u in visible:
                p = self.pts[u]
                fog.blit(hole, (p[0] - self.rect.x - 120, p[1] - self.rect.y - 120),
                         special_flags=pygame.BLEND_RGBA_MIN)
            self._fog = fog
        surf.blit(self._fog, self.rect.topleft)
        fx.spaced(surf, "FOG OF WAR", (self.rect.right - 20, self.rect.bottom - 14), 10, T.DIM, "bold", 3,
                  anchor="bottomright")

    def _draw_pulses(self, surf, known_edges, t):
        if self.rng.random() < 0.25 and len(self.pulses) < 26:
            u, v = self.rng.choice(self.edges)
            if self.rng.random() < 0.5:
                u, v = v, u
            self.pulses.append([u, v, 0.0, self.rng.uniform(0.4, 0.9)])
        keep = []
        for p in self.pulses:
            p[2] += p[3] / 60
            if p[2] < 1:
                keep.append(p)
            if known_edges is not None and frozenset((p[0], p[1])) not in known_edges:
                continue
            a, b = self.pts[p[0]], self.pts[p[1]]
            x, y = a[0] + (b[0] - a[0]) * p[2], a[1] + (b[1] - a[1]) * p[2]
            fx.blit_glow(surf, (int(x), int(y)), 7, T.EDGE_LIT, 0.9)
        self.pulses = keep

    def _draw_node(self, surf, g, u, view, t, show_red, show_blue, hl, hover, red_dbg):
        net = self.net
        p = self.pts[u]
        r = self.radius(u)
        kind = net.kind[u]
        held = show_red and u in g.red_held
        isolated = u in g.isolated
        ring = T.NODE_RING
        fill = T.NODE
        if kind == "database":
            ring = T.GOLD
            fx.blit_glow(surf, p, 58, T.GOLD, 0.9 + 0.2 * math.sin(t * 2))
        elif kind == "gateway":
            ring = (210, 220, 240)
        if held:
            ring = T.RED
            fill = (58, 14, 26)
            fx.blit_glow(surf, p, 30, T.RED, 0.7)
        if isolated:
            ring = (110, 120, 140)
            fill = (20, 22, 30)
        pygame.draw.circle(surf, fill, p, r)
        pygame.draw.circle(surf, ring, p, r, 2)
        if kind == "database":
            ang = t * 0.8
            rect = pygame.Rect(0, 0, 2 * r + 16, 2 * r + 16)
            rect.center = p
            for i in range(3):
                a0 = ang + i * 2 * math.pi / 3
                pygame.draw.arc(surf, T.GOLD, rect, a0, a0 + 1.2, 2)
            fx.text(surf, "DB", p, 13, T.GOLD, "black", anchor="center")
        elif kind == "gateway":
            fx.text(surf, "GW", p, 11, (220, 228, 245), "bold", anchor="center")
        else:
            inner = {"bridge": 4, "fileserver": 3, "storage": 3, "server": 3, "workstation": 2}[kind]
            pygame.draw.circle(surf, ring, p, inner)

        # Blue-only markers
        if show_blue:
            if u in g.patched:
                rect = pygame.Rect(0, 0, 2 * r + 8, 2 * r + 8)
                rect.center = p
                pygame.draw.arc(surf, T.CYAN, rect, math.pi * 0.15, math.pi * 0.85, 2)
            if u in g.decoys:
                fx.diamond(surf, T.AMBER, p, r + 7, 2)
                fx.blit_glow(surf, p, 26, T.AMBER, 0.45)
        if isolated:
            fx.hexagon(surf, T.BLUE_SOFT if view != "red" else (150, 160, 180), p, r + 8, 2, rot=t * 0.6)
            fx.text(surf, str(g.isolated[u]), (p[0] + r + 8, p[1] - r - 6), 11, T.BLUE_SOFT, "bold", anchor="center")

        if hl:
            a = 0.5 + 0.5 * math.sin(t * 6)
            pygame.draw.circle(surf, T.mix(T.WHITE, T.RED_SOFT, a), p, r + 5, 2)
        if hover:
            pygame.draw.circle(surf, T.WHITE, p, r + 4, 1)

        # label and (in Red's view) what Red believes the weakness is
        lab_col = T.MUTED if not held else T.RED_SOFT
        if kind not in ("database", "gateway"):
            fx.text(surf, net.label[u], (p[0], p[1] + r + 3), 10, lab_col, "medium", anchor="midtop")
        if view == "red" and u in g.red_intel_weak and u not in g.red_held and kind != "database":
            w = g.red_intel_weak[u]
            fx.text(surf, f"{int(w * 100)}%", (p[0], p[1] - r - 3), 10, T.RED_SOFT, "bold", anchor="midbottom")
