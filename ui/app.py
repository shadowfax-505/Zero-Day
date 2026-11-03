"""Pygame application: main menu, match screen (AI vs AI or Human vs AI) and
result screen. AI moves are computed on a worker thread so the board keeps
animating while the agents think."""

import math
import os
import random
import threading
import time

import pygame

from agents.blue.agent import BlueAI
from agents.human import HumanRed, HumanBlue
from agents.red.agent import RedAI
from engine import config as C
from engine.mapgen import generate
from engine.match import Match
from ui import fx
from ui import theme as T
from ui.board import Board, VIEWS
from ui.panels import draw_top, draw_red_panel, draw_blue_panel, draw_bottom, act_text, blue_act_text

SPEEDS = [0.5, 1, 2, 4]
TOOLS = ["monitor", "patch", "decoy", "isolate", "restore"]
MENU_MAP = pygame.Rect(720, 128, 790, 560)


class App:
    def __init__(self, mode=None, seed=None, speed=1, view="full", windowed=True, record=None):
        pygame.init()
        pygame.display.set_caption("Zero Day - Red AI vs Blue AI")
        flags = pygame.SCALED | (pygame.RESIZABLE if windowed else pygame.FULLSCREEN)
        self.screen = pygame.display.set_mode((T.W, T.H), flags)
        self.clock = pygame.time.Clock()
        self.t = 0.0
        self.seed = seed if seed is not None else random.randrange(1, 100000)
        self.speed_i = SPEEDS.index(speed) if speed in SPEEDS else 1
        self.default_view = view
        self.record = record
        self.frame = 0
        if record:
            os.makedirs(record, exist_ok=True)
        self.background = self._make_background()
        self.menu_board = Board(generate(self.seed), MENU_MAP)
        self.menu_sel = 0
        self.effects = []
        self.state = "menu"
        self.match = None
        if mode:
            self.start_match(mode)

    # -- setup -------------------------------------------------------------------
    def _make_background(self):
        """Plain paper with a faint print grain."""
        bg = pygame.Surface((T.W, T.H))
        bg.fill(T.PAPER)
        rng = random.Random(7)
        for _ in range(9000):
            x, y = rng.randrange(T.W), rng.randrange(T.H)
            bg.set_at((x, y), T.mix(T.PAPER, T.INK_3, rng.uniform(0.08, 0.22)))
        return bg

    def start_match(self, mode, same_map=False):
        self.mode = mode
        net = self.match.net if (same_map and self.match) else generate(self.seed)
        red = HumanRed() if mode == "red" else RedAI()
        blue = HumanBlue() if mode == "blue" else BlueAI()
        self.match = Match(red, blue, net=net)
        self.board = Board(net)
        self.view = {"red": "red", "blue": "blue"}.get(mode, self.default_view)
        self.state = "match"
        self.phase = "think"
        self.phase_t = 0.0
        self.paused = mode == "ai" and False
        self.step_once = False
        self.effects = []
        self.log = []
        self.pending_red = None
        self.pending_blue = None
        self.worker = None
        self.human_tool = "isolate"
        self.human_blue_acts = []
        self.result_t = 0.0
        self.mode_label = {"ai": "AI VS AI", "red": "YOU (RED) VS BLUE AI", "blue": "RED AI VS YOU (BLUE)"}[mode]
        # Blue's belief needs one look at the board before the first round
        if mode == "red":
            self.match.blue_debug = {}
        self._start_thinking()

    @property
    def speed(self):
        return SPEEDS[self.speed_i]

    # -- thinking ----------------------------------------------------------------
    def _start_thinking(self):
        m = self.match
        self.pending_red = None
        self.pending_blue = None
        self.human_blue_acts = []

        def work():
            if not isinstance(m.blue, HumanBlue):
                self.pending_blue = m.ask_blue()
            if not isinstance(m.red, HumanRed):
                self.pending_red = m.ask_red()

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()
        self.phase = "think"
        self.phase_t = 0.0

    def _ready(self):
        return self.pending_red is not None and self.pending_blue is not None and not self.worker.is_alive()

    # -- round resolution ------------------------------------------------------------
    def _resolve(self):
        m, g, net = self.match, self.match.game, self.match.net
        old_pos = g.red_pos
        m.apply(self.pending_red, self.pending_blue)
        rec = g.history[-1]
        self._spawn_effects(rec, old_pos)
        self._log_round(rec)
        self.phase = "settle"
        self.phase_t = 0.0

    def _fx(self, effect, views=("red", "full", "blue")):
        effect.views = views
        self.effects.append(effect)

    def _spawn_effects(self, rec, old_pos):
        g, net, P = self.match.game, self.match.net, self.board.pts
        for kind, t in rec.blue_actions:
            if kind == "isolate":
                self._fx(fx.Ripple(P[t], T.BLUE, 70, 0.9, 3), ("full", "blue", "red"))
                self._fx(fx.Burst(P[t], T.BLUE, 18, 120))
            elif kind == "patch":
                self._fx(fx.Ripple(P[t], T.BLUE, 34, 0.8, 2), ("full", "blue"))
                self._fx(fx.FloatText(P[t], "PATCHED", T.BLUE, 11), ("full", "blue"))
            elif kind == "decoy":
                self._fx(fx.Ripple(P[t], T.AMBER, 40, 0.9, 2), ("full", "blue"))
            elif kind == "restore":
                self._fx(fx.Ripple(P[t], T.BLUE_SOFT, 40, 0.8, 2), ("full", "blue"))
        a = rec.red_action
        res = rec.red_result
        target = a[1] if len(a) > 1 else (net.database if a[0] == "claim" else old_pos)
        if a[0] in ("capture", "unlock", "claim") and res not in ("cancelled", "removed"):
            ok = res in ("captured", "unlocked", "claimed")
            col = T.GOLD if a[0] == "claim" else T.RED
            self._fx(fx.Beam(P[old_pos], P[target], col, 0.8, ok), ("red", "full"))
            if ok:
                self._fx(fx.Burst(P[target], col, 30, 160), ("red", "full"))
            else:
                self._fx(fx.FloatText(P[target], "BLOCKED" if res == "blocked" else "FAILED", T.INK_2, 11),
                         ("red", "full"))
        elif a[0] == "advance" and res == "advanced":
            self._fx(fx.Beam(P[old_pos], P[target], T.RED_SOFT, 0.5, True), ("red", "full"))
        elif a[0] == "scout" and res == "scouted":
            self._fx(fx.Ripple(P[old_pos], T.RED_SOFT, 90, 1.2, 1, dashed=True), ("red", "full"))
            self._fx(fx.FloatText(P[old_pos], "SCOUT", T.RED_SOFT, 11), ("red", "full"))
        for u, s, real in rec.alerts:
            self._fx(fx.Ripple(P[u], T.AMBER, 30 + 40 * s, 1.3, 3 if s > 0.5 else 2, dashed=not real),
                     ("blue",) if True else ())
            self._fx(fx.Ripple(P[u], T.AMBER if real else T.INK_3, 30 + 40 * s, 1.3, 2, dashed=not real), ("full",))
        if rec.alerts:
            strongest = rec.alerts[0]
            self._fx(fx.FloatText(P[strongest[0]], "ALERT", T.AMBER, 11), ("blue", "full"))
        for ev in rec.events:
            if "cut Red off" in ev:
                self._fx(fx.FloatText(P[old_pos], "CUT OFF!", T.BLUE_SOFT, 15))
                self._fx(fx.Flash(T.BLUE, 0.4, 50))
            elif "decoy" in ev:
                self._fx(fx.FloatText(P[target], "DECOY!", T.AMBER, 15))
                self._fx(fx.Burst(P[target], T.AMBER, 34, 170))
            elif "restored" in ev:
                self._fx(fx.FloatText(P[next(u for u in range(net.n) if net.label[u] in ev)], "RESTORED", T.BLUE_SOFT, 12),
                         ("full", "blue", "red"))
        if g.winner == "red":
            self._fx(fx.Flash(T.GOLD, 1.2, 120))
            self._fx(fx.Burst(P[net.database], T.GOLD, 80, 260, 1.6))
        elif g.winner == "blue" and "removed" in g.reason:
            self._fx(fx.Flash(T.BLUE, 1.0, 90))

    def _log_round(self, rec):
        net = self.match.net
        red = f"Red: {act_text(net, rec.red_action)} ({rec.red_result})"
        blue = "Blue: " + (", ".join(blue_act_text(net, a) for a in rec.blue_actions) or "hold")
        alerts = f"{len(rec.alerts)} alert{'s' if len(rec.alerts) != 1 else ''}"
        if self.view == "red":
            line = red
        elif self.view == "blue":
            line = f"{blue}   ·   {alerts}"
        else:
            line = f"{red}   ·   {blue}   ·   {alerts}"
        col = T.TEXT
        for ev in rec.events:
            if "decoy" in ev or "cut Red off" in ev or "restored" in ev:
                col = T.BLUE
            if "claimed" in ev:
                col = T.GOLD
        self.log.append((rec.round, col, line))
        for ev in rec.events:
            if "captured" in ev or (self.view == "blue" and "unlocked" in ev):
                continue
            self.log.append((rec.round, T.INK_2, "   " + ev))

    # -- human input -------------------------------------------------------------------
    def _human_red_targets(self):
        g = self.match.game
        out = {}
        for a in g.red_legal():
            if a[0] == "claim":
                out[self.match.net.database] = a
            elif len(a) > 1:
                out[a[1]] = a
        return out

    def _human_blue_ap(self):
        net = self.match.net
        return C.BLUE_AP - sum(C.action_cost(k, t, net.gateway) for k, t in self.human_blue_acts)

    def _human_blue_add(self, node):
        g, net = self.match.game, self.match.net
        tool = self.human_tool
        target = net.zone[node] if tool == "monitor" else node
        cost = C.action_cost(tool, target, net.gateway)
        if cost > self._human_blue_ap() or not g.blue_can(tool, target):
            self._fx(fx.FloatText(self.board.pts[node], "NOT ALLOWED", T.INK_2, 11))
            return
        if (tool, target) in self.human_blue_acts:
            return
        if tool == "isolate" and any(k == "isolate" for k, _ in self.human_blue_acts):
            return
        self.human_blue_acts.append((tool, target))

    def _human_blue_commit(self):
        self.pending_blue = list(self.human_blue_acts)
        self.match.blue_debug = {"actions": list(self.human_blue_acts)}

    # -- events ---------------------------------------------------------------------------
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            return False
        if self.state == "menu":
            return self._handle_menu(ev)
        if ev.type == pygame.KEYDOWN:
            k = ev.key
            if k == pygame.K_ESCAPE or k == pygame.K_m:
                self.state = "menu"
                return True
            if k == pygame.K_F12:
                self._screenshot()
            if self.state == "result":
                if k == pygame.K_r:
                    self.start_match(self.mode, same_map=True)
                elif k in (pygame.K_n, pygame.K_RETURN):
                    self.seed = random.randrange(1, 100000)
                    self.start_match(self.mode)
                return True
            if k == pygame.K_v and self.mode == "ai":
                self.view = VIEWS[(VIEWS.index(self.view) + 1) % 3]
            elif k == pygame.K_1 and self.mode == "ai":
                self.view = "red"
            elif k == pygame.K_2 and self.mode == "ai":
                self.view = "full"
            elif k == pygame.K_3 and self.mode == "ai":
                self.view = "blue"
            elif k in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                self.speed_i = min(len(SPEEDS) - 1, self.speed_i + 1)
            elif k in (pygame.K_MINUS, pygame.K_KP_MINUS):
                self.speed_i = max(0, self.speed_i - 1)
            elif k == pygame.K_r:
                self.start_match(self.mode, same_map=True)
            elif k == pygame.K_n and self.mode == "ai":
                self.step_once = True
            elif k == pygame.K_SPACE and self.mode == "ai":
                self.paused = not self.paused
            elif self.mode == "red" and k == pygame.K_s and self.phase == "think" and self.pending_red is None:
                self.pending_red = ("scout",)
            elif self.mode == "blue" and self.phase == "think" and self.pending_blue is None:
                if pygame.K_F1 <= k <= pygame.K_F5:
                    self.human_tool = TOOLS[k - pygame.K_F1]
                elif k in (pygame.K_q, pygame.K_w, pygame.K_e, pygame.K_a, pygame.K_d):
                    self.human_tool = {pygame.K_q: "monitor", pygame.K_w: "patch", pygame.K_e: "decoy",
                                       pygame.K_a: "isolate", pygame.K_d: "restore"}[k]
                elif k == pygame.K_BACKSPACE and self.human_blue_acts:
                    self.human_blue_acts.pop()
                elif k in (pygame.K_RETURN, pygame.K_SPACE):
                    self._human_blue_commit()
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.state == "match" and self.phase == "think":
            if self.mode == "red" and self.pending_red is None:
                targets = self._human_red_targets()
                u = self.board.node_at(ev.pos, set(targets))
                if u is not None:
                    self.pending_red = targets[u]
            elif self.mode == "blue" and self.pending_blue is None:
                u = self.board.node_at(ev.pos)
                if u is not None:
                    self._human_blue_add(u)
        return True

    def _menu_items(self):
        return [("AI VS AI", "ai"), ("PLAY AS RED", "red"), ("PLAY AS BLUE", "blue"), ("QUIT", "quit")]

    def _handle_menu(self, ev):
        items = self._menu_items()
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.menu_sel = (self.menu_sel - 1) % len(items)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.menu_sel = (self.menu_sel + 1) % len(items)
            elif ev.key == pygame.K_LEFT:
                self.seed = max(1, self.seed - 1)
                self.menu_board = Board(generate(self.seed), MENU_MAP)
            elif ev.key == pygame.K_RIGHT:
                self.seed += 1
                self.menu_board = Board(generate(self.seed), MENU_MAP)
            elif ev.key == pygame.K_r:
                self.seed = random.randrange(1, 100000)
                self.menu_board = Board(generate(self.seed), MENU_MAP)
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                return self._menu_pick(items[self.menu_sel][1])
            elif ev.key == pygame.K_ESCAPE:
                return False
        if ev.type == pygame.MOUSEMOTION:
            for i, r in enumerate(self._menu_rects()):
                if r.collidepoint(ev.pos):
                    self.menu_sel = i
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, r in enumerate(self._menu_rects()):
                if r.collidepoint(ev.pos):
                    return self._menu_pick(items[i][1])
        return True

    def _menu_pick(self, what):
        if what == "quit":
            return False
        self.start_match(what)
        return True

    def _menu_rects(self):
        return [pygame.Rect(110, 570 + i * 52, 520, 46) for i in range(len(self._menu_items()))]

    def _screenshot(self):
        os.makedirs("screenshots", exist_ok=True)
        path = os.path.join("screenshots", f"zero-day-{int(time.time())}.png")
        pygame.image.save(self.screen, path)

    # -- update -----------------------------------------------------------------------------
    def update(self, dt):
        self.t += dt
        for e in self.effects:
            e.update(dt * max(1.0, self.speed * 0.75))
        self.effects = [e for e in self.effects if not e.done]
        if self.state != "match":
            if self.state == "result":
                self.result_t += dt
            return
        g = self.match.game
        self.phase_t += dt * self.speed
        if self.phase == "think":
            min_think = 0.35 if self.mode == "ai" else 0.0
            can_go = (not self.paused) or self.step_once or self.mode != "ai"
            if self._ready() and self.phase_t >= min_think and can_go:
                self.step_once = False
                self.phase = "reveal"
                self.phase_t = 0.0
        elif self.phase == "reveal":
            if self.phase_t >= 0.55:
                self._resolve()
        elif self.phase == "settle":
            if self.phase_t >= 0.9:
                if g.winner:
                    self.state = "result"
                    self.result_t = 0.0
                else:
                    self._start_thinking()

    # -- drawing ----------------------------------------------------------------------------
    def draw(self):
        s = self.screen
        s.blit(self.background, (0, 0))
        if self.state == "menu":
            self._draw_menu(s)
        else:
            self._draw_match(s)
            if self.state == "result":
                self._draw_result(s)
        pygame.display.flip()

    def _draw_menu(self, s):
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
        for i, ((label, _), r) in enumerate(zip(self._menu_items(), self._menu_rects())):
            sel = i == self.menu_sel
            col = [T.INK, T.RED, T.BLUE, T.INK_2][i]
            if sel:
                pygame.draw.rect(s, col, r)
            fx.text(s, f"{i + 1:02d}", (r.x + 14, r.centery), 15, T.PAPER if sel else T.INK_3, "medium", mono=True,
                    anchor="midleft")
            fx.spaced(s, label, (r.x + 56, r.centery + 1), 24, T.PAPER if sel else col, "bold", 2, anchor="midleft")
            if sel:
                fx.text(s, "Enter", (r.right - 14, r.centery), 13, T.PAPER, "medium", mono=True, anchor="midright")
            fx.hrule(s, r.x, r.right, r.bottom, T.RULE)

        # right column: the map, printed as a plate with a caption
        b = self.menu_board
        b.draw(s, _MenuGame(b.net), "full", self.t)
        pr = b.rect
        fx.spaced(s, f"MAP {self.seed}", (pr.x, pr.bottom + 12), 17, T.INK, "bold", 2)
        fx.text(s, "Left / Right: change map     R: random map", (pr.right, pr.bottom + 14), 13, T.INK_2,
                "regular", mono=True, anchor="topright")
        fx.text(s, "Red starts at GW and is after DB. Blue sees every node but never Red.",
                (pr.x, pr.bottom + 40), 13, T.INK_2, "regular")

        fx.hrule(s, x0, T.W - 60, T.H - 52)
        fx.text(s, "Muttakin Rahman Shoscho (2207061)     Yasar Wajih (2207064)", (x0, T.H - 30), 14, T.INK_2,
                "regular", anchor="midleft")
        fx.text(s, "Up / Down to choose, Enter to start, Esc to quit", (T.W - 60, T.H - 30), 13, T.INK_3,
                "regular", mono=True, anchor="midright")

    def _draw_match(self, s):
        m, g = self.match, self.match.game
        hl, hover = (), None
        mouse = pygame.mouse.get_pos()
        monitored = set(g.monitored)
        if self.phase == "reveal" and self.pending_blue:
            monitored |= {t for k, t in self.pending_blue if k == "monitor"}
        if self.mode == "red" and self.phase == "think" and self.pending_red is None:
            targets = self._human_red_targets()
            hl = set(targets)
            hover = self.board.node_at(mouse, hl)
        if self.mode == "blue" and self.phase == "think" and self.pending_blue is None:
            hover = self.board.node_at(mouse)
            monitored |= {t for k, t in self.human_blue_acts if k == "monitor"}
        red_dbg = m.red_debug if self.mode != "red" else {}
        self.board.draw(s, g, self.view, self.t, red_dbg, m.blue_debug, hl, hover, monitored)
        self._draw_pending(s)
        for e in self.effects:
            if self.view in getattr(e, "views", VIEWS):
                if isinstance(e, fx.Flash):
                    continue
                e.draw(s)
        if self.phase == "think" and not self._ready() and self.worker.is_alive():
            self._draw_thinking(s)

        draw_top(s, m, self.view, self.speed, self.paused, self.mode_label, self.t)
        left = pygame.Rect(16, T.TOP_H + 12, T.SIDE_W - 16, T.H - T.TOP_H - T.BOTTOM_H - 24)
        right = pygame.Rect(T.W - T.SIDE_W, T.TOP_H + 12, T.SIDE_W - 16, left.h)
        draw_red_panel(s, left, m, self.view, self.mode == "red", self._red_help())
        draw_blue_panel(s, right, m, self.view, self.mode == "blue", self._blue_help())
        draw_bottom(s, self.log, self._controls(), self.t)
        for e in self.effects:
            if isinstance(e, fx.Flash) and self.view in getattr(e, "views", VIEWS):
                e.draw(s)

    def _draw_pending(self, s):
        """Blue's chosen actions are shown on the board just before they resolve."""
        acts = []
        if self.phase == "reveal" and self.pending_blue and self.view != "red":
            acts = self.pending_blue
        if self.mode == "blue" and self.phase == "think":
            acts = self.human_blue_acts
        P = self.board.pts
        for k, t in acts:
            if k == "monitor":
                continue
            p = P[t]
            fx.dashed_circle(s, T.BLUE, p, 22, 2, 16, rot=self.t * 0.8)
            fx.tag(s, k.upper(), (p[0], p[1] - 32), T.BLUE, 12)
        if self.phase == "reveal" and self.pending_red and self.view != "blue":
            a = self.pending_red
            g = self.match.game
            if len(a) > 1 or a[0] == "claim":
                tgt = a[1] if len(a) > 1 else self.match.net.database
                fx.dashed_line(s, T.RED, P[g.red_pos], P[tgt], 2, 4, 4, offset=-self.t * 40)

    def _draw_thinking(self, s):
        r = self.board.rect
        names = []
        if self.pending_blue is None and not isinstance(self.match.blue, HumanBlue):
            names.append("Blue")
        if self.pending_red is None and not isinstance(self.match.red, HumanRed):
            names.append("Red")
        if not names:
            return
        dots = "." * (1 + int(self.t * 3) % 3)
        fx.text(s, f"{' and '.join(names)} thinking{dots}", (r.x + 14, r.bottom - 10), 12, T.INK_2, "regular",
                mono=True, anchor="bottomleft")

    def _red_help(self):
        if self.mode != "red":
            return None
        if self.pending_red is not None:
            return ["Move locked in. Waiting for Blue..."]
        return ["Click a marked neighbour to move:",
                "  free node: Capture (chance = weakness)",
                "  across a zone gate: Unlock (loud)",
                "  your own node: Advance (quiet)",
                "  the database: Claim (wins)",
                "S: Scout (reveals nearby nodes)",
                "",
                "Blue sees alerts, not you. Loud moves",
                "and decoys give you away."]

    def _blue_help(self):
        if self.mode != "blue":
            return None
        ap = self._human_blue_ap()
        lines = [(f"Action points left: {ap} / {C.BLUE_AP}", T.INK)]
        keys = {"monitor": "Q", "patch": "W", "decoy": "E", "isolate": "A", "restore": "D"}
        for tool in TOOLS:
            sel = tool == self.human_tool
            cost = C.COST[tool]
            lines.append((f"{'>' if sel else ' '} {keys[tool]}  {tool.title():8s} cost {cost}", T.BLUE if sel else T.INK_2))
        lines.append(("", T.TEXT))
        lines.append(("Click a node to use the tool.", T.TEXT))
        lines.append(("Backspace: undo   Enter: end turn", T.TEXT))
        lines.append(("", T.TEXT))
        for k, t in self.human_blue_acts:
            lines.append(("  " + blue_act_text(self.match.net, (k, t)), T.BLUE))
        g, net = self.match.game, self.match.net
        lines.append(("", T.TEXT))
        lines.append(("Alerts last round:", T.MUTED))
        alerts = g.history[-1].alerts if g.history else []
        for u, s_, _ in alerts[:5]:
            lines.append((f"  {net.label[u]}  strength {s_:.2f}", T.AMBER))
        if not alerts:
            lines.append(("  none", T.DIM))
        for kind, t, found in g.blue_feedback:
            if kind in ("isolate", "restore"):
                lines.append((f"  {kind.title()} {net.label[t]}: {'Red was there!' if found else 'nothing found'}",
                              T.BLUE if found else T.INK_3))
        if g.decoy_sprung is not None:
            lines.append((f"  Decoy sprung on {net.label[g.decoy_sprung]}!", T.AMBER))
        return lines

    def _controls(self):
        if self.mode == "ai":
            return [("SPACE", "play / pause"), ("N", "step one round"), ("V", "switch view"), ("+ -", "speed"),
                    ("R", "restart map"), ("M", "menu"), ("F12", "screenshot"), ("1 2 3", "red / full / blue")]
        return [("R", "restart map"), ("M", "menu"), ("F12", "screenshot")]

    def _draw_result(self, s):
        g, m = self.match.game, self.match
        k = min(1.0, self.result_t / 0.4)
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

    # -- loop -----------------------------------------------------------------------------------
    def run(self):
        running = True
        while running:
            dt = self.clock.tick(60) / 1000.0
            for ev in pygame.event.get():
                if not self.handle(ev):
                    running = False
            if self.record:
                dt = 1 / 30           # fixed step so the recording plays back at real speed
            self.update(dt)
            self.draw()
            if self.record:
                pygame.image.save(self.screen, os.path.join(self.record, f"frame_{self.frame:06d}.png"))
                self.frame += 1
        pygame.quit()


class _MenuGame:
    """Just enough game state to draw a map on the menu."""

    def __init__(self, net):
        self.red_known = set(range(net.n))
        self.red_known_edges = {}
        self.open_gates = set()
        self.red_held = set()
        self.red_pos = net.gateway
        self.isolated = {}
        self.patched = set()
        self.decoys = set()
        self.red_intel_weak = {}
        self.winner = "blue"
        self.monitored = set()
        self.history = []
