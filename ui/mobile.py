"""Phone layouts ('portrait' and 'landscape', picked by ui/device.py).

The computer layout puts the map between two side panels with a log and a
keyboard legend underneath. A phone has room for the map and one panel, and
no keyboard, so here:

  * the map fills the width (portrait: turned so the three zones stack
    top to bottom),
  * the Red, Blue and Log panels share one tabbed pane you can drag to scroll,
  * a row of buttons along the bottom does everything the keys do
    (MENU = Esc, PLAY / PAUSE, STEP, VIEW, SPEED, SCOUT, UNDO, END TURN, CHAT ...),
  * the menu, result card and online lobby are re-laid out to fit.

Everything here only uses the colour names both themes define, so it works
with the paper and the dark look alike."""

import random

import pygame

from engine import config as C
from ui import device
from ui import overlays as O
from ui.menu_game import MenuGame
from ui.online import _Ink

TOOLS = ["monitor", "patch", "decoy", "isolate", "restore"]
SPEEDS = [0.5, 1, 2, 4]
VIEW_SHORT = {"red": "RED", "full": "FULL", "blue": "BLUE"}
PANEL_H = 720            # height the side panels are drawn at before scrolling


def _k(key):
    return pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0)


# -- geometry ------------------------------------------------------------------------------
def _bar_rows(app, mode):
    if app.layout != "portrait":
        return 1
    if mode == "blue" or (app.state == "result" and app.online and not app.online.closed):
        return 2
    return 1


def match_rects(app, mode=None):
    """Rects for the match screen: top bar, board, pane (tabs + content) and the button bar."""
    W, H = app.size
    mode = mode or app.mode
    rows = _bar_rows(app, mode)
    if app.layout == "portrait":
        top = pygame.Rect(0, 0, W, 44)
        bar_h = rows * 50 + (rows - 1) * 6 + 14
        bar = pygame.Rect(0, H - bar_h, W, bar_h)
        bh = min(round((W - 12) * 1.18), H - top.h - bar_h - 240)
        board = pygame.Rect(6, top.bottom + 6, W - 12, max(260, bh))
        pane = pygame.Rect(6, board.bottom + 6, W - 12, bar.y - board.bottom - 10)
    else:
        top = pygame.Rect(0, 0, W, 40)
        pane_w = max(290, min(400, round(W * 0.34)))
        bar_h = 60
        bar = pygame.Rect(0, H - bar_h, W - pane_w - 6, bar_h)
        board = pygame.Rect(6, top.bottom + 6, W - pane_w - 18, bar.y - top.bottom - 10)
        pane = pygame.Rect(W - pane_w - 6, top.bottom + 6, pane_w, H - top.bottom - 12)
    tabs = pygame.Rect(pane.x, pane.y, pane.w, 36)
    body = pygame.Rect(pane.x, tabs.bottom + 2, pane.w, pane.bottom - tabs.bottom - 2)
    return {"top": top, "board": board, "pane": pane, "tabs": tabs, "body": body, "bar": bar}


def make_board(app, net, mode):
    return app.sk.board.Board(net, match_rects(app, mode)["board"], transpose=app.layout == "portrait")


