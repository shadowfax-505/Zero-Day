"""Lockstep match protocol on top of Peer. No pygame here, so it can be tested headless.

    client -> host   hello   {name, v}
    host -> client   start   {seed, host_side, name, match}      (also used for every rematch)
    both             move    {match, round, act, fp}             fp = state fingerprint before the move
    host -> client   move    {..., state}                        after a desync: the host's full state,
                                                                 which the client adopts before the round
    client -> host   rematch {new_map}                           host answers with a new start
    both             chat    {text}
    both             bye
"""

from agents.base import Agent
from net.peer import PROTOCOL, fingerprint

OTHER = {"red": "blue", "blue": "red"}


class RemotePlayer(Agent):
    """Stands in for the player on the other machine. Its moves arrive over the network."""

    def __init__(self, side, name):
        super().__init__()
        self.side, self.name = side, name

    def choose_action(self, obs):
        raise RuntimeError("remote moves come from the network")


def pack(side, act):
    if side == "red":
        return list(act)
    return [list(a) for a in act]


def unpack(side, data):
    if side == "red":
        return tuple(data)
    return [tuple(a) for a in data]


class Session:
    """One side of an online game. role is 'host' or 'client'."""

    def __init__(self, peer, role, name, side=None, local_ai=False):
        self.peer, self.role, self.name = peer, role, name
        self.side = side                  # host picks; client learns it from 'start'
        self.local_ai = local_ai
        self.remote_name = "Opponent"
        self.match_id = 0
        self.seed = None
        self.moves = {}                   # round -> (act, fp) from the remote side, current match only
        self.sent_round = None
        self.my_fp = {}
        self.desync_round = None
        self.resyncs = 0                  # how many times this match was put back in sync
        self.resync_needed = False        # host: send the full state with the next move
        self.resync_state = {}            # client: round -> host state to adopt before that round
        self.state_sent_round = None
        self.closed = False
        self.greeted = False
        if role == "client":
            peer.send({"t": "hello", "v": PROTOCOL, "name": name})

    # -- outgoing -------------------------------------------------------------------
    def start(self, seed):
        """Host only: begin (or restart) a match on this seed."""
        self.match_id += 1
        self.seed = seed
        self._reset_round_state()
        self.peer.send({"t": "start", "seed": seed, "host_side": self.side, "name": self.name,
                        "match": self.match_id})

    def send_move(self, game, act):
        fp = fingerprint(game)
        self.my_fp[game.round] = fp
        self.sent_round = game.round
        msg = {"t": "move", "match": self.match_id, "round": game.round, "act": pack(self.side, act), "fp": fp}
        if self.role == "host" and self.resync_needed:
            # the host's game is the reference: ship it so the client can adopt it
            msg["state"] = game.snapshot()
            self.state_sent_round = game.round   # the client's fp for this round is still the old one
            self.resync_needed = False
            self.desync_round = None
            self.resyncs += 1
        self.peer.send(msg)

    def adopt_state(self, game):
        """Client: if the host sent its state for this round, take it over. Returns True if it did.
        Call before applying the round's moves; both sides then apply the same moves to the same
        state, so the match carries on in sync."""
        st = self.resync_state.pop(game.round, None)
        if st is None:
            return False
        game.restore(st)
        self.my_fp[game.round] = fingerprint(game)
        self.desync_round = None
        self.resyncs += 1
        return True

    def request_rematch(self, new_map):
        self.peer.send({"t": "rematch", "new_map": bool(new_map)})

    def chat(self, text):
        self.peer.send({"t": "chat", "text": text[:120]})

    def close(self):
        self.closed = True
        self.peer.close()

    # -- incoming -------------------------------------------------------------------
    def _reset_round_state(self):
        self.moves = {}
        self.my_fp = {}
        self.sent_round = None
        self.desync_round = None
        self.resync_needed = False
        self.resync_state = {}

    def remote_move(self, rnd):
        """The opponent's move for this round, or None if it has not arrived yet."""
        got = self.moves.get(rnd)
        if got is None:
            return None
        act, fp = got
        if fp and self.my_fp.get(rnd) and fp != self.my_fp[rnd] and self.desync_round is None \
                and rnd not in self.resync_state and rnd != self.state_sent_round:
            self.desync_round = rnd
            if self.role == "host":
                self.resync_needed = True
        return act

    def poll(self):
        """Handle network traffic. Returns UI events:
        ('start', seed) ('chat', who, text) ('rematch', new_map) ('hello', name) ('closed', why) ('error', why)"""
        out = []
        for m in self.peer.poll():
            t = m.get("t")
            if t == "hello" and self.role == "host":
                if m.get("v") != PROTOCOL:
                    self.peer.send({"t": "bye", "why": "different game version"})
                    out.append(("error", "The other player has a different version of the game."))
                    continue
                self.remote_name = str(m.get("name") or "Opponent")[:20]
                self.greeted = True
                out.append(("hello", self.remote_name))
            elif t == "start" and self.role == "client":
                self.remote_name = str(m.get("name") or "Host")[:20]
                self.side = OTHER[m["host_side"]]
                self.match_id = int(m["match"])
                self.seed = int(m["seed"])
                self._reset_round_state()
                out.append(("start", self.seed))
            elif t == "move":
                if int(m.get("match", -1)) == self.match_id:
                    rnd = int(m["round"])
                    fp = m.get("fp")
                    if self.role == "client" and isinstance(m.get("state"), dict):
                        self.resync_state[rnd] = m["state"]
                        fp = None        # compare again once the state is adopted
                    self.moves[rnd] = (unpack(OTHER[self.side], m["act"]), fp)
            elif t == "rematch" and self.role == "host":
                out.append(("rematch", bool(m.get("new_map"))))
            elif t == "chat":
                out.append(("chat", self.remote_name, str(m.get("text", ""))[:120]))
            elif t in ("bye", "_closed"):
                if not self.closed:
                    self.closed = True
                    out.append(("closed", m.get("why") or f"{self.remote_name} left the game."))
        return out
