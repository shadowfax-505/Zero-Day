"""Screens for the 'dark' theme (the original neon look): background, menu,
pending-move markers, thinking line and the result card."""

import math

import pygame

from agents.human import HumanRed, HumanBlue
from ui.neon import fx
from ui.neon import theme as T
from ui.menu_game import MenuGame
from ui import hidpi

MENU_MAP = pygame.Rect(720, 128, 790, 560)    # the map preview on the menu


def make_background(app):
    bg = hidpi.Surface((T.W, T.H))
    for y in range(T.H):
        k = y / T.H
        hidpi.line(bg, T.mix(T.BG2, T.BG, k), (0, y), (T.W, y))
    for x in range(0, T.W, 40):
        hidpi.line(bg, T.GRID, (x, 0), (x, T.H))
    for y in range(0, T.H, 40):
        hidpi.line(bg, T.GRID, (0, y), (T.W, y))
    vign = hidpi.Surface((T.W, T.H), pygame.SRCALPHA)
    for i in range(60):
        a = int(3 * i)
        hidpi.rect(vign, (0, 0, 0, min(255, a)), (i * 6 - 360, i * 4 - 240, T.W + 720 - i * 12, T.H + 480 - i * 8),
                         8)
    bg.blit(vign, (0, 0))
    return bg


def draw_menu(app, s):
    """Title and menu on the left, the chosen map on the right (as in the paper theme)."""
    x0 = 110
    fx.blit_glow(s, (x0 + 150, 250), 220, T.RED, 0.3)
    fx.blit_glow(s, (x0 + 400, 250), 220, T.BLUE, 0.3)
    fx.spaced(s, "AI LAB FINAL PROJECT  ·  KUET CSE", (x0 + 2, 140), 13, T.MUTED, "semibold", 4)
    glitch = int(3 * math.sin(app.t * 13)) if int(app.t * 2) % 7 == 0 else 0
    fx.text(s, "ZERO DAY", (x0 + glitch + 3, 168), 118, T.scale(T.RED, 0.7), "black")
    fx.text(s, "ZERO DAY", (x0 - glitch - 3, 168), 118, T.scale(T.BLUE, 0.7), "black")
    fx.text(s, "ZERO DAY", (x0, 168), 118, T.WHITE, "black")
    fx.text(s, "An intruder AI and a defender AI on a network", (x0, 330), 19, T.TEXT, "medium")
    fx.text(s, "neither of them can fully see.", (x0, 356), 19, T.TEXT, "medium")
    for i, (col, side, algos) in enumerate(((T.RED, "RED", "A* · Information-Set MCTS · opponent model"),
                                            (T.BLUE, "BLUE", "particle filter · fuzzy logic · minimax + alpha-beta · GA"))):
        y = 398 + i * 24
        fx.spaced(s, side, (x0, y + 2), 11, col, "bold", 3)
        fx.text(s, algos, (x0 + 52, y), 14, T.MUTED, "medium")
    for i, ((label, _), r) in enumerate(zip(app._menu_items(), menu_rects(app))):
        sel = i == app.menu_sel
        key = app._menu_items()[i][1]
        col = {"ai": T.TEXT, "red": T.RED, "blue": T.BLUE}.get(key, T.MUTED)
        if sel:
            fx.blit_glow(s, r.center, 140, col, 0.25)
            hidpi.rect(s, T.scale(col, 0.22), r, border_radius=25)
        hidpi.rect(s, col if sel else T.PANEL_EDGE, r, 2 if sel else 1, border_radius=25)
        fx.spaced(s, label, r.center, 15, T.WHITE if sel else col, "bold", 4, anchor="center")

    # right: the chosen map in a panel, with its seed underneath
    b = app.menu_board
    fx.rounded_panel(s, b.rect.inflate(24, 24), radius=18, alpha=200)
    b.draw(s, MenuGame(b.net), "full", app.t)
    pr = b.rect.inflate(24, 24)
    fx.spaced(s, f"MAP {app.seed}", (pr.x + 4, pr.bottom + 16), 15, T.WHITE, "bold", 3)
    fx.text(s, "◀ ▶  change map      R  random map", (pr.right - 4, pr.bottom + 16), 14, T.MUTED, "medium",
            mono=True, anchor="topright")
    fx.text(s, "Red starts at GW and is after DB. Blue sees every node but never Red.", (pr.x + 4, pr.bottom + 44),
            14, T.DIM, "medium")

    fx.text(s, "Muttakin Rahman Shoscho (2207061)   ·   Yasar Wajih (2207064)", (x0, 862), 14, T.DIM, "medium",
            anchor="midleft")
    fx.text(s, "Up / Down choose   Enter start   T theme   Esc quit", (T.W - 90, 862), 13, T.DIM, "medium",
            mono=True, anchor="midright")


def menu_rects(app):
    return [pygame.Rect(110, 470 + i * 48, 460, 40) for i in range(len(app._menu_items()))]


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
        hidpi.circle(s, col, p, 22, 2)
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
    veil = hidpi.Surface((T.W, T.H), pygame.SRCALPHA)
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
    fx.text(s, ("R  rematch      N  new map      S  swap sides" if app.online else "R  replay this map      N  new map      M  menu"), (cx, cy + 170), 15, T.MUTED, "medium",
            mono=True, anchor="center")
