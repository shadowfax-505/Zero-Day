"""Online lobby: host a game or join one on the same network (or by IP).

Rows are picked with Up/Down or the mouse; Left/Right flips a choice; text
fields take typing while they are selected. Games announced on the LAN show up
on the right and join with one click.
"""

import json
import os
import random
import socket
import threading

import pygame

from net.peer import DEFAULT_PORT, Beacon, Peer, Scanner, local_ip
from net.session import Session
from ui import fx
from ui import theme as T

PREFS = os.path.join(os.path.expanduser("~"), ".zero-day-online.json")


def _load_prefs():
    try:
        with open(PREFS) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save_prefs(p):
    try:
        with open(PREFS, "w") as f:
            json.dump(p, f)
    except OSError:
        pass


class Lobby:
    ROWS = ["name", "side", "player", "host", "ip", "back"]

    def __init__(self, seed):
        p = _load_prefs()
        self.name = p.get("name") or f"Player{random.randrange(10, 99)}"
        self.side = p.get("side", "red")
        self.local_ai = bool(p.get("local_ai", False))
        self.ip = p.get("ip", "")
        self.port = int(p.get("port", DEFAULT_PORT))
        self.seed = seed
        self.sel = 3
        self.state = "setup"         # setup | hosting | joining
        self.status = ""
        self.status_col = T.INK_2
        self.session = None
        self.peer = None
        self.beacon = None
        self.scanner = Scanner()
        self.my_ip = local_ip()
        self._join_result = None

    # -- lifecycle --------------------------------------------------------------------
    def _prefs(self):
        _save_prefs({"name": self.name, "side": self.side, "local_ai": self.local_ai, "ip": self.ip,
                     "port": self.port})

    def close(self, keep_session=False):
        self.scanner.stop = True
        if self.beacon:
            self.beacon.stop = True
        if not keep_session:
            if self.session:
                self.session.close()
            elif self.peer:
                self.peer.close()
        self.session = self.peer = self.beacon = None

    def _cancel(self):
        if self.beacon:
            self.beacon.stop = True
        if self.session:
            self.session.close()
        elif self.peer:
            self.peer.close()
        self.session = self.peer = self.beacon = None
        self.state = "setup"

    def _host(self):
        self._prefs()
        try:
            self.peer = Peer.host(self.port)
        except OSError as e:
            self._error(f"Could not open port {self.port}: {e.strerror or e}")
            return
        self.beacon = Beacon(self.name, self.port, self.side)
        self.state = "hosting"
        self.status = ""

    def _join(self, ip, port):
        ip = ip.strip()
        if not ip:
            self._error("Type the host's IP address first (it is shown on their screen).")
            return
        if ":" in ip:
            ip, _, p = ip.partition(":")
            port = int(p) if p.isdigit() else port
        self._prefs()
        self.state = "joining"
        self.status = f"Connecting to {ip}:{port}..."
        self.status_col = T.INK_2
        self._join_result = None

        def work():
            try:
                self._join_result = Peer.join(ip, port, timeout=4.0)
            except (OSError, socket.timeout) as e:
                self._join_result = f"Could not reach {ip}:{port} ({getattr(e, 'strerror', None) or e})."

        threading.Thread(target=work, daemon=True).start()

    def _error(self, msg):
        self.status, self.status_col = msg, T.RED

    def update(self):
        """Returns a ready Session once a match can begin."""
        if self.state != "joining" and isinstance(self._join_result, Peer):
            self._join_result.close()            # a join that finished after it was cancelled
            self._join_result = None
        if self.state == "joining" and self.session is None and self._join_result is not None:
            res, self._join_result = self._join_result, None
            if isinstance(res, str):
                self.state = "setup"
                self._error(res)
                return None
            self.peer = res
            self.session = Session(self.peer, "client", self.name, local_ai=self.local_ai)
            self.status = "Connected. Waiting for the host to start..."
        if self.state == "hosting" and self.peer and self.peer.accepted() and self.session is None:
            self.session = Session(self.peer, "host", self.name, side=self.side, local_ai=self.local_ai)
        if self.session is None:
            return None
        for ev in self.session.poll():
            if ev[0] == "hello":
                if self.beacon:
                    self.beacon.stop = True
                self.session.start(self.seed)
                return self.session
            if ev[0] == "start":
                return self.session
            if ev[0] in ("closed", "error"):
                self._cancel()
                self._error(ev[1] if ev[0] == "error" else "The connection closed before the game started.")
        return None

    # -- input --------------------------------------------------------------------------
    def _rows(self):
        return self.ROWS + [("game", g) for g in self.scanner.games()]

    def handle(self, ev):
        """Returns 'back' to leave the lobby, otherwise None."""
        if self.state != "setup":
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                self._cancel()
                self.status = ""
            return None
        rows = self._rows()
        self.sel = min(self.sel, len(rows) - 1)
        if ev.type == pygame.KEYDOWN:
            row = rows[self.sel]
            k = ev.key
            if k == pygame.K_ESCAPE:
                return "back"
            if k in (pygame.K_UP, pygame.K_DOWN, pygame.K_TAB):
                step = -1 if k == pygame.K_UP or (k == pygame.K_TAB and ev.mod & pygame.KMOD_SHIFT) else 1
                self.sel = (self.sel + step) % len(rows)
            elif k in (pygame.K_LEFT, pygame.K_RIGHT) and row in ("side", "player"):
                self._flip(row)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._activate(row)
            elif row in ("name", "ip"):
                self._type(row, ev)
        elif ev.type == pygame.MOUSEMOTION:
            for i, r in enumerate(self._row_rects(len(rows))):
                if r.collidepoint(ev.pos):
                    self.sel = i
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, r in enumerate(self._row_rects(len(rows))):
                if r.collidepoint(ev.pos):
                    self.sel = i
                    row = rows[i]
                    if row in ("side", "player"):
                        self._flip(row)
                    elif row not in ("name",):
                        return self._activate(row)
        return None

    def _flip(self, row):
        if row == "side":
            self.side = "blue" if self.side == "red" else "red"
        else:
            self.local_ai = not self.local_ai

    def _activate(self, row):
        if row == "back":
            return "back"
        if row == "host":
            self._host()
        elif row == "ip":
            self._join(self.ip, self.port)
        elif row in ("side", "player"):
            self._flip(row)
        elif isinstance(row, tuple):
            ip, port, _, _ = row[1]
            self._join(ip, port)
        return None

    def _type(self, row, ev):
        cur = self.name if row == "name" else self.ip
        if ev.key == pygame.K_BACKSPACE:
            cur = cur[:-1]
        elif ev.unicode and ev.unicode.isprintable():
            ok = ev.unicode.isalnum() or ev.unicode in " _-" if row == "name" else ev.unicode in "0123456789.:abcdefghijklmnopqrstuvwxyz-"
            if ok and len(cur) < (16 if row == "name" else 40):
                cur += ev.unicode
        if row == "name":
            self.name = cur
        else:
            self.ip = cur

    # -- drawing --------------------------------------------------------------------------
    X0 = 110

    def _row_rects(self, n):
        rects = [pygame.Rect(self.X0, 300 + i * 56, 620, 48) for i in range(len(self.ROWS))]
        for j in range(n - len(self.ROWS)):
            rects.append(pygame.Rect(860, 300 + j * 56, 630, 48))
        return rects

    def draw(self, s, t):
        x0 = self.X0
        pygame.draw.rect(s, T.RED, (x0, 128, 14, 34))
        pygame.draw.rect(s, T.BLUE, (x0 + 17, 128, 14, 34))
        fx.spaced(s, "ZERO DAY  /  ONLINE", (x0 + 46, 145), 17, T.INK_2, "semibold", 2, anchor="midleft")
        fx.text(s, "PLAY ONLINE", (x0 - 4, 166), 96, T.INK, "bold", display=True)
        if self.state == "setup":
            self._draw_setup(s, t)
        else:
            self._draw_waiting(s, t)
        fx.hrule(s, x0, T.W - 60, T.H - 52)
        hint = ("Up / Down: choose    Left / Right: change    Type to edit    Enter: go    Esc: back"
                if self.state == "setup" else "Esc: cancel")
        fx.text(s, hint, (T.W - 60, T.H - 30), 13, T.INK_3, "regular", mono=True, anchor="midright")
        fx.text(s, f"This computer: {self.my_ip}", (x0, T.H - 30), 14, T.INK_2, "regular", anchor="midleft")

    def _draw_setup(self, s, t):
        rows = self._rows()
        rects = self._row_rects(len(rows))
        fx.hrule(s, self.X0, self.X0 + 620, 288, T.INK, 2)
        caret = "_" if int(t * 2) % 2 == 0 else " "
        for i, (row, r) in enumerate(zip(rows, rects)):
            sel = i == self.sel
            if isinstance(row, tuple):
                continue
            label, value, col = self._row_text(row, sel, caret)
            if sel:
                pygame.draw.rect(s, T.PAPER_3, r)
                pygame.draw.rect(s, col, (r.x, r.y, 5, r.h))
            fx.spaced(s, label, (r.x + 18, r.centery + 1), 22, col, "bold", 2, anchor="midleft")
            if value:
                fx.text(s, value, (r.right - 16, r.centery), 17, T.INK if row in ("name", "ip") else col,
                        "medium", mono=True, anchor="midright")
            fx.hrule(s, r.x, r.right, r.bottom + 4, T.RULE)

        # games found on the network
        gx = 860
        fx.spaced(s, "GAMES ON YOUR NETWORK", (gx, 262), 17, T.INK, "bold", 2)
        fx.hrule(s, gx, gx + 630, 288, T.INK, 2)
        games = [r for r in rows if isinstance(r, tuple)]
        if not games:
            dots = "." * (1 + int(t * 2) % 3)
            fx.text(s, f"Looking for hosts{dots}", (gx, 306), 16, T.INK_2, "regular")
            fx.text(s, "When a friend on the same Wi-Fi hosts a game it appears here.", (gx, 336), 14, T.INK_3,
                    "regular")
            fx.text(s, "Not showing up? Type their IP in JOIN BY IP on the left.", (gx, 358), 14, T.INK_3,
                    "regular")
            fx.text(s, "Joining? The host picks the sides; you get the other one.", (gx, 380), 14, T.INK_3,
                    "regular")
            if not self.scanner.ok:
                fx.text(s, "(Network search is unavailable on this machine.)", (gx, 408), 13, T.INK_3, "regular")
        for i, row in enumerate(rows):
            if not isinstance(row, tuple):
                continue
            r = rects[i]
            ip, port, name, side = row[1]
            sel = i == self.sel
            if sel:
                pygame.draw.rect(s, T.PAPER_3, r)
            col = T.BLUE if side == "red" else T.RED   # you would play the other side
            pygame.draw.rect(s, col, (r.x, r.y, 5, r.h))
            fx.text(s, name, (r.x + 18, r.centery), 20, T.INK, "semibold", anchor="midleft")
            you = "BLUE" if side == "red" else "RED"
            fx.text(s, f"{ip}:{port}   you play {you}", (r.right - 16, r.centery), 14, T.INK_2, "regular",
                    mono=True, anchor="midright")
            fx.hrule(s, r.x, r.right, r.bottom + 4, T.RULE)

        if self.status:
            fx.text(s, self.status, (self.X0, 300 + len(self.ROWS) * 56 + 18), 15, self.status_col, "regular")

    def _row_text(self, row, sel, caret):
        if row == "name":
            return "YOUR NAME", self.name + (caret if sel else ""), T.INK
        if row == "side":
            return "SIDE WHEN HOSTING", f"< {'RED / INTRUDER' if self.side == 'red' else 'BLUE / DEFENDER'} >", \
                (T.RED if self.side == "red" else T.BLUE)
        if row == "player":
            return "WHO PLAYS IT", f"< {'MY AI' if self.local_ai else 'ME'} >", T.INK
        if row == "host":
            return "HOST A GAME", f"port {self.port}", T.INK
        if row == "ip":
            shown = self.ip + (caret if sel else "")
            return "JOIN BY IP", shown or "type IP", T.INK
        return "BACK", "", T.INK_2

    def _draw_waiting(self, s, t):
        x0 = self.X0
        y = 300
        dots = "." * (1 + int(t * 2) % 3)
        fx.hrule(s, x0, T.W - 60, y - 12, T.INK, 2)
        if self.state == "hosting":
            col = T.RED if self.side == "red" else T.BLUE
            fx.spaced(s, f"WAITING FOR AN OPPONENT{dots}", (x0, y + 10), 34, T.INK, "bold", 2)
            fx.text(s, "Ask your opponent to open PLAY ONLINE. Your game shows up on their screen if you are",
                    (x0, y + 80), 18, T.INK_2, "regular")
            fx.text(s, "on the same network. Otherwise they pick JOIN BY IP and type this address:",
                    (x0, y + 106), 18, T.INK_2, "regular")
            box = pygame.Rect(x0, y + 150, 620, 90)
            pygame.draw.rect(s, T.PAPER, box)
            pygame.draw.rect(s, T.INK, box, 2)
            fx.text(s, f"{self.my_ip}:{self.port}", (box.x + 24, box.centery), 46, T.INK, "semibold", mono=True,
                    anchor="midleft")
            fx.spaced(s, f"YOU PLAY {'RED' if self.side == 'red' else 'BLUE'}"
                      + ("  (YOUR AI)" if self.local_ai else ""), (x0, y + 270), 20, col, "bold", 2)
            fx.text(s, f"Map {self.seed}. Playing over the internet needs port {self.port} forwarded on your router,",
                    (x0, y + 310), 14, T.INK_3, "regular")
            fx.text(s, "or both players on the same virtual LAN (for example Tailscale or ZeroTier).",
                    (x0, y + 330), 14, T.INK_3, "regular")
        else:
            fx.spaced(s, f"JOINING{dots}", (x0, y + 10), 34, T.INK, "bold", 2)
            fx.text(s, self.status, (x0, y + 80), 18, T.INK_2, "regular")
