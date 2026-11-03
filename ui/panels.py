"""Top bar, the two AI panels and the bottom log/controls strip. Laid out like
a printed briefing sheet: hairline rules, condensed headings, mono numbers."""

import math

import pygame

from engine import config as C
from ui import fx
from ui import theme as T
from ui.board import VIEW_NAMES

ACTION_WORD = {"scout": "Scout", "capture": "Capture", "unlock": "Unlock", "advance": "Advance", "claim": "Claim",
               "monitor": "Monitor", "patch": "Patch", "decoy": "Decoy", "isolate": "Isolate", "restore": "Restore"}


def act_text(net, act):
    if not act:
        return "-"
    k = act[0]
    if k == "scout":
        return "Scout nearby"
    if k == "claim":
        return "Claim the database"
    return f"{ACTION_WORD[k]} {net.label[act[1]]}"


def blue_act_text(net, a):
    k, t = a
    if k == "monitor":
        return f"Monitor {C.ZONE_NAMES[t].title()}"
    return f"{ACTION_WORD[k]} {net.label[t]}"


# -- top bar --------------------------------------------------------------------
VIEW_ORDER = ("red", "full", "blue")
VIEW_LABEL = {"red": "RED", "full": "FULL", "blue": "BLUE"}


def view_rects():
    """Screen rects of the RED / FULL / BLUE buttons in the top bar."""
    seg_w = 64
    x0 = T.W - 24 - seg_w * 3
    return {v: pygame.Rect(x0 + i * seg_w, 17, seg_w, 30) for i, v in enumerate(VIEW_ORDER)}


def draw_top(surf, match, view, speed, paused, mode_label, t):
    g, net = match.game, match.net
    pygame.draw.rect(surf, T.PAPER, (0, 0, T.W, T.TOP_H))
    pygame.draw.line(surf, T.INK, (0, T.TOP_H - 1), (T.W, T.TOP_H - 1), 2)

    # masthead
    pygame.draw.rect(surf, T.RED, (24, 20, 8, 24))
    pygame.draw.rect(surf, T.BLUE, (34, 20, 8, 24))
    fx.text(surf, "ZERO DAY", (52, 32), 34, T.INK, "bold", display=True, anchor="midleft")
    pygame.draw.line(surf, T.RULE, (170, 18), (170, 46))
    fx.spaced(surf, mode_label, (184, 32), 15, T.INK_2, "semibold", 2, anchor="midleft")

    # round counter with a ruler of 40 ticks
    cx = T.W // 2 - 150
    fx.spaced(surf, "ROUND", (cx, 32), 15, T.INK_2, "semibold", 2, anchor="midleft")
    r_now = min(g.round, C.MAX_ROUNDS)
    fx.text(surf, f"{r_now:02d}", (cx + 62, 33), 30, T.INK, "semibold", mono=True, anchor="midleft")
    fx.text(surf, f"/{C.MAX_ROUNDS}", (cx + 102, 37), 14, T.INK_3, "medium", mono=True, anchor="midleft")
    x0 = cx + 150
    for i in range(C.MAX_ROUNDS):
        x = x0 + i * 6
        done = i < r_now
        h = 14 if (i + 1) % 10 == 0 else 9
        pygame.draw.line(surf, T.INK if done else T.RULE, (x, 40 - h), (x, 40), 2)

    # view switch: one segmented control (clickable in AI vs AI, see view_rects)
    rects = view_rects()
    box = rects["red"].union(rects["blue"])
    for i, v in enumerate(VIEW_ORDER):
        r = rects[v]
        active = v == view
        col = {"red": T.RED, "blue": T.BLUE, "full": T.INK}[v]
        if active:
            pygame.draw.rect(surf, col, r)
        fx.spaced(surf, VIEW_LABEL[v], r.center, 15, T.PAPER if active else T.INK_2, "semibold", 2, anchor="center")
        if i:
            pygame.draw.line(surf, T.INK, (r.x, r.y), (r.x, r.bottom - 1))
    pygame.draw.rect(surf, T.INK, box, 1)
    fx.spaced(surf, "VIEW", (box.x - 10, 32), 15, T.INK_3, "semibold", 2, anchor="midright")
    state = "paused" if paused else f"{speed:g}x"
    fx.text(surf, f"map {net.seed}   {state}", (box.x - 70, 33), 13, T.INK_2, "medium", mono=True,
            anchor="midright")


