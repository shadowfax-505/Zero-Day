"""Online lobby: host a game or join one, either directly on the same network
(or by IP) or through the relay server with a four-letter room code.

Rows are picked with Up/Down or the mouse; Left/Right flips a choice; text
fields take typing while they are selected. Games announced on the LAN (or
waiting on the relay server) show up on the right and join with one click.
The browser version can only use the relay, so it starts there and hides the
direct options.
"""

import json
import os
import random
import socket
import threading
import time

import pygame

from net.peer import DEFAULT_PORT, Beacon, Peer, Scanner, local_ip
from ui import device
from net.relay import WEB, RelayPeer, default_relay_url, normalise_url, relay_override
from net.session import Session
from ui import theme as T     # rebound to the active skin's theme in Lobby.draw()

fx = None                     # rebound to an _Ink for the active skin in Lobby.draw()

class _Ink:
    """The drawing calls the lobby needs, on top of either skin's fx module."""

    def __init__(self, sk):
        self.f, self.paper = sk.fx, sk.name == "paper"

    def text(self, surf, s, pos, size=14, color=None, weight="regular", mono=False, anchor="topleft", display=False):
        if self.paper:
            return self.f.text(surf, s, pos, size, color, weight, mono=mono, anchor=anchor, display=display)
        if display and weight == "bold":
            weight = "black"
        return self.f.text(surf, s, pos, size, color, weight, mono=mono, anchor=anchor)

    def spaced(self, surf, s, pos, size, color, weight="semibold", spacing=2, anchor="topleft"):
        return self.f.spaced(surf, s, pos, size, color, weight, spacing, anchor)

    @staticmethod
    def hrule(surf, x0, x1, y, color=None, width=1):
        pygame.draw.line(surf, color or T.RULE, (x0, y), (x1, y), width)


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


class _NoScanner:
    """The browser can't listen for LAN broadcasts."""
    ok = False
    stop = False

    @staticmethod
    def games():
        return []


