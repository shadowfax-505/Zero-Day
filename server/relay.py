"""Zero Day relay: lets two players meet online when they can't connect directly
(browser players, or friends on different networks).

It knows nothing about the game. A host opens a room and gets a four-letter
code; the other player joins with that code; from then on every message one
of them sends is passed to the other unchanged. The game itself still runs on
the two players' machines in lockstep, exactly like direct LAN play.

    pip install -r server/requirements.txt
    python server/relay.py                  # listens on $PORT (default 8765)

Messages are JSON text frames. Ones whose "t" starts with "_" talk to the relay:

    -> {"t":"_create", "name", "side", "v"}     <- {"t":"_room", "code"}
    -> {"t":"_join", "code"}                    <- {"t":"_joined", "name", "side"}  (host gets {"t":"_peer"})
    -> {"t":"_list"}                            <- {"t":"_rooms", "rooms":[{code,name,side,v}]}
    <- {"t":"_err", "why"}                      <- {"t":"_closed", "why"}   (the other player left)

Everything else is forwarded to the other player in the room.
"""

import asyncio
import http
import json
import logging
import os
import random
import string
import time

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

log = logging.getLogger("relay")

MAX_ROOMS = 500
MAX_MSG = 16 * 1024            # a move or chat line is well under 1 KB
ROOM_IDLE_SECONDS = 2 * 3600
CODE_CHARS = "".join(c for c in string.ascii_uppercase if c not in "IO")   # no I/O to confuse with 1/0


class Room:
    def __init__(self, code, host, name, side, version):
        self.code, self.host, self.name, self.side, self.version = code, host, name, side, version
        self.guest = None
        self.last = time.time()

    def other(self, ws):
        return self.guest if ws is self.host else self.host


rooms = {}                     # code -> Room
where = {}                     # websocket -> Room


def _new_code():
    for _ in range(1000):
        code = "".join(random.choices(CODE_CHARS, k=4))
        if code not in rooms:
            return code
    raise RuntimeError("no free room codes")


async def _send(ws, msg):
    if ws is None:
        return
    try:
        await ws.send(json.dumps(msg, separators=(",", ":")))
    except ConnectionClosed:
        pass


def _open_rooms():
    return [{"code": r.code, "name": r.name, "side": r.side, "v": r.version}
            for r in sorted(rooms.values(), key=lambda r: -r.last) if r.guest is None][:20]


async def _leave(ws, why):
    room = where.pop(ws, None)
    if room is None:
        return
    other = room.other(ws)
    rooms.pop(room.code, None)
    if other is not None:
        where.pop(other, None)
        await _send(other, {"t": "_closed", "why": why})
        await other.close()


async def handler(ws):
    try:
        async for raw in ws:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                msg = json.loads(raw)
                t = msg.get("t", "")
            except (ValueError, AttributeError):
                continue
            room = where.get(ws)
            if not str(t).startswith("_"):
                if room is not None:
                    room.last = time.time()
                    await _forward(room.other(ws), raw)
                continue
            if t == "_list":
                await _send(ws, {"t": "_rooms", "rooms": _open_rooms()})
            elif t == "_create":
                if room is not None:
                    await _leave(ws, "The host opened a new room.")
                if len(rooms) >= MAX_ROOMS:
                    await _send(ws, {"t": "_err", "why": "The server is full. Try again in a minute."})
                    continue
                code = _new_code()
                r = Room(code, ws, str(msg.get("name") or "Host")[:20], msg.get("side") if msg.get("side") in
                         ("red", "blue") else "red", msg.get("v"))
                rooms[code] = r
                where[ws] = r
                await _send(ws, {"t": "_room", "code": code})
                log.info("room %s opened (%d rooms)", code, len(rooms))
            elif t == "_join":
                code = str(msg.get("code") or "").strip().upper()
                r = rooms.get(code)
                if r is None:
                    await _send(ws, {"t": "_err", "why": f"No open game with code {code or '?'}."})
                elif r.guest is not None:
                    await _send(ws, {"t": "_err", "why": f"Game {code} already has two players."})
                elif r.host is ws:
                    await _send(ws, {"t": "_err", "why": "That is your own game."})
                else:
                    if room is not None:
                        await _leave(ws, "Your opponent joined another game.")
                    r.guest = ws
                    r.last = time.time()
                    where[ws] = r
                    await _send(ws, {"t": "_joined", "code": code, "name": r.name, "side": r.side})
                    await _send(r.host, {"t": "_peer"})
                    log.info("room %s full", code)
            elif t == "_leave":
                await _leave(ws, "The other player left.")
    except ConnectionClosed:
        pass
    finally:
        await _leave(ws, "The other player left the game.")


async def _forward(ws, raw):
    if ws is None:
        return
    try:
        await ws.send(raw)
    except ConnectionClosed:
        pass


async def _sweep():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        for code, r in list(rooms.items()):
            if now - r.last > ROOM_IDLE_SECONDS:
                for ws in (r.host, r.guest):
                    if ws is not None:
                        where.pop(ws, None)
                        await ws.close()
                rooms.pop(code, None)


def health(connection, request):
    """Plain HTTP (not a WebSocket upgrade) gets a short status page, so hosts' health checks pass."""
    if request.headers.get("Upgrade", "").lower() != "websocket":
        body = f"Zero Day relay OK. {len(rooms)} room(s) open.\n"
        return connection.respond(http.HTTPStatus.OK, body)
    return None


async def main(port):
    asyncio.get_running_loop().create_task(_sweep())
    async with serve(handler, "0.0.0.0", port, process_request=health, max_size=MAX_MSG,
                     ping_interval=20, ping_timeout=20) as server:
        log.info("Zero Day relay listening on port %d", port)
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(main(int(os.environ.get("PORT", "8765"))))
