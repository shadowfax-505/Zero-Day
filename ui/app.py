"""Pygame application: main menu, settings, match screen (AI vs AI or Human vs
AI), pause/help overlays and the result screen. AI moves are computed on a
worker thread so the board keeps animating while the agents think.

The look comes from a skin (ui/skins.py): 'paper' by default, or 'dark' (the
original neon look). Switching skin rebinds the module names below
(T, fx, Board, draw_top, ...), so the rest of this file never needs to know
which one is active."""

import asyncio
import os
import random
import sys
import threading
import time

import pygame

from agents.blue.agent import BlueAI
from agents.human import HumanRed, HumanBlue
from agents.red.agent import RedAI
from engine import config as C
from engine.mapgen import generate
from engine.match import Match
from net.session import OTHER, RemotePlayer
from ui import overlays as O
from ui.online import Lobby
from ui import skins
from ui.settings import Settings
from ui.sound import Sound

WEB = sys.platform == "emscripten"     # running in the browser (pygbag): no threads there
SPEEDS = [0.5, 1, 2, 4]
TOOLS = ["monitor", "patch", "decoy", "isolate", "restore"]
AUTO_NEXT_SECONDS = 6.0

# rebound by _use_skin()
T = fx = Board = VIEWS = screens = None
draw_top = draw_red_panel = draw_blue_panel = draw_bottom = act_text = blue_act_text = view_rects = None
control_rects = None

# keycaps in the bottom bar -> the key a click on them presses
KEYCAP_KEYS = {"SPACE": pygame.K_SPACE, "N": pygame.K_n, "V": pygame.K_v, "+ -": pygame.K_PLUS, "R": pygame.K_r,
               "T": pygame.K_t, "H": pygame.K_h, "ESC": pygame.K_ESCAPE, "C": pygame.K_c, "M": pygame.K_m}

VIEW_KEYS = {pygame.K_1: "red", pygame.K_2: "full", pygame.K_3: "blue",
             pygame.K_KP1: "red", pygame.K_KP2: "full", pygame.K_KP3: "blue"}


def _use_skin(name):
    global T, fx, Board, VIEWS, screens, draw_top, draw_red_panel, draw_blue_panel, draw_bottom, act_text, \
        blue_act_text, view_rects, control_rects
    sk = skins.load(name)
    T, fx, screens = sk.T, sk.fx, sk.screens
    Board, VIEWS = sk.board.Board, sk.board.VIEWS
    p = sk.panels
    draw_top, draw_red_panel, draw_blue_panel, draw_bottom = p.draw_top, p.draw_red_panel, p.draw_blue_panel, \
        p.draw_bottom
    act_text, blue_act_text, view_rects = p.act_text, p.blue_act_text, p.view_rects
    control_rects = p.control_rects
    return sk


