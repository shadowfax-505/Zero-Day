"""Network renderer: zones, links, nodes, Red's route, Blue's belief map and
per-view fog of war. Drawn like a printed map: ink shapes on paper, one shape
per node type, hatching for what Red has not seen."""

import math

import pygame

from engine import config as C
from engine.mapgen import ZONE_X
from ui import fx
from ui import theme as T

VIEWS = ["red", "full", "blue"]
VIEW_NAMES = {"red": "RED'S VIEW", "full": "FULL VIEW", "blue": "BLUE'S VIEW"}

FOG_R = 64


class Board:
    def __init__(self, net, rect=T.BOARD):
        self.net = net
        self.rect = rect
        pad_x, pad_y = 30, 46
        self.inner = rect.inflate(-2 * pad_x, -2 * pad_y)
        self.inner.y += 10
        self.pts = [self.to_screen(p) for p in net.pos]
        self.zone_rects = []
        for z, (x0, x1) in enumerate(ZONE_X):
            a = self.to_screen((x0 - 0.035, 0.02))
            b = self.to_screen((x1 + 0.035, 0.98))
            self.zone_rects.append(pygame.Rect(a[0], a[1] - 18, b[0] - a[0], b[1] - a[1] + 18))
        self.edges = list(net.edges())
        self._fog_key = None

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
        return 17 if k == "database" else 14 if k == "gateway" else 10 if k == "bridge" else 8

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

        self._draw_plate(surf)
        self._draw_zones(surf, view, monitored_preview)

        # Blue's belief: flat discs sized and shaded by probability, particles as dots
        if show_blue and blue_dbg.get("belief") is not None:
            self._draw_belief(surf, blue_dbg, t)

        # links
        for u, v in self.edges:
            e = frozenset((u, v))
            if known_edges is not None and e not in known_edges:
                continue
            a, b = self.pts[u], self.pts[v]
            gate = e in net.gates
            opened = e in g.open_gates
            held_both = show_red and u in g.red_held and v in g.red_held
            if held_both or (gate and opened and show_red):
                pygame.draw.line(surf, T.RED, a, b, 3)
            elif gate:
                fx.dashed_line(surf, T.INK_2, a, b, 2, 7, 5)
            else:
                pygame.draw.line(surf, T.EDGE, a, b, 1)
            if gate:
                m = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
                col = T.RED if opened and show_red else T.INK
                r = pygame.Rect(0, 0, 11, 11)
                r.center = m
                pygame.draw.rect(surf, T.PAPER, r)
                pygame.draw.rect(surf, col, r, 2)
                if not (opened and show_red):
                    pygame.draw.rect(surf, col, r.inflate(-6, -6))

        if view == "red":
            self._draw_fog(surf, visible)

        # Red's planned route
        if show_red and red_dbg.get("route"):
            route = red_dbg["route"]
            for i in range(len(route) - 1):
                fx.dashed_line(surf, T.RED, self.pts[route[i]], self.pts[route[i + 1]], 3, 9, 6, offset=-t * 30)
            if not red_dbg.get("reaches_db") and route:
                fx.dashed_line(surf, T.fade(T.RED, 0.45), self.pts[route[-1]], self.pts[net.database], 1, 2, 6,
                               offset=-t * 20)

        # nodes
        for u in range(net.n):
            if u not in visible:
                continue
            self._draw_node(surf, g, u, view, t, show_red, show_blue, u in highlight, u == hover)

        # last round's alerts (Blue sees these, never whether they are real)
        if show_blue and g.history:
            for u, strength, real in g.history[-1].alerts:
                p = self.pts[u]
                r = self.radius(u)
                c = (p[0] + r + 5, p[1] - r - 5)
                col = T.ALERT if (real or view == "blue") else T.INK_3
                pygame.draw.circle(surf, T.PAPER, c, 9)
                pygame.draw.circle(surf, col, c, 8)
                fx.text(surf, "!", (c[0] + 1, c[1]), 13, T.PAPER, "bold", anchor="center")

        # Red's marker: a pin above its node
        if show_red and g.winner != "blue":
            p = self.pts[g.red_pos]
            r = self.radius(g.red_pos)
            pygame.draw.circle(surf, T.RED, p, r + 6, 2)
            bob = 2 * math.sin(t * 3)
            x, y = p[0], p[1] - r - 12 + bob
            pygame.draw.polygon(surf, T.RED, [(x - 8, y - 12), (x + 8, y - 12), (x, y)])
            pygame.draw.polygon(surf, T.PAPER, [(x - 8, y - 12), (x + 8, y - 12), (x, y)], 1)

    def _draw_plate(self, surf):
        """The map sheet: faint grid with a frame and corner ticks."""
        if getattr(self, "_plate", None) is None:
            r = self.rect
            plate = pygame.Surface(r.size)
            plate.fill(T.PAPER)
            for x in range(0, r.w, 32):
                pygame.draw.line(plate, T.GRID, (x, 0), (x, r.h))
            for y in range(0, r.h, 32):
                pygame.draw.line(plate, T.GRID, (0, y), (r.w, y))
            pygame.draw.rect(plate, T.INK_3, plate.get_rect(), 1)
            for cx, cy, dx, dy in ((0, 0, 1, 1), (r.w - 1, 0, -1, 1), (0, r.h - 1, 1, -1), (r.w - 1, r.h - 1, -1, -1)):
                pygame.draw.line(plate, T.INK, (cx, cy), (cx + 14 * dx, cy), 2)
                pygame.draw.line(plate, T.INK, (cx, cy), (cx, cy + 14 * dy), 2)
            self._plate = plate
        surf.blit(self._plate, self.rect.topleft)

    def _zone_fill(self, u, view):
        """Colour under a node's label, so labels sit on a clean patch over the links."""
        if view != "red" and self.net.zone[u] in self._watched:
            return T.mix(T.PAPER_2, T.BLUE, 22 / 255)
        return T.PAPER_2

    def _draw_zones(self, surf, view, monitored_preview):
        mon = set(monitored_preview) if view != "red" else set()
        self._watched = mon
        for z, r in enumerate(self.zone_rects):
            watched = z in mon
            if watched:
                s = pygame.Surface(r.size, pygame.SRCALPHA)
                s.fill((*T.BLUE, 22))
                surf.blit(s, r.topleft)
                pygame.draw.rect(surf, T.BLUE, r, 2)
            else:
                pygame.draw.rect(surf, T.PAPER_2, r)
                pygame.draw.rect(surf, T.RULE, r, 1)
            fx.text(surf, f"{z + 1:02d}", (r.x + 12, r.y + 7), 15, T.INK_3, "semibold", display=True)
            fx.spaced(surf, C.ZONE_NAMES[z], (r.x + 36, r.y + 7), 15, T.INK_2, "semibold", 2)
            if watched:
                fx.spaced(surf, "MONITORED", (r.right - 12, r.y + 7), 15, T.BLUE, "bold", 2, anchor="topright")

    def _draw_belief(self, surf, blue_dbg, t):
        b = blue_dbg["belief"]
        ox, oy = self.rect.topleft
        layer = pygame.Surface(self.rect.size, pygame.SRCALPHA)
        for u in range(self.net.n):
            if b[u] > 0.01:
                k = min(1.0, b[u] * 1.8)
                p = self.pts[u]
                pygame.draw.circle(layer, (*T.BLUE, int(36 + 80 * k)), (p[0] - ox, p[1] - oy), int(16 + 30 * k))
        surf.blit(layer, (ox, oy))
        parts = blue_dbg.get("particles")
        if parts is not None:
            n = min(240, len(parts))
            for i in range(n):
                u = int(parts[i])
                a = (i * 2.399963) % (2 * math.pi)          # golden-angle spread around the node
                rad = 6 + 18 * math.sqrt((i % 37) / 37)
                p = self.pts[u]
                surf.fill(T.BLUE_DARK, (int(p[0] + math.cos(a) * rad), int(p[1] + math.sin(a) * rad), 2, 2))

    def _draw_fog(self, surf, visible):
        """Hatched fog over everything Red has not seen, with clean cut-outs."""
        key = frozenset(visible)
        if self._fog_key != key:
            self._fog_key = key
            fog = pygame.Surface(self.rect.size, pygame.SRCALPHA)
            fog.fill((*T.PAPER_3, 250))
            fx.hatch(fog, fog.get_rect(), (*T.RULE, 255), 9, 1)
            ox, oy = self.rect.topleft
            for u in visible:
                p = self.pts[u]
                pygame.draw.circle(fog, (*T.INK_3, 255), (p[0] - ox, p[1] - oy), FOG_R + 2)
            for u in visible:
                p = self.pts[u]
                pygame.draw.circle(fog, (0, 0, 0, 0), (p[0] - ox, p[1] - oy), FOG_R)
            self._fog = fog
        surf.blit(self._fog, self.rect.topleft)
        fx.tag(surf, "UNEXPLORED", (self.rect.right - 60, self.rect.bottom - 18), T.INK_2, 13)

    def _draw_node(self, surf, g, u, view, t, show_red, show_blue, hl, hover):
        net = self.net
        p = self.pts[u]
        x, y = p
        r = self.radius(u)
        kind = net.kind[u]
        held = show_red and u in g.red_held
        isolated = u in g.isolated
        ink = T.INK
        fill = T.PAPER
        if held:
            ink, fill = T.RED_DARK, T.RED
        if isolated:
            ink = T.BLUE

        # decoy: dashed blue ring (Blue knows; Red does not)
        if show_blue and u in g.decoys:
            fx.dashed_circle(surf, T.BLUE, p, r + 9, 2, 16, rot=t * 0.4)

        if kind == "database":
            box = pygame.Rect(0, 0, 2 * r, 2 * r)
            box.center = p
            pygame.draw.rect(surf, T.PAPER, box.inflate(10, 10))
            pygame.draw.rect(surf, T.OCHRE, box.inflate(10, 10), 1)
            pygame.draw.rect(surf, T.OCHRE if not held else T.RED, box)
            fx.text(surf, "DB", (x, y + 1), 17, T.PAPER, "bold", display=True, anchor="center")
        elif kind == "gateway":
            box = pygame.Rect(0, 0, 2 * r, 2 * r)
            box.center = p
            pygame.draw.rect(surf, T.RED if held else T.INK, box)
            fx.text(surf, "GW", (x, y + 1), 15, T.PAPER, "bold", display=True, anchor="center")
        elif kind == "workstation":
            pygame.draw.circle(surf, fill, p, r)
            pygame.draw.circle(surf, ink, p, r, 2)
        elif kind == "bridge":
            pygame.draw.circle(surf, fill, p, r)
            pygame.draw.circle(surf, ink, p, r, 2)
            pygame.draw.circle(surf, ink if not held else T.PAPER, p, 3)
        else:  # server, fileserver, storage: squares
            box = pygame.Rect(0, 0, 2 * r, 2 * r)
            box.center = p
            pygame.draw.rect(surf, fill, box)
            pygame.draw.rect(surf, ink, box, 2)
            mark = ink if not held else T.PAPER
            if kind == "storage":
                pygame.draw.line(surf, mark, (x - r + 3, y), (x + r - 3, y), 2)
            elif kind == "fileserver":
                pygame.draw.line(surf, mark, (x - r + 3, y - 2), (x + r - 3, y - 2), 1)
                pygame.draw.line(surf, mark, (x - r + 3, y + 2), (x + r - 3, y + 2), 1)

        # patched: a small blue bar under the node
        if show_blue and u in g.patched:
            pygame.draw.line(surf, T.BLUE, (x - r, y + r + 4), (x + r, y + r + 4), 3)

        # isolated: blue square bracket and a strike, with rounds left
        if isolated:
            col = T.BLUE if view != "red" else T.INK_2
            box = pygame.Rect(0, 0, 2 * r + 14, 2 * r + 14)
            box.center = p
            pygame.draw.rect(surf, col, box, 2)
            pygame.draw.line(surf, col, box.bottomleft, box.topright, 2)
            badge = pygame.Rect(0, 0, 15, 15)
            badge.center = box.topright
            pygame.draw.rect(surf, col, badge)
            fx.text(surf, str(g.isolated[u]), badge.center, 11, T.PAPER, "semibold", mono=True, anchor="center")

        if hl:
            a = 0.5 + 0.5 * math.sin(t * 5)
            fx.dashed_circle(surf, T.mix(T.RED, T.INK, a * 0.4), p, r + 8, 2, 14, rot=t)
        if hover:
            pygame.draw.circle(surf, T.INK, p, r + 11, 1)

        # label and (in Red's view) what Red believes the weakness is
        if kind not in ("database", "gateway") and getattr(self, "show_labels", True):
            lab_col = T.RED_DARK if held else T.INK_2
            fx.text(surf, net.label[u], (x, y + r + 6), 11, lab_col, "medium", mono=True, anchor="midtop",
                    bg=self._zone_fill(u, view))
        if view == "red" and u in g.red_intel_weak and u not in g.red_held and kind != "database":
            w = g.red_intel_weak[u]
            fx.text(surf, f"{int(w * 100)}%", (x, y - r - 4), 11, T.RED, "semibold", mono=True, anchor="midbottom",
                    bg=T.PAPER_2)
