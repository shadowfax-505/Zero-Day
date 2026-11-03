"""Pygame application: main menu, settings, match screen (AI vs AI or Human vs
AI), pause/help overlays and the result screen. AI moves are computed on a
worker thread so the board keeps animating while the agents think.

The look comes from a skin (ui/skins.py): 'paper' by default, or 'dark' (the
original neon look). Switching skin rebinds the module names below
(T, fx, Board, draw_top, ...), so the rest of this file never needs to know
which one is active."""

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
from ui import overlays as O
from ui import skins
from ui.settings import Settings
from ui.sound import Sound

SPEEDS = [0.5, 1, 2, 4]
TOOLS = ["monitor", "patch", "decoy", "isolate", "restore"]
AUTO_NEXT_SECONDS = 6.0

# rebound by _use_skin()
T = fx = Board = VIEWS = screens = None
draw_top = draw_red_panel = draw_blue_panel = draw_bottom = act_text = blue_act_text = None


def _use_skin(name):
    global T, fx, Board, VIEWS, screens, draw_top, draw_red_panel, draw_blue_panel, draw_bottom, act_text, \
        blue_act_text
    sk = skins.load(name)
    T, fx, screens = sk.T, sk.fx, sk.screens
    Board, VIEWS = sk.board.Board, sk.board.VIEWS
    p = sk.panels
    draw_top, draw_red_panel, draw_blue_panel, draw_bottom = p.draw_top, p.draw_red_panel, p.draw_blue_panel, \
        p.draw_bottom
    act_text, blue_act_text = p.act_text, p.blue_act_text
    return sk


