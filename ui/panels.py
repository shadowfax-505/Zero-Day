"""Top bar, the two AI panels and the bottom log/controls strip."""

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


def draw_top(surf, match, view, speed, paused, mode_label, t):
    g, net = match.game, match.net
    pygame.draw.rect(surf, (7, 12, 28), (0, 0, T.W, T.TOP_H))
    pygame.draw.line(surf, T.PANEL_EDGE, (0, T.TOP_H), (T.W, T.TOP_H))
    fx.blit_glow(surf, (70, 32), 50, T.RED, 0.35)
    fx.text(surf, "ZERO", (24, 32), 26, T.WHITE, "black", anchor="midleft")
    fx.text(surf, "DAY", (100, 32), 26, T.RED, "black", anchor="midleft")
    fx.spaced(surf, mode_label, (170, 25), 11, T.MUTED, "semibold", 2)

    # round counter
    cx = T.W // 2
    fx.spaced(surf, "ROUND", (cx - 70, 14), 10, T.MUTED, "semibold", 3)
    fx.text(surf, f"{min(g.round, C.MAX_ROUNDS):02d}", (cx - 70, 24), 26, T.WHITE, "bold", mono=True)
    fx.text(surf, f"/ {C.MAX_ROUNDS}", (cx - 22, 34), 14, T.MUTED, "medium", mono=True)
    br = pygame.Rect(cx + 30, 30, 220, 6)
    fx.bar(surf, br, g.round / C.MAX_ROUNDS, T.mix(T.BLUE, T.RED, g.round / C.MAX_ROUNDS))

    # view pills
    x = T.W - 24
    for v in ("blue", "full", "red"):
        name = VIEW_NAMES[v]
        f = T.font(11, "bold")
        w = f.size(name)[0] + 22
        r = pygame.Rect(x - w, 18, w, 28)
        active = v == view
        col = {"red": T.RED, "blue": T.BLUE, "full": T.TEXT}[v]
        if active:
            pygame.draw.rect(surf, T.scale(col, 0.25), r, border_radius=14)
            pygame.draw.rect(surf, col, r, 1, border_radius=14)
        else:
            pygame.draw.rect(surf, T.PANEL_EDGE, r, 1, border_radius=14)
        fx.text(surf, name, r.center, 11, col if active else T.MUTED, "bold", anchor="center")
        x -= w + 8
    state = "PAUSED" if paused else f"{speed:g}x"
    fx.text(surf, f"seed {net.seed}  ·  {state}", (x - 14, 32), 12, T.MUTED, "medium", mono=True, anchor="midright")


def _header(surf, rect, title, sub, color):
    pygame.draw.rect(surf, color, (rect.x, rect.y + 16, 4, 34), border_radius=2)
    fx.spaced(surf, title, (rect.x + 18, rect.y + 14), 12, color, "bold", 3)
    fx.text(surf, sub, (rect.x + 18, rect.y + 32), 13, T.MUTED, "medium")


def _row(surf, x, y, label, value, vcol=T.TEXT, w=300):
    fx.text(surf, label, (x, y), 12, T.MUTED, "medium")
    fx.text(surf, value, (x + w, y), 13, vcol, "semibold", anchor="topright")


def _hidden(surf, rect, color, who):
    fx.text(surf, f"Hidden in {who}'s view", (rect.centerx, rect.centery - 10), 15, T.scale(color, 0.8), "semibold",
            anchor="center")
    fx.text(surf, "Press V to switch view", (rect.centerx, rect.centery + 14), 12, T.DIM, "medium", anchor="center")


