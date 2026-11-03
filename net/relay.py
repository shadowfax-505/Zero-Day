"""Online play through the relay server (server/relay.py), over WebSocket.

Browsers can't open raw TCP sockets or search the LAN, so the web version meets
its opponent through a small relay instead. Desktop copies can use the relay
too, which also lets a desktop player and a browser player play each other.

RelayPeer has the same surface as net.peer.Peer (send / poll / close /
accepted / closed / error), so net.session.Session runs on either one. It also
talks to the relay itself:

    r = RelayPeer(url)            # connects in the background
    r.create(name, side)          # host: r.code becomes the room code, accepted() once someone joins
    r.join("ABCD")                # guest: accepted() once the relay pairs us up
    r.list_rooms(); r.rooms       # open games waiting for a second player

Two transports:
  * in the browser (pygbag, sys.platform == "emscripten") the page's own
    WebSocket object is driven through a few lines of JavaScript;
  * on desktop a background thread runs a websockets client.
"""

import json
import os
from collections import deque
import sys
import threading
import time

from net.peer import PROTOCOL

WEB = sys.platform == "emscripten"

# Where the relay runs. Change this after deploying your own (see DEPLOY.md),
# or override it with the ZERO_DAY_RELAY environment variable, the
# "?relay=wss://..." page address in the browser, or the lobby's SERVER field.
DEFAULT_RELAY = "wss://zero-day-relay.onrender.com"


def relay_override():
    """A relay address given from outside: $ZERO_DAY_RELAY, or ?relay=... on the web page."""
    url = os.environ.get("ZERO_DAY_RELAY", "")
    if not url and WEB:
        try:
            import platform as _pf
            url = str(_pf.window.eval("new URLSearchParams(window.location.search).get('relay') || ''"))
        except Exception:  # noqa: BLE001
            url = ""
    return url


def default_relay_url():
    return relay_override() or DEFAULT_RELAY


def normalise_url(url):
    url = url.strip()
    if url.startswith("https://"):
        return "wss://" + url[len("https://"):]
    if url.startswith("http://"):
        return "ws://" + url[len("http://"):]
    if "://" not in url:
        local = url.startswith(("localhost", "127.", "192.168.", "10."))
        return ("ws://" if local else "wss://") + url
    return url


# -- transports --------------------------------------------------------------------------------------
class _ThreadSocket:
    """Desktop: websockets' sync client on a reader thread."""

    def __init__(self, url, inbox):
        self.inbox = inbox
        self.ws = None
        self.state = "connecting"          # connecting | open | closed
        self.error = None
        self._lock = threading.Lock()
        self._want_close = False
        threading.Thread(target=self._run, args=(url,), daemon=True).start()

    def _run(self, url):
        try:
            from websockets.sync.client import connect
        except ImportError:
            self.error = "Online play through the server needs the websockets package (pip install websockets)."
            self._closed()
            return
        try:
            # a free server that has gone to sleep can take most of a minute to wake up
            conn = connect(url, open_timeout=75, max_size=2 ** 16)
        except Exception as e:  # noqa: BLE001 - any failure means "could not reach the server"
            self.error = f"Could not reach the server ({e.__class__.__name__})."
            self._closed()
            return
        with conn as ws:
            self.ws = ws
            self.state = "open"
            if self._want_close:
                ws.close()
            try:
                while True:
                    self.inbox.append(ws.recv())
            except Exception:  # noqa: BLE001 - closed by either side
                pass
        self._closed()

    def _closed(self):
        if self.state != "closed":
            self.state = "closed"
            self.inbox.append(json.dumps({"t": "_closed", "why": self.error}))

    def send(self, text):
        if self.state != "open":
            return False
        try:
            with self._lock:
                self.ws.send(text)
            return True
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            return False

    def pump(self):
        pass

    def close(self):
        self._want_close = True
        self.state = "closed"
        if self.ws is not None:
            try:
                self.ws.close()
            except Exception:  # noqa: BLE001
                pass


_JS = r"""
(function(){
  if (window.zdnet) return;
  window.zdnet = {
    socks: {}, next: 1,
    open(url) {
      const id = this.next++;
      const s = {ws: null, inbox: [], out: [], state: 'connecting'};
      this.socks[id] = s;
      try { s.ws = new WebSocket(url); }
      catch (e) { s.state = 'closed'; s.inbox.push(JSON.stringify({t: '_closed', why: 'Bad server address.'})); return id; }
      s.ws.onopen = () => { s.state = 'open'; for (const m of s.out) s.ws.send(m); s.out = []; };
      s.ws.onmessage = (e) => { s.inbox.push(String(e.data)); };
      s.ws.onclose = () => {
        const why = s.state === 'connecting' ? 'Could not reach the server.' : null;
        s.state = 'closed'; s.inbox.push(JSON.stringify({t: '_closed', why: why}));
      };
      return id;
    },
    send(id, text) {
      const s = this.socks[id]; if (!s || s.state === 'closed') return false;
      if (s.state === 'open') s.ws.send(text); else s.out.push(text);
      return true;
    },
    take(id) { const s = this.socks[id]; if (!s) return '[]'; const a = s.inbox; s.inbox = []; return JSON.stringify(a); },
    state(id) { const s = this.socks[id]; return s ? s.state : 'closed'; },
    close(id) { const s = this.socks[id]; if (s && s.ws) { try { s.ws.close(); } catch (e) {} } delete this.socks[id]; }
  };
})();
"""