def make_background(app):
    T = app.sk.T
    W, H = app.size
    bg = pygame.Surface((W, H))
    bg.fill(T.BG)
    if T.NAME == "paper":                       # the same faint print grain as the computer layout
        rng = random.Random(7)
        for _ in range(W * H // 160):
            bg.set_at((rng.randrange(W), rng.randrange(H)), T.mix(T.PAPER, T.INK_3, rng.uniform(0.08, 0.22)))
    return bg


# -- buttons ------------------------------------------------------------------------------
class Btn:
    def __init__(self, id, label, sub=None, accent=None, on=False, enabled=True, hot=False):
        self.id, self.label, self.sub, self.accent = id, label, sub, accent
        self.on, self.enabled, self.hot = on, enabled, hot
        self.rect = None


def bar_buttons(app):
    """Rows of buttons for the bottom bar, for the current state."""
    T = app.sk.T
    o = app.online
    if app.state == "result":
        if o:
            if o.closed:
                return [[Btn("home", "LEAVE")]]
            if o.their_offer is not None:
                offers = [Btn("accept", "ACCEPT", app.rematch_text(o.their_offer).replace("the ", ""), hot=True),
                          Btn("decline", "NO THANKS")]
            else:
                mine = o.my_offer
                offers = [Btn(bid, label, "asked" if mine == opt else None, on=mine == opt)
                          for bid, label, opt in (("rematch", "REMATCH", (False, False)),
                                                  ("newmap", "NEW MAP", (True, False)),
                                                  ("swap", "SWAP SIDES", (False, True)))]
            rest = [Btn("chat", "CHAT"), Btn("home", "LEAVE")]
            return [offers, rest] if app.layout == "portrait" else [offers + rest]
        return [[Btn("replay", "REPLAY"), Btn("new", "NEW MAP"), Btn("home", "MAIN MENU")]]
    think = app.state == "match" and app.phase == "think"
    menu = Btn("menu", "MENU")
    chat = [Btn("chat", "CHAT")] if o else []
    accept = [Btn("accept", "REMATCH?", "accept", hot=True)] if o and not o.closed and o.their_offer else []
    if app.mode == "ai":
        return [[Btn("play", "PLAY" if app.paused else "PAUSE", on=app.paused, accent=T.STRONG),
                 Btn("step", "STEP", enabled=app.paused),
                 Btn("view", "VIEW", VIEW_SHORT[app.view], accent={"red": T.RED, "blue": T.BLUE}.get(app.view)),
                 Btn("speed", "SPEED", f"{app.speed:g}x"), menu]]
    if app.mode == "red":
        can = think and app.pending_red is None
        cut = can and app._red_cut_off()
        return [[Btn("scout", "SCOUT", "and pass" if cut else "nearby", accent=T.RED, enabled=can, hot=cut)]
                + accept + chat + [menu]]
    if app.mode == "blue":
        can = think and app.pending_blue is None
        ap = app._human_blue_ap() if can else 0
        tools = [Btn(t, t.upper(), f"{C.COST[t]} AP", accent=T.BLUE, on=can and t == app.human_tool,
                     enabled=can and C.COST[t] <= ap) for t in TOOLS]
        stuck = can and (ap == 0 or not app._blue_can_do_anything())
        acts = [Btn("undo", "UNDO", enabled=can and bool(app.human_blue_acts)),
                Btn("end", "END TURN", f"{ap} AP left" if can else "wait", accent=T.BLUE, hot=stuck, enabled=can)]
        if app.layout == "portrait":
            return [tools, acts + accept + chat + [menu]]
        return [tools + acts + accept + chat + [menu]]
    return [accept + chat + [menu]]                     # online, your AI plays your side


def layout_bar(app, rows, bar):
    n = len(rows)
    h = (bar.h - 14 - 6 * (n - 1)) // n
    y = bar.y + 8
    for row in rows:
        gap = 6
        w = (bar.w - 12 - gap * (len(row) - 1)) / max(1, len(row))
        for i, b in enumerate(row):
            b.rect = pygame.Rect(round(bar.x + 6 + i * (w + gap)), y, round(w), h)
        y += h + 6
    return [b for row in rows for b in row]


def draw_button(app, s, b):
    T, ink = app.sk.T, _Ink(app.sk)
    r = b.rect
    accent = b.accent or T.STRONG
    filled = b.on or b.hot
    pygame.draw.rect(s, accent if filled else T.PANEL, r)
    pygame.draw.rect(s, accent if (filled or b.enabled) else T.PANEL_EDGE, r, 2 if filled else 1)
    col = T.BG if filled else (T.TEXT if b.enabled else T.DIM)
    size = 14 if r.w >= 84 else 12
    if b.sub:
        ink.text(s, b.label, (r.centerx, r.centery - 7), size, col, "bold", anchor="center")
        ink.text(s, b.sub, (r.centerx, r.centery + 10), 11, col if filled else (T.MUTED if b.enabled else T.DIM),
                 "medium", mono=True, anchor="center")
    else:
        ink.text(s, b.label, r.center, size, col, "bold", anchor="center")


def press(app, bid):
    """What a bottom-bar button does. Mostly the same as the key it stands in for."""
    keys = {"play": pygame.K_SPACE, "step": pygame.K_n, "view": pygame.K_v, "scout": pygame.K_s,
            "undo": pygame.K_BACKSPACE, "end": pygame.K_RETURN, "menu": pygame.K_ESCAPE, "replay": pygame.K_r,
            "new": pygame.K_n, "home": pygame.K_m}
    app.sound.play("click")
    if bid in TOOLS:
        app.human_tool = bid
    elif bid == "speed":
        app.speed_i = (app.speed_i + 1) % len(SPEEDS)
    elif bid == "chat":
        open_chat(app)
    elif bid in ("rematch", "newmap", "swap"):
        app._online_rematch(bid == "newmap", bid == "swap")
    elif bid == "accept":
        app._online_accept()
    elif bid == "decline":
        app._online_decline()
    elif bid in keys:
        app.handle(_k(keys[bid]))


def open_chat(app):
    """Browser: the page's own text box (brings up the phone keyboard). Computer: the in-game chat line."""
    if not app.online:
        return
    if device.WEB:
        msg = device.ask_text(f"Message to {app.online.remote_name}:")
        if msg:
            app._send_chat(msg)
    else:
        app.chat_text = ""


# -- match screen ---------------------------------------------------------------------------
def default_tab(app):
    return {"red": "red", "blue": "blue"}.get(app.mode, "red")


def draw_match(app, s):
    T = app.sk.T
    R = match_rects(app)
    app.sk.panels.SWITCH_HINT = "Tap VIEW to switch"
    _draw_board(app, s)
    _draw_top(app, s, R["top"])
    _draw_pane(app, s, R)
    pygame.draw.rect(s, T.BG, R["bar"])
    pygame.draw.line(s, T.STRONG, R["bar"].topleft, R["bar"].topright, 2)
    app._bar = layout_bar(app, bar_buttons(app), R["bar"])
    for b in app._bar:
        draw_button(app, s, b)
    for e in app.effects:
        if isinstance(e, app.sk.fx.Flash) and app.view in getattr(e, "views", ("red", "full", "blue")):
            e.draw(s)


def _draw_board(app, s):
    m, g = app.match, app.match.game
    hl, hover = (), None
    mouse = pygame.mouse.get_pos()
    monitored = set(g.monitored)
    if app.phase == "reveal" and app.pending_blue:
        monitored |= {t for k, t in app.pending_blue if k == "monitor"}
    if app.mode == "red" and app.phase == "think" and app.pending_red is None:
        hl = set(app._human_red_targets())
    if app.mode == "blue" and app.phase == "think" and app.pending_blue is None:
        monitored |= {t for k, t in app.human_blue_acts if k == "monitor"}
    if app.board.rect.collidepoint(mouse):
        hover = app.board.node_at(mouse, set(hl) if hl else None)
    red_dbg = m.red_debug if app.mode != "red" else {}
    app.board.draw(s, g, app.view, app.t, red_dbg, m.blue_debug, hl, hover, monitored)
    app.sk.screens.draw_pending(app, s)
    for e in app.effects:
        if app.view in getattr(e, "views", ("red", "full", "blue")) and not isinstance(e, app.sk.fx.Flash):
            e.draw(s)
    if app.phase == "think" and not app._ready() and app.online:
        app._draw_online_thinking(s)
    elif app.phase == "think" and not app._ready() and app.worker.is_alive():
        app.sk.screens.draw_thinking(app, s)
    if (app.settings["tooltips"] and app.overlay is None and app.state == "match"
            and app.board.rect.collidepoint(mouse) and getattr(app, "_tapped_board", False)):
        visible = None if app.view != "red" else set(g.red_known) | {m.net.database}
        u = app.board.node_at(mouse, visible)
        if u is not None:
            O.draw_tooltip(app, s, u, mouse)


def _draw_top(app, s, r):
    T, ink = app.sk.T, _Ink(app.sk)
    g, net = app.match.game, app.match.net
    pygame.draw.rect(s, T.BG, r)
    pygame.draw.line(s, T.STRONG, (0, r.bottom - 1), (r.right, r.bottom - 1), 2)
    pygame.draw.rect(s, T.RED, (10, r.centery - 9, 6, 18))
    pygame.draw.rect(s, T.BLUE, (18, r.centery - 9, 6, 18))
    r_now = min(g.round, C.MAX_ROUNDS)
    x = ink.spaced(s, "ROUND", (34, r.centery + 1), 13, T.MUTED, "semibold", 2, anchor="midleft").right
    x = ink.text(s, f"{r_now:02d}", (x + 8, r.centery), 22, T.STRONG, "semibold", mono=True, anchor="midleft").right
    ink.text(s, f"/{C.MAX_ROUNDS}", (x + 2, r.centery + 3), 12, T.DIM, "medium", mono=True, anchor="midleft")
    # rounds played, as a thin rule along the bottom edge
    pygame.draw.line(s, T.RED if g.winner == "red" else T.BLUE, (0, r.bottom - 2),
                     (int(r.w * r_now / C.MAX_ROUNDS), r.bottom - 2), 3)
    o = app.online
    if o:
        who = f"YOU ({o.side.upper()}) VS {o.remote_name.upper()}"
    elif app.mode == "ai":
        who = "AI VS AI" + ("  PAUSED" if app.paused else "")
    else:
        who = f"YOU PLAY {app.mode.upper()}"
    col = {"red": T.RED, "blue": T.BLUE}.get(app.mode if app.mode in ("red", "blue") else "", T.MUTED)
    ink.spaced(s, who[:30], (r.right - 12, r.centery + 1), 13, col, "semibold", 2, anchor="midright")
    if app.layout == "landscape":
        ink.text(s, f"map {net.seed}", (r.centerx, r.centery), 12, T.MUTED, "medium", mono=True, anchor="center")


def _tabs(app):
    T = app.sk.T
    return [("red", "RED", T.RED), ("blue", "BLUE", T.BLUE), ("log", "LOG", T.STRONG)]


def tab_rects(app, R):
    tabs = _tabs(app)
    w = R["tabs"].w / len(tabs)
    return [(k, pygame.Rect(round(R["tabs"].x + i * w), R["tabs"].y, round(w), R["tabs"].h))
            for i, (k, _, _) in enumerate(tabs)]


def _draw_pane(app, s, R):
    T, ink = app.sk.T, _Ink(app.sk)
    body = R["body"]
    for (k, label, col), (_, r) in zip(_tabs(app), tab_rects(app, R)):
        on = k == app.pane_tab
        pygame.draw.rect(s, col if on else T.PANEL, r)
        pygame.draw.rect(s, col, r, 1)
        ink.spaced(s, label, (r.centerx, r.centery + 1), 14, T.BG if on else col, "bold", 2, anchor="center")
    content, h = _pane_content(app, body.w, body.h)
    app.pane_max = max(0, h - body.h)
    app.pane_scroll = max(0, min(app.pane_scroll, app.pane_max))
    pygame.draw.rect(s, T.BG, body)
    s.blit(content, body.topleft, pygame.Rect(0, app.pane_scroll, body.w, body.h))
    pygame.draw.rect(s, T.PANEL_EDGE, body, 1)
    if app.pane_max > 0:                                    # scroll position
        track = body.h - 8
        th = max(24, int(track * body.h / h))
        ty = body.y + 4 + int((track - th) * app.pane_scroll / app.pane_max)
        pygame.draw.rect(s, T.DIM, (body.right - 5, ty, 3, th))


def _pane_content(app, w, vis_h):
    T = app.sk.T
    m, p = app.match, app.sk.panels
    tab = app.pane_tab
    sub = app._panel_subtitles()
    if tab == "log":
        return _log_surface(app, w, vis_h)
    hidden = (tab == "red" and app.view == "blue") or (tab == "blue" and app.view == "red")
    h = vis_h if hidden else max(vis_h, PANEL_H)
    surf = pygame.Surface((w, h))
    surf.fill(T.BG)
    r = pygame.Rect(0, 0, w, h)
    if tab == "red":
        p.draw_red_panel(surf, r, m, app.view, app.mode == "red", app._red_help(), subtitle=sub.get("red"),
                         can_switch=not app.online)
    else:
        p.draw_blue_panel(surf, r, m, app.view, app.mode == "blue", app._blue_help(), subtitle=sub.get("blue"),
                          can_switch=not app.online)
    return surf, h


def _log_surface(app, w, vis_h):
    T, ink = app.sk.T, _Ink(app.sk)
    f = T.font(13, "regular")
    rows = []
    for rnd, col, text in reversed(app._log_lines()[-80:]):
        for i, line in enumerate(O.wrap(f, text.strip(), w - 66)):
            rows.append((rnd if i == 0 else None, col, line, text.startswith("   ")))
    h = max(vis_h, 40 + 19 * len(rows))
    surf = pygame.Surface((w, h))
    surf.fill(T.BG)
    ink.spaced(surf, "MOVE LOG", (14, 12), 13, T.MUTED, "semibold", 2)
    ink.text(surf, "newest first", (w - 14, 13), 11, T.DIM, "regular", mono=True, anchor="topright")
    y = 36
    if not rows:
        ink.text(surf, "Nothing yet.", (14, y), 13, T.DIM, "regular")
    for rnd, col, line, indent in rows:
        if rnd is not None:
            ink.text(surf, f"R{rnd:02d}", (14, y), 12, T.DIM, "regular", mono=True)
        ink.text(surf, line, (54 + (10 if indent else 0), y), 13, col, "regular")
        y += 19
    return surf, h


# -- result card -------------------------------------------------------------------------------
def draw_result(app, s):
    T, ink = app.sk.T, _Ink(app.sk)
    g, m = app.match.game, app.match
    R = match_rects(app)
    k = min(1.0, app.result_t / 0.4)
    veil = pygame.Surface(app.size, pygame.SRCALPHA)
    veil.fill((*T.BG, int(190 * k)))
    s.blit(veil, (0, 0), pygame.Rect(0, 0, app.size[0], R["bar"].y))
    col = T.RED if g.winner == "red" else T.BLUE
    area = R["board"] if app.layout == "portrait" else pygame.Rect(0, R["top"].bottom, app.size[0], R["bar"].y)
    cw = min(area.w - 16, 560)
    f = T.font(15, "regular")
    reason = O.wrap(f, g.reason[:1].upper() + g.reason[1:] + ".", cw - 40)
    o = app.online
    ch = 210 + 20 * len(reason) + (26 if o else 0)
    card = pygame.Rect(0, 0, cw, ch)
    card.center = (area.centerx, area.centery + int(12 * (1 - k)))
    pygame.draw.rect(s, T.PAPER_3, card.move(6, 6))
    pygame.draw.rect(s, T.PANEL, card)
    pygame.draw.rect(s, T.STRONG, card, 2)
    pygame.draw.rect(s, col, (card.x, card.y, card.w, 10))
    x, y = card.x + 20, card.y + 24
    ink.spaced(s, f"ROUND {g.round}  /  MAP {m.net.seed}", (x, y), 13, T.MUTED, "semibold", 2)
    y += 18
    ink.text(s, "RED WINS" if g.winner == "red" else "BLUE WINS", (x - 2, y), 56, col, "bold", display=True)
    y += 70
    if o:
        ink.spaced(s, "YOU WIN" if g.winner == o.side else "YOU LOSE", (x, y), 17, col, "bold", 2)
        y += 26
    for line in reason:
        ink.text(s, line, (x, y), 15, T.TEXT, "regular")
        y += 20
    y += 8
    pygame.draw.line(s, T.STRONG, (x, y), (card.right - 20, y))
    stats = [("Red nodes held", str(len(g.red_held))),
             ("Blue found Red", f"round {m.located_round}" if m.located_round else "never"),
             ("Alerts raised", str(sum(len(r.alerts) for r in g.history)))]
    cw3 = (card.w - 40) // 3
    for i, (lab, val) in enumerate(stats):
        cx = x + i * cw3
        ink.text(s, lab, (cx, y + 10), 11, T.MUTED, "regular")
        ink.text(s, val, (cx, y + 28), 20, T.STRONG, "medium", mono=True)
    if app.mode == "ai" and app.settings["auto_next"] and app.overlay is None:
        left = max(0, int(6.0 - app.result_t + 0.99))
        ink.text(s, f"next map in {left}", (card.centerx, card.bottom + 18), 13, T.MUTED, "medium", mono=True,
                 anchor="center")


# -- menu ----------------------------------------------------------------------------------
def menu_geometry(app):
    W, H = app.size
    n = len(app._menu_items())
    geo = {}
    if app.layout == "portrait":
        item_h, gap = 50, 8
        items_y = H - 36 - n * (item_h + gap)
        geo["items"] = [pygame.Rect(20, items_y + i * (item_h + gap), W - 40, item_h) for i in range(n)]
        seed_row = pygame.Rect(20, items_y - 54, W - 40, 42)
        map_top = 200
        geo["map"] = pygame.Rect(20, map_top, W - 40, seed_row.y - 10 - map_top)
        geo["title"] = (20, 40, min(110, int(W * 0.24)))
        geo["sub_y"] = 40 + min(110, int(W * 0.24)) + 2
    else:
        left_w = int(W * 0.46)
        gap = 6
        item_h = max(34, min(44, (H - 24 - 160) // n - gap))
        items_y = H - 20 - n * (item_h + gap)
        geo["items"] = [pygame.Rect(24, items_y + i * (item_h + gap), left_w - 24, item_h) for i in range(n)]
        seed_row = pygame.Rect(left_w + 20, H - 34 - 44, W - left_w - 44, 40)
        geo["map"] = pygame.Rect(left_w + 20, 20, W - left_w - 44, seed_row.y - 30)
        geo["title"] = (24, 22, 84)
        geo["sub_y"] = 22 + 84
    third = seed_row.w // 4
    geo["prev"] = pygame.Rect(seed_row.x, seed_row.y, third, seed_row.h)
    geo["next"] = pygame.Rect(seed_row.right - third, seed_row.y, third, seed_row.h)
    geo["rand"] = pygame.Rect(seed_row.x + third + 6, seed_row.y, seed_row.w - 2 * third - 12, seed_row.h)
    return geo


def make_menu_board(app, net):
    r = menu_geometry(app)["map"]
    if r.h < 120:
        r = pygame.Rect(-2000, -2000, 400, 300)          # no room for the map: keep it off screen
    b = app.sk.board.Board(net, r, transpose=r.h > r.w * 1.1)
    return b


def draw_menu(app, s):
    T, ink = app.sk.T, _Ink(app.sk)
    W, H = app.size
    geo = menu_geometry(app)
    x, y, size = geo["title"]
    pygame.draw.rect(s, T.RED, (x, y - 18, 10, 22))
    pygame.draw.rect(s, T.BLUE, (x + 12, y - 18, 10, 22))
    ink.spaced(s, "KUET CSE  /  AI LAB", (x + 32, y - 7), 13, T.MUTED, "semibold", 2, anchor="midleft")
    scratch = pygame.Surface((1, 1))
    avail = (W - 2 * x) if app.layout == "portrait" else int(W * 0.46) - x
    while size > 40 and ink.text(scratch, "ZERO DAY", (0, 0), size, T.STRONG, "bold", display=True).w > avail:
        size -= 6                                        # the dark theme's face is wider
    ink.text(s, "ZERO DAY", (x - 3, y + 2), size, T.STRONG, "bold", display=True)
    sy = geo["sub_y"]
    ink.text(s, "An intruder AI and a defender AI on a", (x, sy + 6), 15, T.TEXT, "regular")
    ink.text(s, "network neither of them can fully see.", (x, sy + 26), 15, T.TEXT, "regular")
    if app.layout == "portrait":
        ink.text(s, "Muttakin Rahman Shoscho (2207061)  /  Yasar Wajih (2207064)", (W // 2, H - 16), 11,
                 T.MUTED, "regular", anchor="center")

    b = app.menu_board
    if b.rect.y >= 0:
        b.show_labels = False
        b.draw(s, MenuGame(b.net), "full", app.t)
    for key in ("prev", "rand", "next"):
        r = geo[key]
        pygame.draw.rect(s, T.PANEL, r)
        pygame.draw.rect(s, T.PANEL_EDGE, r, 1)
    ink.text(s, "<", geo["prev"].center, 20, T.STRONG, "bold", mono=True, anchor="center")
    ink.text(s, ">", geo["next"].center, 20, T.STRONG, "bold", mono=True, anchor="center")
    ink.text(s, f"MAP {app.seed}", (geo["rand"].centerx, geo["rand"].centery - 7), 15, T.STRONG, "bold",
             anchor="center")
    ink.text(s, "tap for a random map", (geo["rand"].centerx, geo["rand"].centery + 10), 10, T.MUTED, "medium",
             mono=True, anchor="center")

    for i, ((label, key), r) in enumerate(zip(app._menu_items(), geo["items"])):
        sel = i == app.menu_sel
        col = {"red": T.RED, "blue": T.BLUE}.get(key, T.STRONG)
        pygame.draw.rect(s, col if sel else T.PANEL, r)
        pygame.draw.rect(s, col, r, 2 if sel else 1)
        ink.text(s, f"{i + 1:02d}", (r.x + 14, r.centery), 13, T.BG if sel else T.DIM, "medium", mono=True,
                 anchor="midleft")
        ink.spaced(s, label, (r.x + 50, r.centery + 1), 20, T.BG if sel else col, "bold", 2, anchor="midleft")


# -- online lobby: the computer layout, cut into pieces that fit -----------------------------
def lobby_crops(app):
    lb = app.lobby
    foot = pygame.Rect(100, 850, 680, 40)
    if lb.state != "setup":
        return [pygame.Rect(100, 110, 920, 680), foot]
    if app.layout == "portrait":
        return [pygame.Rect(100, 110, 640, 600), pygame.Rect(850, 250, 650, 420), foot]
    return [pygame.Rect(100, 110, 1400, 600), foot]


def lobby_places(app):
    """[(design rect, screen rect)]: the crops stacked top to bottom, scaled to fit."""
    W, H = app.size
    crops = lobby_crops(app)
    gap = 10
    k = min((W - 24) / max(c.w for c in crops), (H - 24 - gap * (len(crops) - 1)) / sum(c.h for c in crops))
    y = 12
    out = []
    for c in crops:
        dst = pygame.Rect(12, round(y), round(c.w * k), round(c.h * k))
        out.append((c, dst))
        y += c.h * k + gap
    return out


def draw_lobby(app, s):
    d = app.design
    d.blit(app.design_bg, (0, 0))
    app.lobby.draw(d, app.t, app.sk)
    for src, dst in lobby_places(app):
        s.blit(pygame.transform.smoothscale(d.subsurface(src), dst.size), dst)


def lobby_event(app, ev):
    """The same event with its position moved back onto the computer-size lobby (or None if off it)."""
    if not hasattr(ev, "pos"):
        return ev
    for src, dst in lobby_places(app):
        if dst.collidepoint(ev.pos):
            k = src.w / dst.w
            pos = (int(src.x + (ev.pos[0] - dst.x) * k), int(src.y + (ev.pos[1] - dst.y) * k))
            return pygame.event.Event(ev.type, {**ev.dict, "pos": pos})
    return None if ev.type == pygame.MOUSEBUTTONDOWN else ev


# -- input -----------------------------------------------------------------------------------
def handle(app, ev):
    """Phone-layout input that the computer layout does not have. True if the event was used up."""
    if app.state == "menu":
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            geo = menu_geometry(app)
            for key, k in (("prev", pygame.K_LEFT), ("next", pygame.K_RIGHT), ("rand", pygame.K_r)):
                if geo[key].collidepoint(ev.pos):
                    app._handle_menu(_k(k))
                    return True
        return False
    if app.state not in ("match", "result") or app.overlay is not None or app.chat_text is not None:
        return False
    R = match_rects(app)
    if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
        app._tapped_board = R["board"].collidepoint(ev.pos)
        for b in getattr(app, "_bar", []):
            if b.rect and b.rect.collidepoint(ev.pos):
                if b.enabled:
                    press(app, b.id)
                return True
        if R["bar"].collidepoint(ev.pos):
            return True
        for k, r in tab_rects(app, R):
            if r.collidepoint(ev.pos):
                if app.pane_tab != k:
                    app.pane_tab, app.pane_scroll = k, 0
                    app.sound.play("click")
                return True
        if R["pane"].collidepoint(ev.pos):
            app._drag = (ev.pos[1], app.pane_scroll)
            return True
        return app.state == "result"                     # the result card is not a board
    if ev.type == pygame.MOUSEMOTION and getattr(app, "_drag", None):
        y0, s0 = app._drag
        app.pane_scroll = max(0, min(getattr(app, "pane_max", 0), s0 - (ev.pos[1] - y0)))
        return True
    if ev.type == pygame.MOUSEBUTTONUP and getattr(app, "_drag", None):
        app._drag = None
        return True
    if ev.type == pygame.MOUSEWHEEL and R["pane"].collidepoint(pygame.mouse.get_pos()):
        app.pane_scroll = max(0, min(getattr(app, "pane_max", 0), app.pane_scroll - ev.y * 40))
        return True
    return False