# -- side panels ------------------------------------------------------------------
def _frame(surf, rect, color, title, sub):
    pygame.draw.rect(surf, T.PAPER, rect)
    pygame.draw.rect(surf, color, (rect.x, rect.y, rect.w, 5))
    fx.text(surf, title, (rect.x + 20, rect.y + 16), 26, color, "bold", display=True)
    fx.text(surf, sub, (rect.x + 20, rect.y + 48), 12, T.INK_2, "regular")


def _section(surf, x, y, w, title, note=None):
    fx.hrule(surf, x, x + w, y)
    fx.label(surf, title, (x, y + 7))
    if note:
        fx.text(surf, note, (x + w, y + 9), 11, T.INK_3, "regular", mono=True, anchor="topright")
    return y + 30


def _row(surf, x, y, label, value, vcol=T.TEXT, w=300):
    fx.text(surf, label, (x, y), 13, T.INK_2, "regular")
    fx.text(surf, value, (x + w, y), 13, vcol, "semibold", anchor="topright")


def _hidden(surf, rect, color, who, can_switch=True):
    box = pygame.Rect(rect.x + 20, rect.y + 80, rect.w - 40, rect.h - 100)
    fx.hatch(surf, box, T.PAPER_3, 9, 1)
    pygame.draw.rect(surf, T.RULE, box, 1)
    fx.tag(surf, f"NOT VISIBLE IN {who.upper()}'S VIEW", (box.centerx, box.centery - 12), color, 15)
    fx.text(surf, "Press V to switch view" if can_switch else "Hidden by the fog of war",
            (box.centerx, box.centery + 16), 12, T.INK_2, "regular", anchor="center")


def draw_red_panel(surf, rect, match, view, human=False, human_help=None, subtitle=None, can_switch=True):
    g, net, d = match.game, match.net, match.red_debug
    _frame(surf, rect, T.RED, "RED  /  INTRUDER",
           subtitle or ("A* route, IS-MCTS, opponent model" if not human else "You are playing Red"))
    if view == "blue":
        _hidden(surf, rect, T.RED, "Blue", can_switch)
        return
    x, w = rect.x + 20, rect.w - 40
    y = rect.y + 76
    hops = net.hops_to_db[g.red_pos]
    _row(surf, x, y, "Position", f"{net.label[g.red_pos]}  {C.ZONE_NAMES[net.zone[g.red_pos]].title()}", T.RED, w)
    y += 20
    _row(surf, x, y, "Nodes held", str(len(g.red_held)), T.INK, w)
    y += 20
    _row(surf, x, y, "Links to database", str(hops) if hops != math.inf else "-", T.OCHRE, w)
    y += 28

    if human:
        y = _section(surf, x, y, w, "Your moves")
        for line in human_help or []:
            fx.text(surf, line, (x, y), 12, T.INK, "regular")
            y += 19
        return

    y = _section(surf, x, y, w, "Next move")
    fx.text(surf, act_text(net, d.get("next")), (x, y - 4), 22, T.INK, "semibold")
    y += 26
    astar = d.get("astar_next")
    if astar and d.get("next") and tuple(astar) != tuple(d["next"]):
        fx.text(surf, f"MCTS overrode A* ({act_text(net, astar)})", (x, y), 12, T.ALERT, "medium")
    else:
        fx.text(surf, "A* and MCTS agree", (x, y), 12, T.INK_3, "regular")
    y += 22
    risk = d.get("risk", 0.0)
    fx.text(surf, "Detection risk", (x, y), 12, T.INK_2, "regular")
    fx.text(surf, f"{int(risk * 100)}%", (x + w, y), 12, T.INK, "medium", mono=True, anchor="topright")
    y += 19
    fx.bar(surf, pygame.Rect(x, y, w, 4), risk, T.RED)
    y += 18

    y = _section(surf, x, y, w, "Monte Carlo search", f"{d.get('iterations', 0)} sims  {d.get('think_ms', 0)} ms")
    stats = d.get("mcts") or []
    total = sum(n for _, n, _ in stats) or 1
    for a, n, q in stats[:4]:
        chosen = d.get("next") and tuple(a) == tuple(d["next"])
        fx.text(surf, act_text(net, a), (x, y), 12, T.INK if chosen else T.INK_2, "semibold" if chosen else "regular")
        fx.text(surf, f"{q:.2f}", (x + w, y), 11, T.INK_2, "regular", mono=True, anchor="topright")
        y += 17
        fx.bar(surf, pygame.Rect(x, y, w, 3), n / total, T.RED if chosen else T.fade(T.RED, 0.55))
        y += 10
    if not stats:
        fx.text(surf, "-", (x, y), 12, T.INK_3)
        y += 18
    y += 6

    y = _section(surf, x, y, w, "Opponent model", "P(zone watched)")
    m = d.get("model", {})
    pm = m.get("p_monitor", [0, 0, 0])
    bw = (w - 20) // 3
    for z in range(3):
        bx = x + z * (bw + 10)
        fx.text(surf, C.ZONE_NAMES[z].title(), (bx, y), 11, T.INK_2, "regular")
        fx.text(surf, f"{int(pm[z] * 100)}%", (bx + bw, y), 11, T.INK, "medium", mono=True, anchor="topright")
        fx.bar(surf, pygame.Rect(bx, y + 18, bw, 3), pm[z], T.BLUE)
    y += 30
    fx.text(surf, f"caught {m.get('caught', 0)}   decoys hit {m.get('decoys_found', 0)}", (x, y), 11, T.INK_3,
            "regular", mono=True)
    y += 26

    route = d.get("route") or []
    if route:
        y = _section(surf, x, y, w, "A* route")
        cx = x
        steps = [net.label[u] for u in route] + ([] if d.get("reaches_db") else ["?", "DB"])
        f = T.font(11, "medium", mono=True)
        for i, lab in enumerate(steps):
            wlab = f.size(lab)[0] + 12
            if cx + wlab + 14 > x + w:
                cx = x
                y += 24
            r = pygame.Rect(cx, y, wlab, 19)
            col = T.OCHRE if lab == "DB" else (T.INK_3 if lab == "?" else T.RED)
            pygame.draw.rect(surf, col, r, 1)
            fx.text(surf, lab, r.center, 11, col, "medium", mono=True, anchor="center")
            cx += wlab
            if i < len(steps) - 1:
                pygame.draw.line(surf, T.INK_3, (cx + 2, r.centery), (cx + 9, r.centery), 1)
                cx += 12
        y += 30
    sus = [(u, p) for u, p in d.get("decoy_suspects", []) if p > 0.05]
    if sus:
        fx.text(surf, "Decoy suspects: " + ", ".join(f"{net.label[u]} {int(p * 100)}%" for u, p in sus[:3]),
                (x, y), 11, T.INK_2, "regular")