def draw_red_panel(surf, rect, match, view, human=False, human_help=None):
    g, net, d = match.game, match.net, match.red_debug
    fx.rounded_panel(surf, rect)
    _header(surf, rect, "RED · INTRUDER", "A* route · IS-MCTS · opponent model" if not human else "You are playing Red",
            T.RED)
    if view == "blue":
        _hidden(surf, rect, T.RED, "Blue")
        return
    x, y, w = rect.x + 20, rect.y + 66, rect.w - 40
    _row(surf, x, y, "Target", "Database", T.GOLD, w)
    y += 22
    _row(surf, x, y, "Position", f"{net.label[g.red_pos]}  ·  {C.ZONE_NAMES[net.zone[g.red_pos]].title()}", T.RED_SOFT, w)
    y += 22
    _row(surf, x, y, "Nodes held", str(len(g.red_held)), T.TEXT, w)
    y += 22
    hops = net.hops_to_db[g.red_pos]
    _row(surf, x, y, "Links to database", str(hops) if hops != math.inf else "-", T.TEXT, w)
    y += 30

    if human:
        fx.spaced(surf, "YOUR MOVES", (x, y), 10, T.MUTED, "bold", 2)
        y += 20
        for line in human_help or []:
            fx.text(surf, line, (x, y), 12, T.TEXT, "medium")
            y += 19
        return

    fx.spaced(surf, "NEXT MOVE", (x, y), 10, T.MUTED, "bold", 2)
    y += 18
    fx.text(surf, act_text(net, d.get("next")), (x, y), 19, T.WHITE, "bold")
    y += 28
    astar = d.get("astar_next")
    if astar and d.get("next") and tuple(astar) != tuple(d["next"]):
        fx.text(surf, f"MCTS overrode A* ({act_text(net, astar)})", (x, y), 11, T.AMBER, "medium")
    else:
        fx.text(surf, "A* and MCTS agree", (x, y), 11, T.DIM, "medium")
    y += 22
    risk = d.get("risk", 0.0)
    fx.text(surf, "Detection risk", (x, y), 12, T.MUTED, "medium")
    fx.text(surf, f"{int(risk * 100)}%", (x + w, y), 12, T.TEXT, "semibold", anchor="topright")
    y += 18
    fx.bar(surf, pygame.Rect(x, y, w, 6), risk, T.mix(T.GREEN, T.RED, min(1.0, risk * 1.6)))
    y += 22

    fx.spaced(surf, "MONTE CARLO SEARCH", (x, y), 10, T.MUTED, "bold", 2)
    fx.text(surf, f"{d.get('iterations', 0)} sims · {d.get('think_ms', 0)} ms", (x + w, y - 1), 11, T.DIM,
            "medium", mono=True, anchor="topright")
    y += 20
    stats = d.get("mcts") or []
    total = sum(n for _, n, _ in stats) or 1
    for a, n, q in stats[:4]:
        chosen = d.get("next") and tuple(a) == tuple(d["next"])
        fx.text(surf, act_text(net, a), (x, y), 12, T.WHITE if chosen else T.MUTED, "semibold" if chosen else "medium")
        fx.text(surf, f"{q:.2f}", (x + w, y), 11, T.MUTED, "medium", mono=True, anchor="topright")
        y += 17
        fx.bar(surf, pygame.Rect(x, y, w, 5), n / total, T.RED if chosen else T.scale(T.RED, 0.45))
        y += 12
    if not stats:
        fx.text(surf, "-", (x, y), 12, T.DIM)
        y += 18
    y += 8

    fx.spaced(surf, "OPPONENT MODEL", (x, y), 10, T.MUTED, "bold", 2)
    y += 20
    m = d.get("model", {})
    pm = m.get("p_monitor", [0, 0, 0])
    bw = (w - 20) // 3
    for z in range(3):
        bx = x + z * (bw + 10)
        fx.text(surf, C.ZONE_NAMES[z].title(), (bx, y), 11, T.MUTED, "medium")
        fx.bar(surf, pygame.Rect(bx, y + 17, bw, 5), pm[z], T.BLUE_SOFT)
        fx.text(surf, f"{int(pm[z] * 100)}%", (bx + bw, y), 11, T.TEXT, "medium", mono=True, anchor="topright")
    y += 30
    fx.text(surf, "P(zone watched)  ·  caught " + str(m.get("caught", 0)) + "  ·  decoys hit " +
            str(m.get("decoys_found", 0)), (x, y), 11, T.DIM, "medium")
    y += 20
    y += 26
    route = d.get("route") or []
    if route:
        fx.spaced(surf, "A* ROUTE", (x, y), 10, T.MUTED, "bold", 2)
        y += 20
        cx = x
        steps = [net.label[u] for u in route] + ([] if d.get("reaches_db") else ["fog...", "DB"])
        for i, lab in enumerate(steps):
            f = T.font(11, "semibold")
            wlab = f.size(lab)[0] + 14
            if cx + wlab > x + w:
                cx = x
                y += 24
            r = pygame.Rect(cx, y, wlab, 20)
            col = T.GOLD if lab == "DB" else (T.MUTED if lab == "fog..." else T.RED_SOFT)
            pygame.draw.rect(surf, T.scale(col, 0.18), r, border_radius=10)
            fx.text(surf, lab, r.center, 11, col, "semibold", anchor="center")
            cx += wlab + 6
        y += 30
    sus = [(u, p) for u, p in d.get("decoy_suspects", []) if p > 0.05]
    if sus:
        fx.text(surf, "Decoy suspects: " + ", ".join(f"{net.label[u]} {int(p * 100)}%" for u, p in sus[:3]),
                (x, y), 11, T.AMBER, "medium")


