"""Screens for the default 'paper' theme: background, menu, pending-move
markers, thinking line and the result card."""

import random

import pygame

from agents.human import HumanRed, HumanBlue
from ui import fx
from ui import theme as T
from ui.menu_game import MenuGame

MENU_MAP = pygame.Rect(720, 128, 790, 560)


def make_background(app):
    """Plain paper with a faint print grain."""
    bg = pygame.Surface((T.W, T.H))
    bg.fill(T.PAPER)
    rng = random.Random(7)
    for _ in range(9000):
        x, y = rng.randrange(T.W), rng.randrange(T.H)
        bg.set_at((x, y), T.mix(T.PAPER, T.INK_3, rng.uniform(0.08, 0.22)))
    return bg


def draw_menu(app, s):
    x0 = 110
    # left column: title block
    pygame.draw.rect(s, T.RED, (x0, 128, 14, 34))
    pygame.draw.rect(s, T.BLUE, (x0 + 17, 128, 14, 34))
    fx.spaced(s, "KUET CSE  /  AI LAB FINAL PROJECT", (x0 + 46, 145), 17, T.INK_2, "semibold", 2,
              anchor="midleft")
    fx.text(s, "ZERO DAY", (x0 - 6, 170), 168, T.INK, "bold", display=True)
    fx.text(s, "An intruder AI and a defender AI on a network", (x0, 362), 22, T.INK, "regular")
    fx.text(s, "neither of them can fully see.", (x0, 392), 22, T.INK, "regular")

    y = 446
    for col, side, algos in ((T.RED, "RED  /  INTRUDER", "A* route, Information-Set MCTS, opponent model"),
                             (T.BLUE, "BLUE  /  DEFENDER",
                              "particle filter, fuzzy logic, minimax + alpha-beta, GA tuning")):
        pygame.draw.rect(s, col, (x0, y + 3, 4, 34))
        fx.spaced(s, side, (x0 + 16, y), 15, col, "bold", 2)
        fx.text(s, algos, (x0 + 16, y + 20), 14, T.INK_2, "regular")
        y += 50

    # menu list
    y = 570
    fx.hrule(s, x0, x0 + 520, y - 12, T.INK, 2)
    for i, ((label, _), r) in enumerate(zip(app._menu_items(), menu_rects(app))):
        sel = i == app.menu_sel
        col = {"ai": T.INK, "red": T.RED, "blue": T.BLUE}.get(app._menu_items()[i][1], T.INK_2)
        if sel:
            pygame.draw.rect(s, col, r)
        fx.text(s, f"{i + 1:02d}", (r.x + 14, r.centery), 15, T.PAPER if sel else T.INK_3, "medium", mono=True,
                anchor="midleft")
        fx.spaced(s, label, (r.x + 56, r.centery + 1), 24, T.PAPER if sel else col, "bold", 2, anchor="midleft")
        if sel:
            fx.text(s, "Enter", (r.right - 14, r.centery), 13, T.PAPER, "medium", mono=True, anchor="midright")
        fx.hrule(s, r.x, r.right, r.bottom, T.RULE)

    # right column: the map, printed as a plate with a caption
    b = app.menu_board
    b.draw(s, MenuGame(b.net), "full", app.t)
    pr = b.rect
    fx.spaced(s, f"MAP {app.seed}", (pr.x, pr.bottom + 12), 17, T.INK, "bold", 2)
    fx.text(s, "Left / Right: change map     R: random map", (pr.right, pr.bottom + 14), 13, T.INK_2,
            "regular", mono=True, anchor="topright")
    fx.text(s, "Red starts at GW and is after DB. Blue sees every node but never Red.",
            (pr.x, pr.bottom + 40), 13, T.INK_2, "regular")

    fx.hrule(s, x0, T.W - 60, T.H - 52)
    fx.text(s, "Muttakin Rahman Shoscho (2207061)     Yasar Wajih (2207064)", (x0, T.H - 30), 14, T.INK_2,
            "regular", anchor="midleft")
    fx.text(s, "Up / Down choose   Enter start   T theme   Esc quit", (T.W - 60, T.H - 30), 13, T.INK_3,
            "regular", mono=True, anchor="midright")