class App:
    def __init__(self, mode=None, seed=None, speed=None, view=None, windowed=None, record=None, theme=None,
                 settings_path=None, online=None):
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
        self.lobby = None
        self.online = None          # net.session.Session while playing online
        self.online_note = None     # e.g. "Bob left the game."
        self.chat_text = None       # chat line being typed, or None
        self._build_skin_surfaces()
        if online is not None:
            self._open_lobby(online)
        elif mode:
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
        self._leave_online()
        net = self.match.net if (same_map and self.match) else generate(self.seed)
        red = HumanRed() if mode == "red" else RedAI()
        blue = HumanBlue() if mode == "blue" else BlueAI()
        label = {"ai": "AI VS AI", "red": "YOU (RED) VS BLUE AI", "blue": "RED AI VS YOU (BLUE)"}[mode]
        self._begin(mode, red, blue, net, label)
        self.view = {"red": "red", "blue": "blue"}.get(mode, self.default_view)

    def start_online_match(self):
        """Both machines call this with the same seed; only the moves travel after that."""
        o = self.online
        self.seed = o.seed
        side = o.side
        if o.local_ai:
            local = RedAI() if side == "red" else BlueAI()
        else:
            local = HumanRed() if side == "red" else HumanBlue()
        remote = RemotePlayer(OTHER[side], o.remote_name)
        red, blue = (local, remote) if side == "red" else (remote, local)
        who = "YOUR AI" if o.local_ai else "YOU"
        label = f"ONLINE  /  {who} ({side.upper()}) VS {o.remote_name.upper()}"
        self.online_note = None
        self.chat_text = None
        self._asked_rematch = False
        self._desync_logged = False
        self._begin("netai" if o.local_ai else side, red, blue, generate(o.seed), label)
        self.view = side            # fog of war: you only ever see your own side's view
        self.log.append((1, "muted", f"Online match on map {o.seed} against {o.remote_name}. Press C to chat."))

    def _begin(self, mode, red, blue, net, label):
        self.mode = mode
        self.match = Match(red, blue, net=net)
        self.board = Board(net)
        self._apply_labels()
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
        self.mode_label = label
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
            if _is_ai(m.blue):
                self.pending_blue = m.ask_blue()
            if _is_ai(m.red):
                self.pending_red = m.ask_red()

        if WEB:
            steps = []
            if _is_ai(m.blue):
                steps.append(lambda: setattr(self, "pending_blue", m.ask_blue()))
            if _is_ai(m.red):
                steps.append(lambda: setattr(self, "pending_red", m.ask_red()))
            self.worker = _StepWorker(steps)
        else:
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
        col = {"text": T.TEXT, "blue": T.BLUE, "gold": T.GOLD, "muted": T.INK_2, "red": T.RED}
        return [(r, col[k], s) for r, k, s in self.log]

    # -- online ---------------------------------------------------------------------------
    def _open_lobby(self, opts=None):
        """opts (from the command line): {'host': bool, 'join': ip, 'port', 'side', 'ai', 'name'}"""
        self.lobby = Lobby(self.seed)
        self.state = "lobby"
        if not opts:
            return
        lb = self.lobby
        if opts.get("port"):
            lb.port = opts["port"]
        if opts.get("side"):
            lb.side = opts["side"]
        if opts.get("name"):
            lb.name = opts["name"][:16]
        lb.local_ai = bool(opts.get("ai"))
        if opts.get("join"):
            lb.ip = opts["join"]
            lb._join(lb.ip, lb.port)
        elif opts.get("host"):
            lb._host()

    def _leave_online(self):
        if self.online:
            self.online.close()
        self.online = None
        self.online_note = None
        self.chat_text = None

    def _online_restart(self, new_map):
        """Host: start the next match (same map or a fresh one) on both machines."""
        if new_map:
            self.seed = random.randrange(1, 100000)
        self.online.start(self.seed)
        self.start_online_match()

    def _online_rematch(self, new_map):
        """R / N (or the pause menu) while online: the host restarts, the joiner asks the host."""
        if self.online.closed:
            return
        if self.online.role == "host":
            self._online_restart(new_map)
        elif not getattr(self, "_asked_rematch", False):
            self._asked_rematch = True
            self.online.request_rematch(new_map)
            self.log.append((self.match.game.round, "muted", f"Asked {self.online.remote_name} for a rematch."))

    def _online_tick(self):
        o = self.online
        for ev in o.poll():
            if ev[0] == "start":
                self.start_online_match()
            elif ev[0] == "rematch":
                self._online_restart(ev[1])
            elif ev[0] == "chat":
                self.log.append((self.match.game.round, "text", f"{ev[1]}: {ev[2]}"))
                self.sound.play("click")
            elif ev[0] in ("closed", "error"):
                self.online_note = ev[1]
                self.log.append((self.match.game.round, "red", ev[1]))
        if self.state not in ("match", "settings") or self.phase != "think" or o.closed:
            return
        g = self.match.game
        mine = self.pending_red if o.side == "red" else self.pending_blue
        if mine is not None and o.sent_round != g.round and self._ready_local():
            o.send_move(g, mine)
        theirs = o.remote_move(g.round)
        if theirs is not None:
            if o.side == "red" and self.pending_blue is None:
                self.pending_blue = theirs
            elif o.side == "blue" and self.pending_red is None:
                self.pending_red = theirs
        if o.desync_round is not None and not self._desync_logged:
            self._desync_logged = True
            self.log.append((g.round, "red", "Warning: the two games went out of sync. Press M and start again."))

    def _ready_local(self):
        return self.worker is None or not self.worker.is_alive()

    def _remote_waiting(self):
        """True while we still wait for the opponent's move this round."""
        return (self.pending_blue if self.online.side == "red" else self.pending_red) is None

    def _local_moved(self):
        return (self.pending_red if self.online.side == "red" else self.pending_blue) is not None

    def _handle_chat(self, ev):
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE:
            self.chat_text = None
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            msg = self.chat_text.strip()
            if msg and self.online and not self.online.closed:
                self.online.chat(msg)
                self.log.append((self.match.game.round, "text", f"{self.online.name}: {msg}"))
            self.chat_text = None
        elif ev.key == pygame.K_BACKSPACE:
            self.chat_text = self.chat_text[:-1]
        elif ev.unicode and ev.unicode.isprintable() and len(self.chat_text) < 80:
            self.chat_text += ev.unicode

    def _draw_online_thinking(self, s):
        o = self.online
        if o.closed:
            return
        r = self.board.rect
        dots = "." * (1 + int(self.t * 3) % 3)
        name = o.remote_name
        col = T.INK_2
        if self.mode == "netai" and not self._local_moved():
            msg = f"Your AI is thinking{dots}"
        elif self._remote_waiting():
            msg = f"Waiting for {name}{dots}" if self._local_moved() else f"{name} is still deciding{dots}"
        else:
            msg = f"{name} has locked in a move. Your turn!"
            col = T.RED if o.side == "red" else T.BLUE
        fx.text(s, msg, (r.x + 14, r.bottom - 10), 13, col, "medium", mono=True, anchor="bottomleft")

    def _draw_online_overlay(self, s):
        """Result line, chat box, and a banner when the other player has gone."""
        o = self.online
        if self.state == "result" and self.overlay is None:
            mine = o.side
            g = self.match.game
            won = g.winner == mine
            if o.closed:
                keys = "M  menu"
            elif o.role == "client" and self._asked_rematch:
                keys = f"Asked {o.remote_name} for a rematch...   M  menu"
            elif o.role == "client":
                keys = "R / N  ask the host for a rematch   C  chat   M  menu"
            else:
                keys = "R  rematch on this map   N  new map   C  chat   M  menu"
            box = pygame.Rect(0, 0, 760, 48)
            box.center = (T.W // 2, T.H - 70)
            pygame.draw.rect(s, T.PAPER, box)
            pygame.draw.rect(s, T.RED if g.winner == "red" else T.BLUE, box, 2)
            fx.spaced(s, "YOU WIN" if won else "YOU LOSE", (box.x + 20, box.centery), 20,
                      T.RED if g.winner == "red" else T.BLUE, "bold", 2, anchor="midleft")
            fx.text(s, keys, (box.right - 16, box.centery), 13, T.INK_2, "medium", mono=True, anchor="midright")
        if self.chat_text is not None:
            box = pygame.Rect(T.SIDE_W + 16, T.H - T.BOTTOM_H - 58, T.W - 2 * T.SIDE_W - 32, 40)
            pygame.draw.rect(s, T.PAPER, box)
            pygame.draw.rect(s, T.INK, box, 2)
            caret = "_" if int(self.t * 2) % 2 == 0 else " "
            fx.spaced(s, "SAY", (box.x + 14, box.centery + 1), 16, T.INK_2, "bold", 2, anchor="midleft")
            fx.text(s, self.chat_text + caret, (box.x + 60, box.centery), 16, T.INK, "regular", anchor="midleft")
            fx.text(s, "Enter send   Esc cancel", (box.right - 12, box.centery), 12, T.INK_3, "regular",
                    mono=True, anchor="midright")
        if self.online_note:
            card = pygame.Rect(0, 0, 640, 120)
            card.center = (T.W // 2, T.TOP_H + 90)
            pygame.draw.rect(s, T.PAPER, card)
            pygame.draw.rect(s, T.INK, card, 2)
            pygame.draw.rect(s, T.RED, (card.x, card.y, card.w, 8))
            fx.spaced(s, "CONNECTION LOST", (card.x + 28, card.y + 26), 22, T.RED, "bold", 2)
            fx.text(s, self.online_note, (card.x + 28, card.y + 60), 16, T.INK, "regular")
            fx.text(s, "M  back to the menu", (card.x + 28, card.y + 88), 13, T.INK_2, "regular", mono=True)

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

    def _blue_refusal(self, tool, target):
        """Why this Blue action can't be added right now, or None if it can."""
        g, net = self.match.game, self.match.net
        cost = C.action_cost(tool, target, net.gateway)
        ap = self._human_blue_ap()
        if cost > ap:
            what = "sealing GW" if tool == "restore" and target == net.gateway else tool.title()
            return f"{what} needs {cost} AP, {ap} left"
        if (tool, target) in self.human_blue_acts:
            return "already chosen"
        if tool == "isolate" and any(k == "isolate" for k, _ in self.human_blue_acts):
            return "one isolate per turn"
        if not g.blue_can(tool, target):
            if tool == "isolate" and g.round < g.isolate_ready:
                return f"isolate recharging (round {g.isolate_ready})"
            if tool == "decoy" and len(g.decoys) >= C.MAX_DECOYS:
                return f"all {C.MAX_DECOYS} decoys placed"
            if tool == "patch" and target in g.patched:
                return "already patched"
            return "not allowed here"
        return None

    def _blue_can_do_anything(self):
        """True if some action is still affordable and legal this turn (else the turn may as well end)."""
        net = self.match.net
        for tool in TOOLS:
            targets = range(3) if tool == "monitor" else range(net.n)
            if any(self._blue_refusal(tool, t) is None for t in targets):
                return True
        return False

    def _human_blue_add(self, node):
        net = self.match.net
        tool = self.human_tool
        target = net.zone[node] if tool == "monitor" else node
        why = self._blue_refusal(tool, target)
        if why:
            self._fx(fx.FloatText(self.board.pts[node], why.upper(), T.INK_2, 11))
            self.sound.play("fail")
            return
        self.human_blue_acts.append((tool, target))
        self.sound.play("click")

    # Blue's clickable tool bar along the top of the board (works without the keyboard, e.g. in a browser)
    def _blue_bar_rects(self):
        r = self.board.rect
        names = TOOLS + ["end"]
        w, h, gap = 118, 34, 6
        x0 = r.centerx - (len(names) * w + (len(names) - 1) * gap) // 2
        return [(n, pygame.Rect(x0 + i * (w + gap), r.y + 8, w, h)) for i, n in enumerate(names)]

    def _blue_bar_click(self, pos):
        for name, rect in self._blue_bar_rects():
            if rect.collidepoint(pos):
                if name == "end":
                    self._human_blue_commit()
                else:
                    self.human_tool = name
                self.sound.play("click")
                return True
        return False

    def _draw_blue_bar(self, s):
        ap = self._human_blue_ap()
        mouse = pygame.mouse.get_pos()
        keys = {"monitor": "Q", "patch": "W", "decoy": "E", "isolate": "A", "restore": "D", "end": "ENTER"}
        stuck = not self._blue_can_do_anything()
        for name, r in self._blue_bar_rects():
            if name == "end":
                hot = stuck or ap == 0
                fill = T.BLUE if hot else T.PAPER
                pygame.draw.rect(s, fill, r)
                pygame.draw.rect(s, T.BLUE, r, 2)
                col = T.PAPER if hot else T.BLUE
                fx.text(s, f"END TURN  {ap} AP", (r.centerx, r.centery - 6), 13, col, "bold", anchor="center")
                fx.text(s, keys[name], (r.centerx, r.centery + 9), 10, col, "medium", mono=True, anchor="center")
                continue
            cost = C.COST[name]
            sel = name == self.human_tool
            afford = cost <= ap
            pygame.draw.rect(s, T.BLUE if sel else T.PAPER, r)
            pygame.draw.rect(s, T.BLUE if (sel or r.collidepoint(mouse)) else T.RULE, r, 1)
            col = T.PAPER if sel else (T.INK if afford else T.INK_3)
            fx.text(s, name.title(), (r.x + 10, r.centery - 6), 13, col, "semibold", anchor="midleft")
            fx.text(s, f"{keys[name]}  ·  {cost} AP", (r.x + 10, r.centery + 9), 10, col, "medium", mono=True,
                    anchor="midleft")
        if stuck:
            fx.text(s, "Nothing else fits this turn: press Enter or END TURN", (self.board.rect.centerx,
                    self.board.rect.bottom - 34), 13, T.BLUE, "semibold", anchor="center")

    def _human_blue_commit(self):
        self.pending_blue = list(self.human_blue_acts)
        self.match.blue_debug = {"actions": list(self.human_blue_acts)}

    # -- events ---------------------------------------------------------------------------
    def _set_view(self, v):
        if v != self.view:
            self.view = v
            self.sound.play("click")
            if WEB:                          # tools/web_smoke.py checks for this line in the browser console
                try:
                    import platform as _pf
                    _pf.window.console.log(f"view: {v}")
                except Exception:  # noqa: BLE001
                    pass

    def _can_switch_view(self):
        return self.mode == "ai" and not self.online

    def _click_target(self, pos):
        """What a left click at pos would press during a match: ("view", v), ("key", K_...) or None."""
        if self.state not in ("match", "result") or self.match is None or self.overlay or self.chat_text is not None:
            return None
        if self._can_switch_view():
            for v, r in view_rects().items():
                if r.inflate(4, 8).collidepoint(pos):
                    return "view", v
            if self.state == "match":
                left, right = self._side_rects()
                if self.view == "blue" and left.collidepoint(pos):      # Red's panel is hidden: show Red's view
                    return "view", "red"
                if self.view == "red" and right.collidepoint(pos):
                    return "view", "blue"
        if self.state == "match":
            for keycap, _, _, row in control_rects(self._controls()):
                if keycap in KEYCAP_KEYS and row.collidepoint(pos):
                    return "key", KEYCAP_KEYS[keycap]
        return None

    def _side_rects(self):
        left = pygame.Rect(16, T.TOP_H + 12, T.SIDE_W - 16, T.H - T.TOP_H - T.BOTTOM_H - 24)
        right = pygame.Rect(T.W - T.SIDE_W, T.TOP_H + 12, T.SIDE_W - 16, left.h)
        return left, right

    def _update_cursor(self):
        """Hand cursor over anything clickable, so it is obvious what can be clicked."""
        want = self.state in ("match", "result") and self._click_target(pygame.mouse.get_pos()) is not None
        if want != getattr(self, "_hand", False):
            self._hand = want
            try:
                pygame.mouse.set_cursor(pygame.SYSTEM_CURSOR_HAND if want else pygame.SYSTEM_CURSOR_ARROW)
            except Exception:  # noqa: BLE001  (no system cursors on some platforms)
                pass

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
        if self.state == "lobby":
            if self.lobby.handle(ev) == "back":
                self.lobby.close()
                self.lobby = None
                self.state = "menu"
            return True
        if self.state == "settings":
            return self._handle_settings(ev)
        if self.chat_text is not None:
            self._handle_chat(ev)
            return True
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
                self._leave_online()
                self.state = "menu"
                return True
            if k == pygame.K_h:
                self._help_from_pause = False
                self.overlay = "help"
                return True
            if k == pygame.K_t:
                self.set_theme("dark" if self.sk.name == "paper" else "paper")
                return True
            if self.online:
                if k == pygame.K_c:
                    self.chat_text = ""
                    return True
                if self.state == "result" and k in (pygame.K_r, pygame.K_n, pygame.K_RETURN):
                    self._online_rematch(k != pygame.K_r)
                    return True
                if k in (pygame.K_r, pygame.K_n):
                    return True
            if self.mode == "ai" and (k == pygame.K_v or k in VIEW_KEYS):
                self._set_view(VIEW_KEYS.get(k) or VIEWS[(VIEWS.index(self.view) + 1) % 3])
                return True
            if self.state == "result":
                if k == pygame.K_r:
                    self.start_match(self.mode, same_map=True)
                elif k in (pygame.K_n, pygame.K_RETURN):
                    self._new_map()
                return True
            if k in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
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
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            hit = self._click_target(ev.pos)
            if hit is not None:
                kind, what = hit
                if kind == "view":
                    self._set_view(what)
                    return True
                if what == pygame.K_PLUS and self.speed_i == len(SPEEDS) - 1:
                    self.speed_i = 0                   # clicking "+ -" cycles the speed round
                    return True
                return self.handle(pygame.event.Event(pygame.KEYDOWN, key=what, mod=0, unicode="", scancode=0))
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.state == "match" and self.phase == "think":
            if self.mode == "red" and self.pending_red is None:
                targets = self._human_red_targets()
                u = self.board.node_at(ev.pos, set(targets))
                if u is not None:
                    self.pending_red = targets[u]
                    self.sound.play("click")
            elif self.mode == "blue" and self.pending_blue is None:
                if self._blue_bar_click(ev.pos):
                    return True
                u = self.board.node_at(ev.pos)
                if u is not None:
                    self._human_blue_add(u)
        return True

    # menu
    def _menu_items(self):
        items = [("AI VS AI", "ai"), ("PLAY AS RED", "red"), ("PLAY AS BLUE", "blue"), ("PLAY ONLINE", "online"),
                 ("SETTINGS", "settings"), ("QUIT", "quit")]
        return items[:-1] if WEB else items          # a web page can't quit

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
                return WEB
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
        if what == "online":
            self._open_lobby()
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
        elif what in ("restart", "new") and self.online:
            self.overlay = None
            self._online_rematch(what == "new")
        elif what == "restart":
            self.start_match(self.mode, same_map=True)
        elif what == "new":
            self._new_map()
        elif what == "menu":
            self.overlay = None
            self._leave_online()
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
        if self.state == "lobby":
            sess = self.lobby.update()
            if sess:
                self.lobby.close(keep_session=True)
                self.lobby = None
                self.online = sess
                self.start_online_match()
            return
        if self.online:
            self._online_tick()             # keeps the link alive even while a menu is open
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
            if isinstance(self.worker, _StepWorker) and self.phase_t > 0:
                self.worker.step()            # browser: one agent per frame so the page stays responsive
            if (self.mode == "blue" and not self.settings["confirm_turn"] and self.pending_blue is None
                    and self.human_blue_acts and (self._human_blue_ap() == 0 or not self._blue_can_do_anything())):
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
        if self.state == "lobby":
            self.lobby.draw(s, self.t, self.sk)
        elif self.state == "menu" or (self.state == "settings" and self.settings_from == "menu"):
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
            if self.online:
                self._draw_online_overlay(s)
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
        if self.mode == "blue" and self.phase == "think" and self.pending_blue is None and self.state == "match":
            self._draw_blue_bar(s)
        for e in self.effects:
            if self.view in getattr(e, "views", VIEWS):
                if isinstance(e, fx.Flash):
                    continue
                e.draw(s)
        if self.phase == "think" and not self._ready() and self.online:
            self._draw_online_thinking(s)
        elif self.phase == "think" and not self._ready() and self.worker.is_alive():
            screens.draw_thinking(self, s)

        draw_top(s, m, self.view, self.speed, self.paused, self.mode_label, self.t)
        left, right = self._side_rects()
        sub = {}
        if self.online:
            o = self.online
            sub[o.side] = "Your AI on this computer" if o.local_ai else None
            sub[OTHER[o.side]] = f"{o.remote_name}, playing online"
        draw_red_panel(s, left, m, self.view, self.mode == "red", self._red_help(), subtitle=sub.get("red"),
                       can_switch=self._can_switch_view())
        draw_blue_panel(s, right, m, self.view, self.mode == "blue", self._blue_help(), subtitle=sub.get("blue"),
                        can_switch=self._can_switch_view())
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
        lines.append(("Pick a tool above the map, then click a node.", T.TEXT))
        end = "Enter: end turn" if self.settings["confirm_turn"] else "Enter / auto at 0 AP"
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
        if self.online:
            return [("C", "chat"), ("T", "theme"), ("H", "all controls"), ("ESC", "pause menu"), ("M", "leave game")]
        if self.mode == "ai":
            return [("SPACE", "play / pause"), ("N", "step one round"), ("V", "view (or 1 2 3, click)"), ("+ -", "speed"),
                    ("R", "restart map"), ("T", "theme"), ("H", "all controls"), ("ESC", "pause menu")]
        return [("R", "restart map"), ("T", "theme"), ("H", "all controls"), ("ESC", "pause menu")]

    # -- loop -----------------------------------------------------------------------------------
    def run(self):
        asyncio.run(self.run_async())

    async def run_async(self):
        """The game loop. Async so the browser build (pygbag) can hand control back to the page every frame."""
        running = True
        print("Zero Day running", "(browser)" if WEB else "")
        if WEB:
            try:
                import platform as _pf
                _pf.window.console.log("Zero Day running (browser)")
            except Exception:  # noqa: BLE001
                pass
        while running:
            dt = self.clock.tick(60) / 1000.0
            for ev in pygame.event.get():
                if not self.handle(ev):
                    running = False
            if self.record:
                dt = 1 / 30           # fixed step so the recording plays back at real speed
            self.update(dt)
            self.draw()
            self._update_cursor()
            if self.record:
                pygame.image.save(self.screen, os.path.join(self.record, f"frame_{self.frame:06d}.png"))
                self.frame += 1
            await asyncio.sleep(0)
        self.settings.save()
        self._leave_online()
        if self.lobby:
            self.lobby.close()
        pygame.quit()


class _StepWorker:
    """Stands in for the thinking thread in the browser, where threads can't run.
    step() runs one agent; is_alive() is True until all have run."""

    def __init__(self, steps):
        self.steps = list(steps)

    def step(self):
        if self.steps:
            self.steps.pop(0)()

    def is_alive(self):
        return bool(self.steps)


def _is_ai(agent):
    return not isinstance(agent, (HumanRed, HumanBlue, RemotePlayer))