def draw_blue_panel(surf, rect, match, view, human=False, human_help=None):
    g, net, d = match.game, match.net, match.blue_debug
    fx.rounded_panel(surf, rect)
    _header(surf, rect, "BLUE · DEFENDER", "particle filter · fuzzy · minimax" if not human else "You are playing Blue",
            T.BLUE)
    if view == "red":
        _hidden(surf, rect, T.BLUE, "Red")
        return
    x, y, w = rect.x + 20, rect.y + 66, rect.w - 40
    if human:
        fx.spaced(surf, "YOUR TOOLS", (x, y), 10, T.MUTED, "bold", 2)
        y += 20
        for line in human_help or []:
            col = line[1] if isinstance(line, tuple) else T.TEXT
            s = line[0] if isinstance(line, tuple) else line
            fx.text(surf, s, (x, y), 12, col, "medium")
            y += 19
        return

    fx.spaced(surf, "WHERE IS RED?", (x, y), 10, T.MUTED, "bold", 2)
    fx.text(surf, f"entropy {d.get('entropy', 0):.2f} bits", (x + w, y - 1), 11, T.DIM, "medium", mono=True,
            anchor="topright")
    y += 20
    for u, p in (d.get("top") or [])[:5]:
        truth = view == "full" and u == g.red_pos
        fx.text(surf, net.label[u], (x, y), 12, T.WHITE if truth else T.TEXT, "semibold")
        if truth:
            fx.text(surf, "RED IS HERE", (x + 62, y + 1), 9, T.RED_SOFT, "bold")
        fx.text(surf, f"{p * 100:.0f}%", (x + w, y), 12, T.BLUE_SOFT, "semibold", mono=True, anchor="topright")
        y += 17
        fx.bar(surf, pygame.Rect(x, y, w, 5), p, T.BLUE)
        y += 12
    y += 10

    fx.spaced(surf, "FUZZY THREAT", (x, y), 10, T.MUTED, "bold", 2)
    y += 20
    mt = d.get("max_threat", 0.0)
    lvl = "ACT" if mt >= match.blue.weights["act"] else "WATCH" if mt >= match.blue.weights["watch"] else "CALM"
    col = {"ACT": T.RED_SOFT, "WATCH": T.AMBER, "CALM": T.GREEN}[lvl]
    fx.text(surf, f"{mt:.0f}", (x, y - 2), 28, T.WHITE, "bold", mono=True)
    fx.text(surf, lvl, (x + 64, y + 8), 13, col, "bold")
    gr = pygame.Rect(x + 120, y + 12, w - 120, 8)
    fx.bar(surf, gr, mt / 100, T.mix(T.GREEN, T.RED, mt / 100))
    for thr in (match.blue.weights["watch"], match.blue.weights["act"]):
        tx = gr.x + int(gr.w * thr / 100)
        pygame.draw.line(surf, T.TEXT, (tx, gr.y - 3), (tx, gr.bottom + 3), 1)
    y += 40
    for u, sc, level in (d.get("threat_top") or [])[:3]:
        fx.text(surf, net.label[u], (x, y), 12, T.TEXT, "medium")
        fx.text(surf, f"{sc:.0f}  {level}", (x + w, y), 11, T.MUTED, "medium", mono=True, anchor="topright")
        y += 17
    y += 10

    fx.spaced(surf, "MINIMAX + ALPHA-BETA", (x, y), 10, T.MUTED, "bold", 2)
    y += 16
    fx.text(surf, f"{d.get('options', 0)} plans vs Red's best replies · {d.get('evaluated', 0)} evals",
            (x, y), 11, T.DIM, "medium")
    y += 22
    for a in d.get("actions") or []:
        cost = C.action_cost(a[0], a[1], net.gateway)
        fx.text(surf, blue_act_text(net, a), (x, y), 14, T.WHITE, "semibold")
        for i in range(cost):
            pygame.draw.circle(surf, T.BLUE, (x + w - i * 12, y + 9), 4)
        y += 22
    if not d.get("actions"):
        fx.text(surf, "Hold (no action)", (x, y), 13, T.DIM, "medium")
        y += 22
    y += 12
    fx.spaced(surf, "ALERTS LAST ROUND", (x, y), 10, T.MUTED, "bold", 2)
    y += 20
    alerts = g.history[-1].alerts if g.history else []
    if not alerts:
        fx.text(surf, "quiet", (x, y), 12, T.DIM, "medium")
    for u, s_, real in alerts[:4]:
        fx.text(surf, net.label[u], (x, y), 12, T.AMBER, "semibold")
        fx.bar(surf, pygame.Rect(x + 70, y + 6, w - 160, 5), s_, T.AMBER)
        tag = ("real" if real else "false alarm") if view == "full" else f"{s_:.2f}"
        fx.text(surf, tag, (x + w, y), 11, T.MUTED if not real else T.TEXT, "medium", anchor="topright")
        y += 18
    y = max(y + 10, rect.bottom - 34)
    ready = g.round >= g.isolate_ready
    fx.text(surf, f"Decoys {len(g.decoys)}/{C.MAX_DECOYS}   ·   Isolate {'ready' if ready else 'recharging'}",
            (x, y), 11, T.DIM, "medium")


