"""Replaces Connection.py.

Most of Connection's 651 lines -- raw socket I/O, TLS wrapping, msgpack
framing, handshake negotiation -- are gone: libp2p's connection upgrade
(multistream-select + Noise) already does that, and ProtocolRouter.call()
already implements one-stream-per-request, so there's no req_id/
waiting_requests correlation to reimplement either -- the stream itself is
the correlation.

What's left is what Connection.py did *beyond* raw transport: per-peer
bookkeeping (timing, reputation) and a cmd-name -> protocol-ID registry,
since libp2p addresses protocols by ID rather than a shared "cmd" field on
one connection.
"""
import time

from . import ProtocolRouter
from .protocols import getfile, pex, ping, update

# cmd name -> protocol ID. Grows as more protocols/*.py handlers land;
# PeerSession doesn't need all of them to be useful.
PROTOCOLS = {
    "ping": ping.PROTOCOL_ID,
    "getFile": getfile.PROTOCOL_ID,
    "pex": pex.PROTOCOL_ID,
    "update": update.PROTOCOL_ID,
}


class PeerSession:
    def __init__(self, host, peer_id):
        self.host = host
        self.peer_id = peer_id
        self.last_cmd_sent = None
        self.last_req_time = 0.0
        self.last_ping_delay = None
        self.bad_actions = 0
        self.connected_time = time.time()

    def badAction(self, weight: int = 1) -> None:
        self.bad_actions += weight

    def goodAction(self) -> None:
        self.bad_actions = 0

    async def request(self, cmd: str, params: dict | None = None) -> dict:
        protocol_id = PROTOCOLS.get(cmd)
        if protocol_id is None:
            return {"error": "Unknown command: %s" % cmd}

        self.last_req_time = time.time()
        self.last_cmd_sent = cmd
        return await ProtocolRouter.call(self.host, self.peer_id, protocol_id, params or {})

    async def ping(self) -> bool:
        s = time.time()
        response = await self.request("ping")
        if response and response.get("body") == b"Pong!":
            self.last_ping_delay = time.time() - s
            return True
        return False
