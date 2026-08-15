"""Trio-native replacement for Site/Site.py -- started with the peer table
(addPeer/getConnectablePeers/isServing) and now owns a real SiteStorage
(file I/O layer) and ContentManager (content.json loading + root-signature
verification only -- see ContentManager.py's own module docstring for what
that excludes). WorkerManager and the UI layer are still gevent-based and
much larger undertakings of their own -- download orchestration and
plugin hooks extend this class once those land.

Peer identity is peer_id (libp2p), not ip:port like the old Site.peers
table: host.connect() needs a peer_id up front to authenticate the Noise
handshake, so ip:port alone was never enough to actually dial anyone under
libp2p -- see protocols/pex.py's docstring for the same point from the
wire-protocol side. addPeer()'s signature reflects that (peer_id is now a
required, leading argument, not absent like the original).

ip/port are optional (unlike the original's required, non-empty pair):
kad-dht's find_peers() (SiteAnnouncer.py) returns libp2p PeerInfo objects
-- peer_id plus a multiaddr list, no plain ip:port -- so a DHT-discovered
peer genuinely doesn't have one to give. The real dialing address always
lives in the libp2p host's own peerstore once any connection or DHT
lookup has touched that peer_id; ip/port here are best-effort display
info (as pex's wire format still provides), not what dialing depends on.
"""
import hashlib
import time

from libp2p.peer.id import ID

from Crypt import CryptHash

from .SiteStorage import SiteStorage
from .ContentManager import ContentManager


class PeerRecord:
    __slots__ = ("peer_id", "ip", "port", "reputation", "time_found")

    def __init__(self, peer_id: ID, ip: str | None, port: int | None):
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
    def __init__(self, address: str, site_root, serving: bool = True, allow_create: bool = True):
        self.address = address
        self.address_sha1 = hashlib.sha1(address.encode("ascii")).digest()  # DHT key
        self.site_root = site_root
        self.storage = SiteStorage(site_root, allow_create=allow_create)
        self.content_manager = ContentManager(self.storage, address)
        self.serving = serving
        self.peers: dict[str, PeerRecord] = {}  # peer_id.to_base58() -> PeerRecord
        self.peer_blacklist: set = set()  # of peer_id.to_base58()

        # Minimal slice of the original's settings dict -- just what the
        # Phase 7 wrapper-HTML rendering needs (permissions list, the two
        # per-site auth keys for websocket access). The rest of settings
        # (added/downloaded/size tracking, sites.json persistence) waits
        # for whatever eventually needs it.
        self.permissions: list = []
        self.wrapper_key = CryptHash.random()
        self.ajax_key = CryptHash.random()

    def isServing(self) -> bool:
        return self.serving

    def addPeer(self, peer_id: ID, ip: str | None = None, port: int | None = None, source: str = "other"):
        """Returns the PeerRecord (new or already-known), or False if
        rejected (blacklisted). ip may be None (e.g. DHT-sourced peers,
        which come as peer_id + multiaddrs, not a plain ip:port pair) --
        that's different from an explicitly empty/"0.0.0.0" ip, which is
        still rejected the same as the original."""
        if ip is not None and (not ip or ip == "0.0.0.0"):
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