class Lobby:
    LAN_ROWS = ["name", "side", "player", "via", "host", "ip", "back"]
    RELAY_ROWS = ["name", "side", "player", "via", "server", "rhost", "code", "back"]
    LIST_EVERY = 2.0             # seconds between refreshes of the relay's open-games list

    def __init__(self, seed):
        p = _load_prefs()
        self.name = p.get("name") or f"Player{random.randrange(10, 99)}"
        self.side = p.get("side", "red")
        self.local_ai = bool(p.get("local_ai", False))
        self.ip = p.get("ip", "")
        self.port = int(p.get("port", DEFAULT_PORT))
        self.via = "relay" if WEB else p.get("via", "lan")
        self.server = relay_override() or p.get("server") or default_relay_url()
        self.code = ""
        self.seed = seed
        self.sel = self.ROWS.index("rhost" if self.via == "relay" else "host")
        self.state = "setup"         # setup | hosting | joining
        self.status = ""
        self.status_col = "muted"
        self.session = None
        self.peer = None
        self.beacon = None
        self.relay = None            # RelayPeer while the relay is in use
        self._relay_want = None      # ("create",) or ("join", code) to send once the relay connects
        self._list_t = 0.0
        self.scanner = _NoScanner() if WEB else Scanner()
        self.my_ip = "" if WEB else local_ip()
        self._join_result = None
        if self.via == "relay":
            self._connect_relay()

    @property
    def ROWS(self):
        rows = self.RELAY_ROWS if self.via == "relay" else self.LAN_ROWS
        return [r for r in rows if not (WEB and r == "via")]

    # -- lifecycle --------------------------------------------------------------------
    def _prefs(self):
        _save_prefs({"name": self.name, "side": self.side, "local_ai": self.local_ai, "ip": self.ip,
                     "port": self.port, "via": self.via, "server": self.server})

    def close(self, keep_session=False):
        self.scanner.stop = True
        if self.beacon:
            self.beacon.stop = True
        if not keep_session:
            if self.session:
                self.session.close()
            elif self.peer:
                self.peer.close()
        if self.relay is not None and not (keep_session and self.peer is self.relay):
            self.relay.close()
        self.session = self.peer = self.beacon = self.relay = None

    def _cancel(self):
        if self.beacon:
            self.beacon.stop = True
        if self.peer is self.relay and self.relay is not None:
            # leave the room but keep the connection to the server for the games list
            if self.session:
                self.session.closed = True
            if self.relay.paired:
                self.relay.close()
                self.relay = None
            else:
                self.relay.leave()
        elif self.session:
            self.session.close()
        elif self.peer:
            self.peer.close()
        self.session = self.peer = self.beacon = None
        self._relay_want = None
        self.state = "setup"

    # -- relay ------------------------------------------------------------------------
    def _connect_relay(self):
        if self.relay is not None and not self.relay.closed and self.relay.url == normalise_url(self.server):
            return
        if self.relay is not None:
            self.relay.close()
        try:
            self.relay = RelayPeer(self.server)
        except Exception as e:  # noqa: BLE001 - e.g. no WebSocket support at all
            self.relay = None
            self._error(f"Could not open a connection to the server: {e}")
            return
        self._list_t = 0.0

    def _relay_host(self):
        self._prefs()
        self._connect_relay()
        if self.relay is None:
            return
        self._relay_want = ("create",)
        self.peer = self.relay
        self.state = "hosting"
        self.status = ""

    def _relay_join(self, code):
        code = code.strip().upper()
        if len(code) != 4:
            self._error("Type the four-letter code shown on the host's screen.")
            return
        self._prefs()
        self._connect_relay()
        if self.relay is None:
            return
        self._relay_want = ("join", code)
        self.peer = self.relay
        self.state = "joining"
        self.status = f"Joining game {code}..."
        self.status_col = "muted"

    def _relay_update(self):
        r = self.relay
        if r is None:
            return
        r.update()
        if r.closed:
            why = r.error or "Lost the connection to the server."
            self.relay = None
            if self.state != "setup":
                self._cancel()
            self._error(why)
            return
        if not r.connected:
            return
        if self._relay_want:
            want, self._relay_want = self._relay_want, None
            if want[0] == "create":
                r.create(self.name, self.side)
            else:
                r.join(want[1])
        if r.notices:
            why = r.notices.pop(0)
            if self.state != "setup":
                self.state = "setup"
                self.peer = None
            self._error(why)
        if self.state == "setup" and time.time() - self._list_t > self.LIST_EVERY:
            self._list_t = time.time()
            r.list_rooms()

    def server_status(self):
        r = self.relay
        if r is None:
            return "not connected", "muted"
        if r.connected:
            return "connected", "ok"
        if r.connecting:
            wait = time.time() - r.started
            return ("waking the server up (up to a minute)..." if wait > 4 else "connecting..."), "muted"
        return "not connected", "muted"

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
        self.status_col = "muted"
        self._join_result = None

        def work():
            try:
                self._join_result = Peer.join(ip, port, timeout=4.0)
            except (OSError, socket.timeout) as e:
                self._join_result = f"Could not reach {ip}:{port} ({getattr(e, 'strerror', None) or e})."

        threading.Thread(target=work, daemon=True).start()

    def _error(self, msg):
        self.status, self.status_col = msg, "red"

    def update(self):
        """Returns a ready Session once a match can begin."""
        if self.via == "relay" or self.relay is not None:
            self._relay_update()
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
        if self.state == "joining" and self.session is None and self.peer is not None \
                and self.peer is self.relay and self.relay.accepted():
            self.session = Session(self.peer, "client", self.name, local_ai=self.local_ai)
            self.status = "Joined. Waiting for the host to start..."
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
        if self.via == "relay":
            games = self.relay.rooms if self.relay is not None and self.relay.connected else []
            return self.ROWS + [("room", g) for g in games]
        return self.ROWS + [("game", g) for g in self.scanner.games()]

    def handle(self, ev):
        """Returns 'back' to leave the lobby, otherwise None."""
        if self.state != "setup":
            tapped = (ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1 and self.CANCEL.collidepoint(ev.pos))
            if (ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE) or tapped:
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
            elif k in (pygame.K_LEFT, pygame.K_RIGHT) and row in ("side", "player", "via"):
                self._flip(row)
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                return self._activate(row)
            elif row in ("name", "ip", "server", "code"):
                self._type(row, ev)
            if k == pygame.K_v and ev.mod & (pygame.KMOD_CTRL | pygame.KMOD_META) and row in ("ip", "server", "code"):
                self._paste(row)
        elif ev.type == pygame.MOUSEMOTION:
            for i, r in enumerate(self._row_rects(len(rows))):
                if r.collidepoint(ev.pos):
                    self.sel = i
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for i, r in enumerate(self._row_rects(len(rows))):
                if r.collidepoint(ev.pos):
                    self.sel = i
                    row = rows[i]
                    if row in ("side", "player", "via"):
                        self._flip(row)
                    elif row in self.ASK and device.WEB:
                        return self._ask(row)
                    elif row not in ("name", "server") and not (row == "code" and len(self.code) != 4):
                        return self._activate(row)
        return None

    def _flip(self, row):
        if row == "side":
            self.side = "blue" if self.side == "red" else "red"
        elif row == "via":
            self.via = "lan" if self.via == "relay" else "relay"
            self.status = ""
            if self.via == "relay":
                self._connect_relay()
            elif self.relay is not None:
                self.relay.close()
                self.relay = None
            self._prefs()
        else:
            self.local_ai = not self.local_ai

    def _activate(self, row):
        if row == "back":
            return "back"
        if row == "host":
            self._host()
        elif row == "ip":
            self._join(self.ip, self.port)
        elif row == "rhost":
            self._relay_host()
        elif row == "code":
            self._relay_join(self.code)
        elif row == "server":
            self._prefs()
            self._connect_relay()
        elif row in ("side", "player", "via"):
            self._flip(row)
        elif isinstance(row, tuple) and row[0] == "room":
            self._relay_join(row[1][0])
        elif isinstance(row, tuple):
            ip, port, _, _ = row[1]
            self._join(ip, port)
        return None

    def _paste(self, row):
        try:
            if not pygame.scrap.get_init():
                pygame.scrap.init()
            text = pygame.scrap.get_text() or ""
        except (pygame.error, AttributeError, NotImplementedError):
            return
        text = text.strip().splitlines()[0] if text.strip() else ""
        if row == "ip":
            self.ip = text[:40]
        elif row == "server":
            self.server = text[:80]
        else:
            self.code = "".join(c for c in text.upper() if c.isalpha())[:4]

    ASK = {"name": "Your name", "ip": "The host's IP address", "server": "Relay server address",
           "code": "The four-letter game code"}

    def _ask(self, row):
        """Browser (phones have no keyboard for the game): ask with the page's own text box, then go."""
        cur = {"name": self.name, "ip": self.ip, "server": self.server, "code": self.code}[row]
        text = device.ask_text(self.ASK[row], cur)
        if text is None:
            return None
        cur = ""
        for ch in text:
            cur = self._add_char(row, cur, ch)
        self._set_field(row, cur)
        if row == "name":
            self._prefs()
        elif row == "server" or (row == "ip" and cur) or (row == "code" and len(cur) == 4):
            return self._activate(row)
        return None

    @staticmethod
    def _add_char(row, cur, ch):
        limit = {"name": 16, "ip": 40, "server": 80, "code": 4}[row]
        if row == "name":
            ok = ch.isalnum() or ch in " _-"
        elif row == "ip":
            ok = ch in "0123456789.:abcdefghijklmnopqrstuvwxyz-"
        elif row == "server":
            ok = ch.isalnum() or ch in ".:/-_?=&%"
        else:
            ch = ch.upper()
            ok = ch.isalpha()
        return cur + ch if ok and len(cur) < limit else cur

    def _type(self, row, ev):
        cur = {"name": self.name, "ip": self.ip, "server": self.server, "code": self.code}[row]
        if ev.key == pygame.K_BACKSPACE:
            cur = cur[:-1]
        elif ev.unicode and ev.unicode.isprintable() and not ev.mod & (pygame.KMOD_CTRL | pygame.KMOD_META):
            cur = self._add_char(row, cur, ev.unicode)
        self._set_field(row, cur)

    def _set_field(self, row, cur):
        if row == "name":
            self.name = cur
        elif row == "ip":
            self.ip = cur
        elif row == "server":
            self.server = cur
        else:
            self.code = cur

    # -- drawing --------------------------------------------------------------------------
    X0 = 110
    CANCEL = pygame.Rect(110, 720, 240, 52)          # shown while hosting / joining, for touch screens

    def _row_rects(self, n):
        rects = [pygame.Rect(self.X0, 300 + i * 56, 620, 48) for i in range(len(self.ROWS))]
        for j in range(n - len(self.ROWS)):
            rects.append(pygame.Rect(860, 300 + j * 56, 630, 48))
        return rects

    def draw(self, s, t, sk):
        global T, fx
        T, fx = sk.T, _Ink(sk)
        x0 = self.X0
        pygame.draw.rect(s, T.RED, (x0, 128, 14, 34))
        pygame.draw.rect(s, T.BLUE, (x0 + 17, 128, 14, 34))
        fx.spaced(s, "ZERO DAY  /  ONLINE", (x0 + 46, 145), 17, T.INK_2, "semibold", 2, anchor="midleft")
        fx.text(s, "PLAY ONLINE", (x0 - 4, 166), 96, T.INK, "bold", display=True)
        if self.state == "setup":
            self._draw_setup(s, t)
        else:
            self._draw_waiting(s, t)
            r = self.CANCEL
            pygame.draw.rect(s, T.PAPER, r)
            pygame.draw.rect(s, T.INK, r, 2)
            fx.spaced(s, "CANCEL", r.center, 20, T.INK, "bold", 2, anchor="center")
        fx.hrule(s, x0, T.W - 60, T.H - 52)
        hint = ("Up / Down: choose    Left / Right: change    Type to edit    Enter: go    Esc: back"
                if self.state == "setup" else "Esc: cancel")
        fx.text(s, hint, (T.W - 60, T.H - 30), 13, T.INK_3, "regular", mono=True, anchor="midright")
        if self.via == "relay":
            st, kind = self.server_status()
            fx.text(s, f"Server: {st}", (x0, T.H - 30), 14, T.BLUE if kind == "ok" else T.INK_2, "regular",
                    anchor="midleft")
        else:
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

        # games found on the network (or waiting on the relay server)
        gx = 860
        fx.spaced(s, "OPEN GAMES ON THE SERVER" if self.via == "relay" else "GAMES ON YOUR NETWORK", (gx, 262), 17,
                  T.INK, "bold", 2)
        fx.hrule(s, gx, gx + 630, 288, T.INK, 2)
        games = [r for r in rows if isinstance(r, tuple)]
        if not games and self.via == "relay":
            st, _ = self.server_status()
            if st == "connected":
                fx.text(s, "No one is waiting for an opponent right now.", (gx, 306), 16, T.INK_2, "regular")
            else:
                dots = "." * (1 + int(t * 2) % 3)
                fx.text(s, f"Server: {st.rstrip('.')}{dots}", (gx, 306), 16, T.INK_2, "regular")
            fx.text(s, "HOST A GAME gives you a four-letter code. Send it to your opponent;", (gx, 336), 14,
                    T.INK_3, "regular")
            fx.text(s, "they type it in JOIN BY CODE, or click your game when it shows up here.", (gx, 358), 14,
                    T.INK_3, "regular")
            fx.text(s, "Works between browsers and desktop copies, on any network.", (gx, 380), 14, T.INK_3,
                    "regular")
        elif not games:
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
            if row[0] == "room":
                code, name, side = row[1]
                where = f"code {code}"
            else:
                ip, port, name, side = row[1]
                where = f"{ip}:{port}"
            sel = i == self.sel
            if sel:
                pygame.draw.rect(s, T.PAPER_3, r)
            col = T.BLUE if side == "red" else T.RED   # you would play the other side
            pygame.draw.rect(s, col, (r.x, r.y, 5, r.h))
            fx.text(s, name, (r.x + 18, r.centery), 20, T.INK, "semibold", anchor="midleft")
            you = "BLUE" if side == "red" else "RED"
            fx.text(s, f"{where}   you play {you}", (r.right - 16, r.centery), 14, T.INK_2, "regular",
                    mono=True, anchor="midright")
            fx.hrule(s, r.x, r.right, r.bottom + 4, T.RULE)

        if self.status:
            col = T.RED if self.status_col == "red" else T.INK_2
            fx.text(s, self.status, (self.X0, 300 + len(self.ROWS) * 56 + 18), 15, col, "regular")

    def _row_text(self, row, sel, caret):
        if row == "name":
            return "YOUR NAME", self.name + (caret if sel else ""), T.INK
        if row == "side":
            return "SIDE WHEN HOSTING", f"< {'RED / INTRUDER' if self.side == 'red' else 'BLUE / DEFENDER'} >", \
                (T.RED if self.side == "red" else T.BLUE)
        if row == "player":
            return "WHO PLAYS IT", f"< {'MY AI' if self.local_ai else 'ME'} >", T.INK
        if row == "via":
            return "CONNECT", f"< {'THROUGH THE SERVER' if self.via == 'relay' else 'SAME NETWORK / IP'} >", T.INK
        if row == "host":
            return "HOST A GAME", f"port {self.port}", T.INK
        if row == "rhost":
            return "HOST A GAME", "get a code", T.INK
        if row == "server":
            shown = self.server + (caret if sel else "")
            if not sel and len(shown) > 34:
                shown = shown.split("://")[-1][:31] + "..."
            return "SERVER", shown[-40:], T.INK
        if row == "code":
            shown = self.code + (caret if sel else "")
            return "JOIN BY CODE", shown or "type code", T.INK
        if row == "ip":
            shown = self.ip + (caret if sel else "")
            return "JOIN BY IP", shown or "type IP", T.INK
        return "BACK", "", T.INK_2

    def _draw_waiting(self, s, t):
        x0 = self.X0
        y = 300
        dots = "." * (1 + int(t * 2) % 3)
        fx.hrule(s, x0, T.W - 60, y - 12, T.INK, 2)
        if self.state == "hosting" and self.via == "relay":
            col = T.RED if self.side == "red" else T.BLUE
            code = self.relay.code if self.relay is not None else None
            if code is None:
                st, _ = self.server_status()
                fx.spaced(s, f"OPENING A GAME{dots}", (x0, y + 10), 34, T.INK, "bold", 2)
                fx.text(s, f"Server: {st}", (x0, y + 80), 18, T.INK_2, "regular")
                fx.text(s, "A free server sleeps when nobody uses it; the first visit can take up to a minute.",
                        (x0, y + 106), 15, T.INK_3, "regular")
                return
            fx.spaced(s, f"WAITING FOR AN OPPONENT{dots}", (x0, y + 10), 34, T.INK, "bold", 2)
            fx.text(s, "Send your opponent this code. They open PLAY ONLINE, pick THROUGH THE SERVER",
                    (x0, y + 80), 18, T.INK_2, "regular")
            fx.text(s, "and type it in JOIN BY CODE (or click your game in their list).", (x0, y + 106), 18,
                    T.INK_2, "regular")
            box = pygame.Rect(x0, y + 150, 360, 110)
            pygame.draw.rect(s, T.PAPER, box)
            pygame.draw.rect(s, T.INK, box, 2)
            fx.text(s, " ".join(code), (box.centerx, box.centery), 64, T.INK, "semibold", mono=True,
                    anchor="center")
            fx.spaced(s, f"YOU PLAY {'RED' if self.side == 'red' else 'BLUE'}"
                      + ("  (YOUR AI)" if self.local_ai else ""), (x0, y + 290), 20, col, "bold", 2)
            fx.text(s, f"Map {self.seed}.", (x0, y + 330), 14, T.INK_3, "regular")
        elif self.state == "hosting":
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
