"""TCP link between two players, plus LAN discovery.

Messages are one JSON object per line. A background thread reads the socket and
puts messages on a queue, so the game loop never blocks on the network.

    host:  p = Peer.host(port); ... p.accepted() -> True once someone joins
    join:  p = Peer.join(ip, port)
    both:  p.send({...}); for msg in p.poll(): ...
"""

import hashlib
import json
import queue
import socket
import threading
import time

PROTOCOL = 2
DEFAULT_PORT = 5150
BEACON_PORT = 5151          # UDP: hosts announce themselves here once a second


def local_ip():
    """Best guess at this machine's LAN address (no packet is actually sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Peer:
    def __init__(self):
        self.sock = None
        self.listener = None
        self.inbox = queue.Queue()
        self.closed = False
        self.error = None
        self._wlock = threading.Lock()

    # -- set up -----------------------------------------------------------------
    @classmethod
    def host(cls, port=DEFAULT_PORT):
        p = cls()
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("", port))
        ls.listen(1)
        ls.settimeout(0.2)
        p.listener = ls
        threading.Thread(target=p._accept_loop, daemon=True).start()
        return p

    @classmethod
    def join(cls, ip, port=DEFAULT_PORT, timeout=5.0):
        p = cls()
        s = socket.create_connection((ip, port), timeout=timeout)
        p._attach(s)
        return p

    def _accept_loop(self):
        while not self.closed and self.sock is None:
            try:
                s, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self._attach(s)
        try:
            self.listener.close()
        except OSError:
            pass

    def _attach(self, s):
        s.settimeout(None)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock = s
        threading.Thread(target=self._read_loop, daemon=True).start()

    def accepted(self):
        return self.sock is not None

    # -- traffic ----------------------------------------------------------------
    def _read_loop(self):
        buf = b""
        try:
            while not self.closed:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        try:
                            self.inbox.put(json.loads(line))
                        except ValueError:
                            pass
        except OSError as e:
            self.error = str(e)
        if not self.closed:
            self.inbox.put({"t": "_closed"})
        self.closed = True

    def send(self, msg):
        if self.sock is None or self.closed:
            return False
        data = (json.dumps(msg, separators=(",", ":")) + "\n").encode()
        try:
            with self._wlock:
                self.sock.sendall(data)
            return True
        except OSError as e:
            self.error = str(e)
            self.closed = True
            self.inbox.put({"t": "_closed"})
            return False

    def poll(self):
        out = []
        while True:
            try:
                out.append(self.inbox.get_nowait())
            except queue.Empty:
                return out

    def close(self):
        if self.sock is not None and not self.closed:
            self.send({"t": "bye"})
        self.closed = True
        for s in (self.sock, self.listener):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


class Beacon:
    """Host side: shout 'a Zero Day game is open here' on the LAN once a second."""

    def __init__(self, name, port, side):
        self.msg = json.dumps({"zd": PROTOCOL, "name": name, "port": port, "side": side}).encode()
        self.stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        while not self.stop:
            for addr in ("255.255.255.255", "127.0.0.1"):
                try:
                    s.sendto(self.msg, (addr, BEACON_PORT))
                except OSError:
                    pass
            time.sleep(1.0)
        s.close()


class Scanner:
    """Join side: listen for host beacons. games() -> [(ip, port, name, side)] seen in the last 3 s."""

    def __init__(self):
        self.found = {}
        self.stop = False
        self.ok = True
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            s.bind(("", BEACON_PORT))
        except OSError:
            self.ok = False
            return
        s.settimeout(0.3)
        while not self.stop:
            try:
                data, (ip, _) = s.recvfrom(1024)
                m = json.loads(data)
                if m.get("zd") == PROTOCOL:
                    if ip.startswith("127.") and any(not k[0].startswith("127.") and k[1] == m["port"]
                                                     for k in self.found):
                        continue
                    self.found[(ip, int(m["port"]))] = (str(m.get("name", "?"))[:20], m.get("side"), time.time())
            except (socket.timeout, ValueError, KeyError, TypeError):
                pass
            except OSError:
                break
        s.close()

    def games(self):
        now = time.time()
        return [(ip, port, name, side) for (ip, port), (name, side, t) in sorted(self.found.items())
                if now - t < 3.0]


def fingerprint(game):
    """Short hash of everything that must match on both machines."""
    state = (game.round, game.red_pos, sorted(game.red_held), game.weakness, sorted(game.decoys),
             sorted(game.isolated.items()), sorted(game.immune.items()),
             sorted(tuple(sorted(e)) for e in game.open_gates), game.rng.getstate())
    return hashlib.md5(repr(state).encode()).hexdigest()[:10]