class App:
    def __init__(self, mode=None, seed=None, speed=None, view=None, windowed=None, record=None, theme=None,
                 settings_path=None):
        self.settings = Settings(settings_path) if settings_path else Settings()
        if theme in skins.THEMES:
            self.settings["theme"] = theme
        self.sk = _use_skin(self.settings["theme"])
        pygame.init()
        pygame.display.set_caption("Zero Day - Red AI vs Blue AI")
        self.fullscreen = (not windowed) if windowed is not None else self.settings["fullscreen"]
        flags = pygame.SCALED | (pygame.FULLSCREEN if self.fullscreen else pygame.RESIZABLE)
        self.screen = pygame.display.set_mode((T.W, T.H), flags)
        self.clock = pygame.time.Clock()
        self.sound = Sound()
        self._apply_sound()
        self.t = 0.0
        self.seed = seed if seed is not None else random.randrange(1, 100000)
        sp = speed if speed is not None else self.settings["speed"]
        self.speed_i = SPEEDS.index(sp) if sp in SPEEDS else 1
        self.cli_view = view
        self.record = record
        self.frame = 0
        if record:
            os.makedirs(record, exist_ok=True)
        self.menu_sel = 0
        self.settings_sel = 0
        self.settings_from = "menu"
        self.pause_sel = 0
        self.overlay = None           # None, "pause" or "help" (during a match)
        self.effects = []
        self.state = "menu"
        self.match = None
        self.mode = None
        self._build_skin_surfaces()
        if mode:
            self.start_match(mode)

    # -- setup -------------------------------------------------------------------
    @property
    def default_view(self):
        return self.cli_view or self.settings["view"]

    def _build_skin_surfaces(self):
        self.background = screens.make_background(self)
        self._new_menu_board()
        if self.match:
            self.board = Board(self.match.net)
        self._apply_labels()

    def _new_menu_board(self):
        net = generate(self.seed)
        self.menu_board = Board(net, screens.MENU_MAP) if screens.MENU_MAP else Board(net)
        self._apply_labels()

    def _apply_labels(self):
        for b in (getattr(self, "menu_board", None), getattr(self, "board", None)):
            if b is not None:
                b.show_labels = self.settings["labels"]

    def _apply_sound(self):
        self.sound.enabled = self.settings["sound"]
        self.sound.volume = self.settings["volume"]

    def set_theme(self, name):
        if name == self.sk.name:
            return
        self.settings["theme"] = name
        self.sk = _use_skin(name)
        self.effects = []
        self._build_skin_surfaces()
        self.settings.save()

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.settings["fullscreen"] = self.fullscreen
        try:
            pygame.display.toggle_fullscreen()
        except pygame.error:
            pass

    def start_match(self, mode, same_map=False):
        self.mode = mode
        net = self.match.net if (same_map and self.match) else generate(self.seed)
        red = HumanRed() if mode == "red" else RedAI()
        blue = HumanBlue() if mode == "blue" else BlueAI()
        self.match = Match(red, blue, net=net)
        self.board = Board(net)
        self._apply_labels()
        self.view = {"red": "red", "blue": "blue"}.get(mode, self.default_view)
        self.state = "match"
        self.overlay = None
        self.phase = "think"
        self.phase_t = 0.0
        self.paused = False
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

    def _new_map(self):
        self.seed = random.randrange(1, 100000)
        self.start_match(self.mode)

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
        m, g = self.match, self.match.game
        old_pos = g.red_pos
        m.apply(self.pending_red, self.pending_blue)
        rec = g.history[-1]
        self._spawn_effects(rec, old_pos)
        self._play_sounds(rec)
        self._log_round(rec)
        self.phase = "settle"
        self.phase_t = 0.0

    def _fx(self, effect, views=("red", "full", "blue")):
        if not self.settings["effects"]:
            return
        effect.views = views
        self.effects.append(effect)

    def _play_sounds(self, rec):
        g = self.match.game
        res = rec.red_result
        if g.winner:
            self.sound.play("win_red" if g.winner == "red" else "win_blue")
            return
        if any("decoy" in ev for ev in rec.events):
            self.sound.play("decoy")
        elif any(k == "isolate" for k, _ in rec.blue_actions):
            self.sound.play("isolate")
        elif res in ("captured", "unlocked", "advanced"):
            self.sound.play("capture")
        elif res in ("failed", "blocked"):
            self.sound.play("fail")
        elif res == "scouted":
            self.sound.play("scout")
        if rec.alerts and self.view != "red":
            self.sound.play("alert")

    def _spawn_effects(self, rec, old_pos):
        g, net, P = self.match.game, self.match.net, self.board.pts
        for kind, t in rec.blue_actions:
            if kind == "isolate":
                self._fx(fx.Ripple(P[t], T.BLUE, 70, 0.9, 3), ("full", "blue", "red"))
                self._fx(fx.Burst(P[t], T.BLUE_SOFT, 18, 120))
            elif kind == "patch":
                self._fx(fx.Ripple(P[t], T.CYAN, 34, 0.8, 2), ("full", "blue"))
                self._fx(fx.FloatText(P[t], "PATCHED", T.CYAN, 11), ("full", "blue"))
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
            self._fx(fx.Ripple(P[u], T.AMBER, 30 + 40 * s, 1.3, 3 if s > 0.5 else 2, dashed=not real), ("blue",))
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
                self._fx(fx.FloatText(P[next(u for u in range(net.n) if net.label[u] in ev)], "RESTORED",
                                      T.BLUE_SOFT, 12), ("full", "blue", "red"))
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
        kind = "text"
        for ev in rec.events:
            if "decoy" in ev or "cut Red off" in ev or "restored" in ev:
                kind = "blue"
            if "claimed" in ev:
                kind = "gold"
        self.log.append((rec.round, kind, line))
        for ev in rec.events:
            if "captured" in ev or (self.view == "blue" and "unlocked" in ev):
                continue
            self.log.append((rec.round, "muted", "   " + ev))

    def _log_lines(self):
        """Log with colours resolved for the current theme (so switching theme recolours it)."""
        col = {"text": T.TEXT, "blue": T.BLUE, "gold": T.GOLD, "muted": T.INK_2}
        return [(r, col[k], s) for r, k, s in self.log]

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
            self.sound.play("fail")
            return
        if (tool, target) in self.human_blue_acts:
            return
        if tool == "isolate" and any(k == "isolate" for k, _ in self.human_blue_acts):
            return
        self.human_blue_acts.append((tool, target))
        self.sound.play("click")

    def _human_blue_commit(self):
        self.pending_blue = list(self.human_blue_acts)
        self.match.blue_debug = {"actions": list(self.human_blue_acts)}

    # -- events ---------------------------------------------------------------------------
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_F11:
                self.toggle_fullscreen()
                self.settings.save()
                return True
            if ev.key == pygame.K_F12:
                self._screenshot()
                return True
        if self.state == "menu":
            return self._handle_menu(ev)
        if self.state == "settings":
            return self._handle_settings(ev)
        if self.overlay == "help":
            if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                self.overlay = "pause" if getattr(self, "_help_from_pause", False) else None
            return True
        if self.overlay == "pause":
            return self._handle_pause(ev)
        if ev.type == pygame.KEYDOWN:
            k = ev.key
            if k == pygame.K_ESCAPE:
                self._open_pause()
                return True
            if k == pygame.K_m:
                self.state = "menu"
                return True
            if k == pygame.K_h:
                self._help_from_pause = False
                self.overlay = "help"
                return True
            if k == pygame.K_t:
                self.set_theme("dark" if self.sk.name == "paper" else "paper")
                return True
            if self.state == "result":
                if k == pygame.K_r:
                    self.start_match(self.mode, same_map=True)
                elif k in (pygame.K_n, pygame.K_RETURN):
                    self._new_map()
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
                self.sound.play("click")
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
                    self.sound.play("click")
            elif self.mode == "blue" and self.pending_blue is None:
                u = self.board.node_at(ev.pos)
                if u is not None:
                    self._human_blue_add(u)
        return True

    # menu
    def _menu_items(self):
        return [("AI VS AI", "ai"), ("PLAY AS RED", "red"), ("PLAY AS BLUE", "blue"), ("SETTINGS", "settings"),
                ("QUIT", "quit")]

    def _menu_rects(self):
        return screens.menu_rects(self)

    def _handle_menu(self, ev):
        items = self._menu_items()
        if ev.type == pygame.KEYDOWN:
            if ev.key in (pygame.K_UP, pygame.K_w):
                self.menu_sel = (self.menu_sel - 1) % len(items)
                self.sound.play("click")
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.menu_sel = (self.menu_sel + 1) % len(items)
                self.sound.play("click")
            elif ev.key == pygame.K_LEFT:
                self.seed = max(1, self.seed - 1)
                self._new_menu_board()
            elif ev.key == pygame.K_RIGHT:
                self.seed += 1
                self._new_menu_board()
            elif ev.key == pygame.K_r:
                self.seed = random.randrange(1, 100000)
                self._new_menu_board()
            elif ev.key == pygame.K_t:
                self.set_theme("dark" if self.sk.name == "paper" else "paper")
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
        if what == "settings":
            self._open_settings("menu")
            return True
        self.start_match(what)
        return True

    # settings
    def _open_settings(self, came_from):
        self.settings_from = came_from
        self.settings_sel = 0
        self.state = "settings"

    def _close_settings(self):
        self.settings.save()
        if self.settings_from == "match":
            self.state = "match" if not self.match.game.winner else "result"
            self.overlay = "pause"
        else:
            self.state = "menu"

    def _change_setting(self, key, d):
        old = self.settings[key]
        new = self.settings.step(key, d)
        self.sound.play("click")
        if key == "theme":
            self.settings["theme"] = old           # set_theme compares against the current skin
            self.set_theme(new)
        elif key == "fullscreen" and new != self.fullscreen:
            self.toggle_fullscreen()
        elif key == "labels":
            self._apply_labels()
        elif key in ("sound", "volume"):
            self._apply_sound()
            self.sound.play("capture")
        elif key == "speed":
            self.speed_i = SPEEDS.index(new)
        elif key == "effects" and not new:
            self.effects = []

    def _handle_settings(self, ev):
        rows = O.settings_rows()
        if ev.type == pygame.KEYDOWN:
            k = ev.key
            key = rows[self.settings_sel]
            if k in (pygame.K_UP, pygame.K_w):
                self.settings_sel = (self.settings_sel - 1) % len(rows)
            elif k in (pygame.K_DOWN, pygame.K_s):
                self.settings_sel = (self.settings_sel + 1) % len(rows)
            elif k in (pygame.K_LEFT, pygame.K_a) and key != "back":
                self._change_setting(key, -1)
            elif k in (pygame.K_RIGHT, pygame.K_d, pygame.K_RETURN, pygame.K_SPACE) and key != "back":
                self._change_setting(key, 1)
            elif k in (pygame.K_ESCAPE, pygame.K_BACKSPACE) or (k == pygame.K_RETURN and key == "back"):
                self._close_settings()
        if ev.type == pygame.MOUSEMOTION:
            key, _ = O.settings_hit(self, ev.pos)
            if key:
                self.settings_sel = rows.index(key)
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button in (1, 3):
            key, d = O.settings_hit(self, ev.pos)
            if key == "back":
                self._close_settings()
            elif key:
                self._change_setting(key, -1 if ev.button == 3 else d)
        return True

    # pause
    def _open_pause(self):
        self.overlay = "pause"
        self.pause_sel = 0

    def _pause_pick(self, what):
        if what == "resume":
            self.overlay = None
        elif what == "settings":
            self.overlay = None
            self._open_settings("match")
        elif what == "help":
            self._help_from_pause = True
            self.overlay = "help"
        elif what == "restart":
            self.start_match(self.mode, same_map=True)
        elif what == "new":
            self._new_map()
        elif what == "menu":
            self.overlay = None
            self.state = "menu"

    def _handle_pause(self, ev):
        items = O.PAUSE_ITEMS
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.overlay = None
            elif ev.key in (pygame.K_UP, pygame.K_w):
                self.pause_sel = (self.pause_sel - 1) % len(items)
            elif ev.key in (pygame.K_DOWN, pygame.K_s):
                self.pause_sel = (self.pause_sel + 1) % len(items)
            elif ev.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._pause_pick(items[self.pause_sel][1])
        _, rects = O.pause_rects(self)
        if ev.type == pygame.MOUSEMOTION:
            for i, r in enumerate(rects):
                if r.collidepoint(ev.pos):
                    self.pause_sel = i
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, r in enumerate(rects):
                if r.collidepoint(ev.pos):
                    self._pause_pick(items[i][1])
        return True

    def _screenshot(self):
        os.makedirs("screenshots", exist_ok=True)
        path = os.path.join("screenshots", f"zero-day-{int(time.time())}.png")
        pygame.image.save(self.screen, path)

    # -- update -----------------------------------------------------------------------------
    def update(self, dt):
        self.t += dt
        if self.overlay is not None or (self.state == "settings" and self.settings_from == "match"):
            return                                     # the match is frozen behind menus
        for e in self.effects:
            e.update(dt * max(1.0, self.speed * 0.75))
        self.effects = [e for e in self.effects if not e.done]
        if self.state == "result":
            self.result_t += dt
            if self.mode == "ai" and self.settings["auto_next"] and self.result_t >= AUTO_NEXT_SECONDS:
                self._new_map()
            return
        if self.state != "match":
            return
        g = self.match.game
        self.phase_t += dt * self.speed
        if self.phase == "think":
            if (self.mode == "blue" and not self.settings["confirm_turn"] and self.pending_blue is None
                    and self.human_blue_acts and self._human_blue_ap() == 0):
                self._human_blue_commit()
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
        if self.state == "menu" or (self.state == "settings" and self.settings_from == "menu"):
            screens.draw_menu(self, s)
            if self.state == "settings":
                O.draw_settings(self, s)
        else:
            self._draw_match(s)
            if self.state == "result":
                screens.draw_result(self, s)
                if self.mode == "ai" and self.settings["auto_next"] and self.overlay is None:
                    left = max(0, int(AUTO_NEXT_SECONDS - self.result_t + 0.99))
                    fx.text(s, f"next map in {left}", (T.W // 2, T.H - 30), 14, T.MUTED, "medium", mono=True,
                            anchor="center")
            if self.state == "settings":
                O.draw_settings(self, s)
            elif self.overlay == "pause":
                O.draw_pause(self, s)
            elif self.overlay == "help":
                O.draw_help(self, s)
        if self.settings["show_fps"]:
            O.draw_fps(self, s)
        pygame.display.flip()

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
        screens.draw_pending(self, s)
        for e in self.effects:
            if self.view in getattr(e, "views", VIEWS):
                if isinstance(e, fx.Flash):
                    continue
                e.draw(s)
        if self.phase == "think" and not self._ready() and self.worker.is_alive():
            screens.draw_thinking(self, s)

        draw_top(s, m, self.view, self.speed, self.paused, self.mode_label, self.t)
        left = pygame.Rect(16, T.TOP_H + 12, T.SIDE_W - 16, T.H - T.TOP_H - T.BOTTOM_H - 24)
        right = pygame.Rect(T.W - T.SIDE_W, T.TOP_H + 12, T.SIDE_W - 16, left.h)
        draw_red_panel(s, left, m, self.view, self.mode == "red", self._red_help())
        draw_blue_panel(s, right, m, self.view, self.mode == "blue", self._blue_help())
        draw_bottom(s, self._log_lines(), self._controls(), self.t)
        for e in self.effects:
            if isinstance(e, fx.Flash) and self.view in getattr(e, "views", VIEWS):
                e.draw(s)

        # hover info
        if (self.settings["tooltips"] and self.overlay is None and self.state == "match"
                and self.board.rect.collidepoint(mouse)):
            visible = None if self.view != "red" else set(g.red_known) | {m.net.database}
            u = self.board.node_at(mouse, visible)
            if u is not None:
                O.draw_tooltip(self, s, u, mouse)

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
                "and decoys give you away.",
                "",
                "H: all controls   Esc: pause"]

    def _blue_help(self):
        if self.mode != "blue":
            return None
        ap = self._human_blue_ap()
        lines = [(f"Action points left: {ap} / {C.BLUE_AP}", T.INK)]
        keys = {"monitor": "Q", "patch": "W", "decoy": "E", "isolate": "A", "restore": "D"}
        for tool in TOOLS:
            sel = tool == self.human_tool
            cost = C.COST[tool]
            lines.append((f"{'>' if sel else ' '} {keys[tool]}  {tool.title():8s} cost {cost}",
                          T.BLUE if sel else T.INK_2))
        lines.append(("", T.TEXT))
        lines.append(("Click a node to use the tool.", T.TEXT))
        end = "Enter: end turn" if self.settings["confirm_turn"] else "turn ends at 0 AP"
        lines.append((f"Backspace: undo   {end}", T.TEXT))
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
                    ("R", "restart map"), ("T", "theme"), ("H", "all controls"), ("ESC", "pause menu")]
        return [("R", "restart map"), ("T", "theme"), ("H", "all controls"), ("ESC", "pause menu")]

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
        self.settings.save()
        pygame.quit()