def draw_blue_panel(surf, rect, match, view, human=False, human_help=None, subtitle=None, can_switch=True):
    g, net, d = match.game, match.net, match.blue_debug
    _frame(surf, rect, T.BLUE, "BLUE  /  DEFENDER",
           subtitle or ("particle filter, fuzzy logic, minimax + alpha-beta" if not human else "You are playing Blue"))
    if view == "red":
        _hidden(surf, rect, T.BLUE, "Red", can_switch)
        return
    x, w = rect.x + 20, rect.w - 40
    y = rect.y + 76
    if human:
        y = _section(surf, x, y, w, "Your tools")
        for line in human_help or []:
            col = line[1] if isinstance(line, tuple) else T.TEXT
            s = line[0] if isinstance(line, tuple) else line
            fx.text(surf, s, (x, y), 12, col, "regular", mono=s.startswith((">", " ")))
            y += 19
        return

    y = _section(surf, x, y, w, "Where is Red?", f"entropy {d.get('entropy', 0):.2f} bits")
    for u, p in (d.get("top") or [])[:5]:
        truth = view == "full" and u == g.red_pos
        fx.text(surf, net.label[u], (x, y), 12, T.INK, "semibold" if truth else "regular", mono=True)
        if truth:
            fx.text(surf, "actual position", (x + 58, y + 1), 11, T.RED, "medium")
        fx.text(surf, f"{p * 100:.0f}%", (x + w, y), 12, T.BLUE, "medium", mono=True, anchor="topright")
        y += 17
        fx.bar(surf, pygame.Rect(x, y, w, 3), p, T.BLUE)
        y += 10
    y += 6

    y = _section(surf, x, y, w, "Fuzzy threat")
    mt = d.get("max_threat", 0.0)
    lvl = "ACT" if mt >= match.blue.weights["act"] else "WATCH" if mt >= match.blue.weights["watch"] else "CALM"
    col = {"ACT": T.RED, "WATCH": T.ALERT, "CALM": T.GREEN}[lvl]
    fx.text(surf, f"{mt:.0f}", (x, y - 6), 32, T.INK, "medium", mono=True)
    fx.spaced(surf, lvl, (x + 60, y + 3), 17, col, "bold", 2)
    gr = pygame.Rect(x + 130, y + 10, w - 130, 6)
    fx.bar(surf, gr, mt / 100, col)
    for thr in (match.blue.weights["watch"], match.blue.weights["act"]):
        tx = gr.x + int(gr.w * thr / 100)
        pygame.draw.line(surf, T.INK, (tx, gr.y - 4), (tx, gr.bottom + 3), 1)
    y += 36
    for u, sc, level in (d.get("threat_top") or [])[:3]:
        fx.text(surf, net.label[u], (x, y), 12, T.INK, "regular", mono=True)
        fx.text(surf, f"{sc:.0f}  {level}", (x + w, y), 11, T.INK_2, "regular", mono=True, anchor="topright")
        y += 17
    y += 8

    y = _section(surf, x, y, w, "Minimax + alpha-beta")
    fx.text(surf, f"{d.get('options', 0)} plans vs Red's best replies, {d.get('evaluated', 0)} evals",
            (x, y - 4), 11, T.INK_3, "regular")
    y += 18
    for a in d.get("actions") or []:
        cost = C.action_cost(a[0], a[1], net.gateway)
        fx.text(surf, blue_act_text(net, a), (x, y), 15, T.INK, "semibold")
        for i in range(cost):
            pygame.draw.rect(surf, T.BLUE, (x + w - 8 - i * 12, y + 6, 8, 8))
        y += 22
    if not d.get("actions"):
        fx.text(surf, "Hold (no action)", (x, y), 13, T.INK_3, "regular")
        y += 22
    y += 8
    y = _section(surf, x, y, w, "Alerts last round")
    alerts = g.history[-1].alerts if g.history else []
    if not alerts:
        fx.text(surf, "quiet", (x, y), 12, T.INK_3, "regular")
    for u, s_, real in alerts[:4]:
        fx.text(surf, net.label[u], (x, y), 12, T.ALERT, "semibold", mono=True)
        fx.bar(surf, pygame.Rect(x + 70, y + 7, w - 160, 3), s_, T.ALERT)
        tag = ("real" if real else "false alarm") if view == "full" else f"{s_:.2f}"
        fx.text(surf, tag, (x + w, y), 11, T.INK if real else T.INK_2, "regular", anchor="topright")
        y += 18
    y = max(y + 10, rect.bottom - 30)
    ready = g.round >= g.isolate_ready
    fx.hrule(surf, x, x + w, y - 8)
    fx.text(surf, f"Decoys {len(g.decoys)}/{C.MAX_DECOYS}      Isolate {'ready' if ready else 'recharging'}",
            (x, y), 11, T.INK_2, "regular", mono=True)


