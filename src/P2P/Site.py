"""Trio-native replacement for Site/Site.py -- started here with the peer
table (addPeer/getConnectablePeers/isServing), the slice FileServer.py
already depends on (Phase 6, previous step) and the only part of Site.py
that doesn't first need ContentManager/SiteStorage/WorkerManager/the UI
layer ported -- all still gevent-based, all larger undertakings of their
own. Content loading, download orchestration, and plugin hooks extend
this class in later sessions.

Peer identity is peer_id (libp2p), not ip:port like the old Site.peers
table: host.connect() needs a peer_id up front to authenticate the Noise
handshake, so ip:port alone was never enough to actually dial anyone under
libp2p -- see protocols/pex.py's docstring for the same point from the
wire-protocol side. addPeer()'s signature reflects that (peer_id is now a
required, leading argument, not absent like the original).
"""
import time

from libp2p.peer.id import ID


class PeerRecord:
    __slots__ = ("peer_id", "ip", "port", "reputation", "time_found")

    def __init__(self, peer_id: ID, ip: str, port: int):
        self.peer_id = peer_id
        self.ip = ip
        self.port = port
        self.reputation = 0
        self.time_found = time.time()

    def found(self, source: str = "other") -> None:
        if self.reputation < 5:
            if source == "tracker":
                self.reputation += 1
            elif source == "local":
                self.reputation += 20
        self.time_found = time.time()


class Site:
    def __init__(self, address: str, site_root, serving: bool = True):
        self.address = address
        self.site_root = site_root
        self.serving = serving
        self.peers: dict[str, PeerRecord] = {}  # peer_id.to_base58() -> PeerRecord
        self.peer_blacklist: set = set()  # of peer_id.to_base58()

    def isServing(self) -> bool:
        return self.serving

    def addPeer(self, peer_id: ID, ip: str, port: int, source: str = "other"):
        """Returns the PeerRecord (new or already-known), or False if
        rejected (blacklisted, or a bare 0.0.0.0 that can't mean anything)."""
        if not ip or ip == "0.0.0.0":
            return False

        key = peer_id.to_base58()
        record = self.peers.get(key)
        if record:
            record.found(source)
            return record

        if key in self.peer_blacklist:
            return False

        record = PeerRecord(peer_id, ip, port)
        self.peers[key] = record
        record.found(source)
        return record

    def getConnectablePeers(self, need_num: int = 5, exclude: set | None = None) -> list[PeerRecord]:
        exclude = exclude or set()
        candidates = [p for p in self.peers.values() if p.peer_id not in exclude]
        candidates.sort(key=lambda p: p.reputation, reverse=True)
        return candidates[:need_num]