class _BrowserSocket:
    """Browser (pygbag): the page's WebSocket, polled once a frame."""

    def __init__(self, url, inbox):
        import platform as _pf          # pygbag's bridge to the page's JavaScript
        self.win = _pf.window
        self.win.eval(_JS)
        self.inbox = inbox
        self.error = None
        self.id = int(self.win.eval(f"zdnet.open({json.dumps(url)})"))

    @property
    def state(self):
        return str(self.win.eval(f"zdnet.state({self.id})"))

    def send(self, text):
        return bool(self.win.eval(f"zdnet.send({self.id}, {json.dumps(text)})"))

    def pump(self):
        for raw in json.loads(str(self.win.eval(f"zdnet.take({self.id})"))):
            self.inbox.append(raw)

    def close(self):
        self.win.eval(f"zdnet.close({self.id})")


# -- the peer -------------------------------------------------------------------------------------------
class RelayPeer:
    """Peer-compatible link through the relay."""

    def __init__(self, url):
        self.url = normalise_url(url)
        self.inbox = deque()          # deque, not queue.Queue: the browser's Python has no working locks
        self.closed = False
        self.error = None
        self.code = None              # room code once hosting (or joined)
        self.paired = False
        self.rooms = []               # [(code, name, side)] open games, from list_rooms()
        self.rooms_t = None
        self.host_name = None         # guest: the host's name, from the relay
        self.started = time.time()
        self.held = []                # game messages waiting for poll()
        self.notices = []             # error replies from the relay, for the lobby to show
        sock_cls = _BrowserSocket if WEB else _ThreadSocket
        self.sock = sock_cls(self.url, self.inbox)

    # -- relay requests ----------------------------------------------------------------
    @property
    def connected(self):
        return self.sock.state == "open"

    @property
    def connecting(self):
        return self.sock.state == "connecting"

    def _raw(self, msg):
        return self.sock.send(json.dumps(msg, separators=(",", ":")))

    def create(self, name, side):
        self.code, self.paired = None, False
        return self._raw({"t": "_create", "name": name, "side": side, "v": PROTOCOL})

    def join(self, code):
        self.code, self.paired = None, False
        return self._raw({"t": "_join", "code": code.strip().upper()})

    def list_rooms(self):
        return self._raw({"t": "_list"})

    def leave(self):
        self.code, self.paired = None, False
        return self._raw({"t": "_leave"})

    # -- Peer interface ----------------------------------------------------------------
    def accepted(self):
        return self.paired

    def send(self, msg):
        if self.closed or not self.paired:
            return False
        if not self._raw(msg):
            self.error = self.error or getattr(self.sock, "error", None)
            return False
        return True

    def update(self):
        """Read what has arrived. Relay replies update this object; game messages are held for poll()."""
        self.sock.pump()
        while True:
            try:
                raw = self.inbox.popleft()
            except IndexError:
                return
            try:
                m = json.loads(raw)
                t = m.get("t")
            except (ValueError, AttributeError):
                continue
            if t == "_room":
                self.code = m.get("code")
            elif t == "_peer":
                self.paired = True
            elif t == "_joined":
                self.code = m.get("code")
                self.host_name = m.get("name")
                self.paired = True
            elif t == "_rooms":
                self.rooms = [(r.get("code"), str(r.get("name", "?"))[:20], r.get("side"))
                              for r in m.get("rooms", []) if r.get("v") == PROTOCOL]
                self.rooms_t = time.time()
            elif t == "_err":
                self.notices.append(m.get("why") or "The server refused that.")
            elif t == "_closed":
                why = m.get("why") or getattr(self.sock, "error", None)
                if why:
                    self.error = why
                if not self.closed:
                    self.closed = True
                    self.held.append({"t": "_closed", "why": why})
            else:
                self.held.append(m)

    def poll(self):
        """Game messages (and a final {"t": "_closed"}) for net.session.Session."""
        self.update()
        out, self.held = self.held, []
        return out

    def close(self):
        if not self.closed:
            if self.paired:
                self._raw({"t": "bye"})
            self.closed = True
        self.sock.close()