# -- bottom strip -----------------------------------------------------------------
def draw_bottom(surf, log_lines, controls, t):
    r = pygame.Rect(0, T.H - T.BOTTOM_H, T.W, T.BOTTOM_H)
    pygame.draw.rect(surf, T.PAPER, r)
    pygame.draw.line(surf, T.INK, r.topleft, r.topright, 2)
    fx.label(surf, "Move log", (24, r.y + 12))
    y = r.y + 38
    for i, (rnd, col, s) in enumerate(log_lines[-5:]):
        if i:
            fx.hrule(surf, 24, 900, y - 3, T.PAPER_3)
        fx.text(surf, f"R{rnd:02d}", (24, y), 12, T.INK_3, "regular", mono=True)
        fx.text(surf, s, (68, y), 13, col, "regular")
        y += 21

    # controls: two columns of keycaps
    pygame.draw.line(surf, T.RULE, (1010, r.y + 14), (1010, T.H - 14))
    fx.label(surf, "Controls", (1032, r.y + 12))
    cols = [1032, 1300]
    x_i, y = 0, r.y + 38
    for keycap, label in controls:
        x = cols[x_i]
        f = T.font(11, "medium", mono=True)
        kw = max(22, f.size(keycap)[0] + 12)
        kr = pygame.Rect(x, y, kw, 20)
        pygame.draw.rect(surf, T.PAPER_2, kr)
        pygame.draw.rect(surf, T.INK_2, kr, 1)
        pygame.draw.line(surf, T.INK_2, (kr.x + 1, kr.bottom), (kr.right - 1, kr.bottom), 1)
        fx.text(surf, keycap, kr.center, 11, T.INK, "medium", mono=True, anchor="center")
        fx.text(surf, label, (kr.right + 10, y + 10), 12, T.INK_2, "regular", anchor="midleft")
        y += 26
        if y > T.H - 30:
            y = r.y + 38
            x_i = min(x_i + 1, len(cols) - 1)