def menu_rects(app):
    return [pygame.Rect(110, 566 + i * 44, 520, 40) for i in range(len(app._menu_items()))]


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
        p = P[t]
        fx.dashed_circle(s, T.BLUE, p, 22, 2, 16, rot=app.t * 0.8)
        fx.tag(s, k.upper(), (p[0], p[1] - 32), T.BLUE, 12)
    if app.phase == "reveal" and app.pending_red and app.view != "blue":
        a = app.pending_red
        g = app.match.game
        if len(a) > 1 or a[0] == "claim":
            tgt = a[1] if len(a) > 1 else app.match.net.database
            fx.dashed_line(s, T.RED, P[g.red_pos], P[tgt], 2, 4, 4, offset=-app.t * 40)


def draw_thinking(app, s):
    r = app.board.rect
    names = []
    if app.pending_blue is None and not isinstance(app.match.blue, HumanBlue):
        names.append("Blue")
    if app.pending_red is None and not isinstance(app.match.red, HumanRed):
        names.append("Red")
    if not names:
        return
    dots = "." * (1 + int(app.t * 3) % 3)
    fx.text(s, f"{' and '.join(names)} thinking{dots}", (r.x + 14, r.bottom - 10), 12, T.INK_2, "regular",
            mono=True, anchor="bottomleft")


def draw_result(app, s):
    g, m = app.match.game, app.match
    k = min(1.0, app.result_t / 0.4)
    veil = pygame.Surface((T.W, T.H), pygame.SRCALPHA)
    veil.fill((*T.PAPER, int(200 * k)))
    s.blit(veil, (0, 0))
    col = T.RED if g.winner == "red" else T.BLUE
    title = "RED WINS" if g.winner == "red" else "BLUE WINS"
    card = pygame.Rect(0, 0, 820, 400)
    card.center = (T.W // 2, T.H // 2 - 30 + int(16 * (1 - k)))
    shadow = card.move(8, 8)
    pygame.draw.rect(s, T.PAPER_3, shadow)
    pygame.draw.rect(s, T.PAPER, card)
    pygame.draw.rect(s, T.INK, card, 2)
    pygame.draw.rect(s, col, (card.x, card.y, card.w, 14))
    x = card.x + 48
    fx.spaced(s, f"ROUND {g.round}  /  MAP {m.net.seed}", (x, card.y + 40), 16, T.INK_2, "semibold", 2)
    fx.text(s, title, (x - 4, card.y + 58), 112, col, "bold", display=True)
    fx.text(s, g.reason[:1].upper() + g.reason[1:] + ".", (x, card.y + 190), 22, T.INK, "regular")
    stats = [("Rounds", str(g.round)),
             ("Red nodes held", str(len(g.red_held))),
             ("Blue first located Red", f"round {m.located_round}" if m.located_round else "never"),
             ("Alerts raised", str(sum(len(r.alerts) for r in g.history)))]
    y = card.y + 246
    fx.hrule(s, x, card.right - 48, y, T.INK)
    cw = (card.w - 96) // 4
    for i, (lab, val) in enumerate(stats):
        cx = x + i * cw
        if i:
            pygame.draw.line(s, T.RULE, (cx - 12, y + 12), (cx - 12, y + 70))
        fx.text(s, lab, (cx, y + 14), 12, T.INK_2, "regular")
        fx.text(s, val, (cx, y + 34), 28, T.INK, "medium", mono=True)
    fx.hrule(s, x, card.right - 48, y + 84)
    fx.text(s, "R  replay this map      N  new map      M  menu", (x, card.bottom - 30), 14, T.INK_2, "regular",
            mono=True, anchor="midleft")
