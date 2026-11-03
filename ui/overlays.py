"""Screens and overlays shared by both themes: settings, pause menu, help,
node tooltips and the FPS counter. They only use the token names that both
themes define (BG, PANEL, PANEL_EDGE, TEXT, MUTED, DIM, STRONG, RED, BLUE...)."""

import pygame

from engine import config as C
from ui import settings as S

KIND_NAMES = {"gateway": "Gateway", "database": "Database", "bridge": "Bridge", "server": "Server",
              "workstation": "Workstation", "fileserver": "File server", "storage": "Storage"}


def _veil(app, s, a=200):
    T = app.sk.T
    v = pygame.Surface(s.get_size(), pygame.SRCALPHA)
    v.fill((*T.BG, a))
    s.blit(v, (0, 0))


def _card(app, s, rect, accent=None):
    T = app.sk.T
    pygame.draw.rect(s, T.PANEL, rect, border_radius=0 if T.NAME == "paper" else 14)
    pygame.draw.rect(s, T.STRONG if T.NAME == "paper" else T.PANEL_EDGE, rect, 2 if T.NAME == "paper" else 1,
                     border_radius=0 if T.NAME == "paper" else 14)
    if accent:
        pygame.draw.rect(s, accent, (rect.x, rect.y, rect.w, 6))


# -- settings screen -------------------------------------------------------------
SETTINGS_RECT = pygame.Rect(0, 0, 900, 720)


def settings_rows():
    """Rows the cursor can sit on: every option, then Back."""
    return [row[0] for row in S.OPTIONS] + ["back"]


