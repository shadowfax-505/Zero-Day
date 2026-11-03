"""Screens for the 'dark' theme (the original neon look): background, menu,
pending-move markers, thinking line and the result card."""

import math

import pygame

from agents.human import HumanRed, HumanBlue
from ui.neon import fx
from ui.neon import theme as T
from ui.menu_game import MenuGame

MENU_MAP = None


def make_background(app):
    bg = pygame.Surface((T.W, T.H))
    for y in range(T.H):
        k = y / T.H
        pygame.draw.line(bg, T.mix(T.BG2, T.BG, k), (0, y), (T.W, y))
    for x in range(0, T.W, 40):
        pygame.draw.line(bg, T.GRID, (x, 0), (x, T.H))
    for y in range(0, T.H, 40):
        pygame.draw.line(bg, T.GRID, (0, y), (T.W, y))
    vign = pygame.Surface((T.W, T.H), pygame.SRCALPHA)
    for i in range(60):
        a = int(3 * i)
        pygame.draw.rect(vign, (0, 0, 0, min(255, a)), (i * 6 - 360, i * 4 - 240, T.W + 720 - i * 12, T.H + 480 - i * 8),
                         8)
    bg.blit(vign, (0, 0))
    return bg


def draw_menu(app, s):
    b = app.menu_board
    layer = pygame.Surface((T.W, T.H))
    layer.fill((0, 0, 0))
    b.draw(layer, MenuGame(b.net), "full", app.t)
    layer.set_alpha(70)
    s.blit(layer, (0, 0))
    veil = pygame.Surface((T.W, T.H), pygame.SRCALPHA)
    pygame.draw.rect(veil, (5, 9, 22, 170), (T.W // 2 - 420, 150, 840, 660), border_radius=30)
    s.blit(veil, (0, 0))
    fx.blit_glow(s, (T.W // 2 - 120, 270), 220, T.RED, 0.35)
    fx.blit_glow(s, (T.W // 2 + 140, 270), 220, T.BLUE, 0.35)
    fx.spaced(s, "AI LAB FINAL PROJECT  ·  KUET CSE", (T.W // 2, 190), 13, T.MUTED, "semibold", 4, anchor="midtop")
    glitch = int(3 * math.sin(app.t * 13)) if int(app.t * 2) % 7 == 0 else 0
    fx.text(s, "ZERO DAY", (T.W // 2 + glitch + 3, 300), 118, T.scale(T.RED, 0.7), "black", anchor="center")
    fx.text(s, "ZERO DAY", (T.W // 2 - glitch - 3, 300), 118, T.scale(T.BLUE, 0.7), "black", anchor="center")
    fx.text(s, "ZERO DAY", (T.W // 2, 300), 118, T.WHITE, "black", anchor="center")
    fx.text(s, "An intruder AI and a defender AI on a network neither can fully see.", (T.W // 2, 385), 19,
            T.TEXT, "medium", anchor="center")
    fx.text(s, "A* · Information-Set MCTS · opponent model   vs   particle filter · fuzzy logic · minimax + alpha-beta · GA",
            (T.W // 2, 418), 14, T.MUTED, "medium", anchor="center")
    for i, ((label, _), r) in enumerate(zip(app._menu_items(), menu_rects(app))):
        sel = i == app.menu_sel
        key = app._menu_items()[i][1]
        col = {"ai": T.TEXT, "red": T.RED, "blue": T.BLUE}.get(key, T.MUTED)
        if sel:
            fx.blit_glow(s, r.center, 140, col, 0.25)
            pygame.draw.rect(s, T.scale(col, 0.22), r, border_radius=25)
        pygame.draw.rect(s, col if sel else T.PANEL_EDGE, r, 2 if sel else 1, border_radius=25)
        fx.spaced(s, label, r.center, 15, T.WHITE if sel else col, "bold", 4, anchor="center")
    fx.text(s, f"Map seed  ◀  {app.seed}  ▶      R: random map      T: theme", (T.W // 2, 752), 14, T.MUTED, "medium",
            mono=True, anchor="center")
    fx.text(s, "Muttakin Rahman Shoscho (2207061)   ·   Yasar Wajih (2207064)", (T.W // 2, 862), 14, T.DIM,
            "medium", anchor="center")


def menu_rects(app):
    return [pygame.Rect(T.W // 2 - 170, 446 + i * 48, 340, 40) for i in range(len(app._menu_items()))]


def draw_pending(app, s):
    """Blue's chosen actions are shown on the board just before they resolve."""
    acts = []
    if app.phase == "reveal" and app.pending_blue and app.view != "red":
        acts = app.pending_blue
    if app.mode == "blue" and app.phase == "think":
        acts = app.human_blue_acts
    P = app.board.pts
    for k, t in acts:
        if k == "monitor":
            continue
        col = {"patch": T.CYAN, "decoy": T.AMBER, "isolate": T.BLUE_SOFT, "restore": T.BLUE_SOFT}[k]
        p = P[t]
        fx.blit_glow(s, p, 34, col, 0.6)
        pygame.draw.circle(s, col, p, 22, 2)
        fx.text(s, k.upper(), (p[0], p[1] - 26), 10, col, "bold", anchor="midbottom")
    if app.phase == "reveal" and app.pending_red and app.view != "blue":
        a = app.pending_red
        g = app.match.game
        if len(a) > 1 or a[0] == "claim":
            tgt = a[1] if len(a) > 1 else app.match.net.database
            fx.dashed_line(s, T.RED_SOFT, P[g.red_pos], P[tgt], 2, 4, 4, offset=-app.t * 60)


def draw_thinking(app, s):
    r = app.board.rect
    x, y = r.centerx, r.bottom - 6
    names = []
    if app.pending_blue is None and not isinstance(app.match.blue, HumanBlue):
        names.append("Blue")
    if app.pending_red is None and not isinstance(app.match.red, HumanRed):
        names.append("Red")
    if not names:
        return
    dots = "." * (1 + int(app.t * 3) % 3)
    fx.text(s, f"{' and '.join(names)} thinking{dots}", (x, y), 12, T.MUTED, "medium", anchor="midbottom")


def draw_result(app, s):
    g, m = app.match.game, app.match
    k = min(1.0, app.result_t / 0.5)
    veil = pygame.Surface((T.W, T.H), pygame.SRCALPHA)
    veil.fill((3, 6, 16, int(170 * k)))
    s.blit(veil, (0, 0))
    col = T.RED if g.winner == "red" else T.BLUE
    title = "RED WINS" if g.winner == "red" else "BLUE WINS"
    cx, cy = T.W // 2, T.H // 2 - 40
    fx.blit_glow(s, (cx, cy - 40), 300, col, 0.5 * k)
    fx.text(s, title, (cx, cy - 60), 96, T.WHITE, "black", anchor="center", alpha=int(255 * k))
    fx.text(s, g.reason, (cx, cy + 10), 22, T.scale(col, 1.2), "semibold", anchor="center", alpha=int(255 * k))
    stats = [("ROUNDS", str(g.round)),
             ("RED NODES HELD", str(len(g.red_held))),
             ("BLUE FIRST LOCATED RED", f"round {m.located_round}" if m.located_round else "never"),
             ("ALERTS RAISED", str(sum(len(r.alerts) for r in g.history)))]
    x0 = cx - 390
    for i, (lab, val) in enumerate(stats):
        x = x0 + i * 260
        fx.spaced(s, lab, (x, cy + 70), 10, T.MUTED, "bold", 2, anchor="midtop")
        fx.text(s, val, (x, cy + 92), 26, T.WHITE, "bold", anchor="midtop")
    fx.text(s, "R  replay this map      N  new map      M  menu", (cx, cy + 170), 15, T.MUTED, "medium",
            mono=True, anchor="center")