def draw_bottom(surf, log_lines, controls, t):
    r = pygame.Rect(0, T.H - T.BOTTOM_H, T.W, T.BOTTOM_H)
    pygame.draw.rect(surf, (7, 12, 28), r)
    pygame.draw.line(surf, T.PANEL_EDGE, r.topleft, r.topright)
    fx.spaced(surf, "MOVE LOG", (24, r.y + 14), 10, T.MUTED, "bold", 2)
    y = r.y + 34
    for rnd, col, s in log_lines[-5:]:
        fx.text(surf, f"R{rnd:02d}", (24, y), 12, T.DIM, "medium", mono=True)
        fx.text(surf, s, (68, y), 13, col, "medium")
        y += 21
    x = T.W - 24
    y = r.y + 16
    for keycap, label in controls:
        f = T.font(11, "bold", mono=True)
        kw = f.size(keycap)[0] + 14
        lw = T.font(12, "medium").size(label)[0]
        kr = pygame.Rect(x - lw - kw - 8, y, kw, 22)
        pygame.draw.rect(surf, (20, 32, 60), kr, border_radius=5)
        pygame.draw.rect(surf, T.PANEL_EDGE, kr, 1, border_radius=5)
        fx.text(surf, keycap, kr.center, 11, T.TEXT, "bold", mono=True, anchor="center")
        fx.text(surf, label, (x, y + 11), 12, T.MUTED, "medium", anchor="midright")
        y += 26
        if y > T.H - 30:
            y = r.y + 16
            x -= 230