def settings_row_rects(app):
    r = SETTINGS_RECT.copy()
    r.center = (app.sk.T.W // 2, app.sk.T.H // 2)
    rects, y = {}, r.y + 92
    for row in S.SPEC:
        if row[0] == "section":
            y += 34
            continue
        rects[row[0]] = pygame.Rect(r.x + 40, y, r.w - 80, 30)
        y += 32
    rects["back"] = pygame.Rect(r.x + 40, r.bottom - 64, 160, 36)
    return r, rects


def draw_settings(app, s):
    T, fx = app.sk.T, app.sk.fx
    _veil(app, s, 225)
    card, rects = settings_row_rects(app)
    _card(app, s, card, T.STRONG)
    fx.text(s, "SETTINGS", (card.x + 40, card.y + 30), 34, T.STRONG, "bold")
    fx.text(s, "Up / Down choose    Left / Right change    Esc back (saved)", (card.right - 40, card.y + 44), 13,
            T.MUTED, "medium", mono=True, anchor="topright")
    sel = settings_rows()[app.settings_sel]
    y = card.y + 92
    for row in S.SPEC:
        if row[0] == "section":
            fx.text(s, row[1].upper(), (card.x + 40, y + 10), 13, T.MUTED, "bold")
            pygame.draw.line(s, T.PANEL_EDGE, (card.x + 140, y + 19), (card.right - 40, y + 19))
            y += 34
            continue
        key, label = row[0], row[1]
        r = rects[key]
        active = key == sel
        if active:
            pygame.draw.rect(s, T.STRONG if T.NAME == "paper" else T.PANEL_EDGE, r)
        col = (T.PANEL if T.NAME == "paper" else T.STRONG) if active else T.TEXT
        fx.text(s, label, (r.x + 12, r.centery), 16, col, "semibold" if active else "medium", anchor="midleft")
        val = app.settings.shown(key)
        fx.text(s, "<", (r.right - 230, r.centery), 16, col, "bold", mono=True, anchor="midleft")
        fx.text(s, val, (r.right - 128, r.centery), 16, col, "semibold", mono=True, anchor="center")
        fx.text(s, ">", (r.right - 26, r.centery), 16, col, "bold", mono=True, anchor="midleft")
        y += 32
    b = rects["back"]
    active = sel == "back"
    pygame.draw.rect(s, T.STRONG if active else T.PANEL_EDGE, b, 0 if active else 1)
    fx.text(s, "BACK", b.center, 15, (T.PANEL if T.NAME == "paper" else T.BG) if active else T.TEXT, "bold",
            anchor="center")
    note = next((r[4] for r in S.OPTIONS if r[0] == sel), "Save and go back.")
    fx.text(s, note, (b.right + 24, b.centery), 13, T.MUTED, "regular", anchor="midleft")


def settings_hit(app, pos):
    """Row key and direction (-1, 0, 1) under the mouse, or (None, 0)."""
    _, rects = settings_row_rects(app)
    for key, r in rects.items():
        if r.collidepoint(pos):
            if key == "back":
                return key, 0
            return key, -1 if pos[0] < r.right - 180 and pos[0] > r.right - 240 else 1
    return None, 0


# -- pause menu --------------------------------------------------------------------
PAUSE_ITEMS = [("Resume", "resume"), ("Settings", "settings"), ("Controls", "help"), ("Restart this map", "restart"),
               ("New map", "new"), ("Main menu", "menu")]


def pause_rects(app):
    T = app.sk.T
    card = pygame.Rect(0, 0, 420, 110 + 50 * len(PAUSE_ITEMS))
    card.center = (T.W // 2, T.H // 2)
    return card, [pygame.Rect(card.x + 30, card.y + 84 + i * 50, card.w - 60, 42) for i in range(len(PAUSE_ITEMS))]


def draw_pause(app, s):
    T, fx = app.sk.T, app.sk.fx
    _veil(app, s, 190)
    card, rects = pause_rects(app)
    _card(app, s, card, T.STRONG)
    fx.text(s, "PAUSED", (card.x + 30, card.y + 26), 30, T.STRONG, "bold")
    fx.text(s, f"round {app.match.game.round}  map {app.match.net.seed}", (card.right - 30, card.y + 38), 13,
            T.MUTED, "medium", mono=True, anchor="topright")
    for i, ((label, _), r) in enumerate(zip(PAUSE_ITEMS, rects)):
        active = i == app.pause_sel
        if active:
            pygame.draw.rect(s, T.STRONG if T.NAME == "paper" else T.PANEL_EDGE, r)
        col = (T.PANEL if T.NAME == "paper" else T.STRONG) if active else T.TEXT
        fx.text(s, label, (r.x + 14, r.centery), 18, col, "semibold", anchor="midleft")
    fx.text(s, "Esc resume", (card.centerx, card.bottom - 14), 12, T.MUTED, "medium", mono=True, anchor="midbottom")


# -- help -------------------------------------------------------------------------------
def help_lines(app):
    common = [("Esc", "pause menu"), ("H", "show / hide this help"), ("M", "main menu"), ("R", "restart this map"),
              ("F11", "fullscreen"), ("F12", "screenshot"), ("T", "switch theme")]
    if app.mode == "ai":
        return "AI vs AI", [("Space", "play / pause"), ("N", "step one round"), ("V", "cycle view"),
                            ("1 2 3", "Red / full / Blue view"), ("+ -", "speed 0.5x to 4x")] + common
    if app.mode == "red":
        return "You play Red", [("Click", "a marked neighbour: capture / unlock / advance / claim"),
                                ("S", "scout nearby nodes")] + common
    return "You play Blue", [("Q W E A D", "monitor / patch / decoy / isolate / restore"),
                             ("Click", "a node to use the tool"), ("Backspace", "undo last action"),
                             ("Enter", "end turn")] + common


def draw_help(app, s):
    T, fx = app.sk.T, app.sk.fx
    _veil(app, s, 190)
    title, lines = help_lines(app)
    card = pygame.Rect(0, 0, 640, 120 + 30 * len(lines))
    card.center = (T.W // 2, T.H // 2)
    _card(app, s, card, T.STRONG)
    fx.text(s, "CONTROLS", (card.x + 30, card.y + 26), 30, T.STRONG, "bold")
    fx.text(s, title, (card.right - 30, card.y + 38), 14, T.MUTED, "medium", anchor="topright")
    y = card.y + 84
    for k, d in lines:
        fx.text(s, k, (card.x + 30, y), 14, T.STRONG, "semibold", mono=True)
        fx.text(s, d, (card.x + 190, y), 15, T.TEXT, "regular")
        y += 30
    fx.text(s, "any key to close", (card.centerx, card.bottom - 14), 12, T.MUTED, "medium", mono=True,
            anchor="midbottom")


# -- tooltip ------------------------------------------------------------------------------
def node_info(app, u):
    g, net, view = app.match.game, app.match.net, app.view
    lines = [(net.label[u] if net.kind[u] not in ("gateway", "database") else KIND_NAMES[net.kind[u]], "title"),
             (f"{KIND_NAMES[net.kind[u]]}, {C.ZONE_NAMES[net.zone[u]].title()}", "muted")]
    if view in ("red", "full"):
        if u == g.red_pos and g.winner != "blue":
            lines.append(("Red is here", "red"))
        elif u in g.red_held:
            lines.append(("Held by Red", "red"))
        if view == "red" and u in g.red_intel_weak and u not in g.red_held:
            lines.append((f"Red's guess at weakness: {int(g.red_intel_weak[u] * 100)}%", "red"))
    if view in ("blue", "full"):
        if u in g.patched:
            lines.append(("Patched by Blue", "blue"))
        if u in g.decoys:
            lines.append(("Decoy", "blue"))
        b = (app.match.blue_debug or {}).get("belief")
        if b is not None and b[u] > 0.005:
            lines.append((f"Blue thinks Red is here: {b[u] * 100:.0f}%", "blue"))
    if u in g.isolated:
        lines.append((f"Isolated, {g.isolated[u]} round(s) left", "blue"))
    hops = net.hops_to_db[u]
    if net.kind[u] != "database" and hops != float("inf"):
        lines.append((f"{hops} link(s) from the database", "muted"))
    return lines


def draw_tooltip(app, s, u, pos):
    T, fx = app.sk.T, app.sk.fx
    lines = node_info(app, u)
    col = {"title": T.STRONG, "muted": T.MUTED, "red": T.RED, "blue": T.BLUE}
    f = T.font(13, "medium")
    w = max(f.size(t)[0] for t, _ in lines) + 24
    h = 14 + 20 * len(lines)
    r = pygame.Rect(pos[0] + 18, pos[1] + 18, w, h)
    if r.right > T.W - 8:
        r.right = pos[0] - 12
    if r.bottom > T.H - 8:
        r.bottom = pos[1] - 12
    _card(app, s, r)
    y = r.y + 8
    for t, kind in lines:
        fx.text(s, t, (r.x + 12, y), 14 if kind == "title" else 13, col[kind], "bold" if kind == "title" else "medium")
        y += 20


def draw_fps(app, s):
    T, fx = app.sk.T, app.sk.fx
    fx.text(s, f"{app.clock.get_fps():.0f} fps", (T.W - 10, T.H - 6), 12, T.MUTED, "medium", mono=True,
            anchor="bottomright")
