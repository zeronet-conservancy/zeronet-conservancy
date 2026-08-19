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

@acceptPlugins: same Phase 8 treatment as User/SiteAnnouncer/SiteManager,
added so a plugin's own registerTo("Site") override can actually attach to
something -- e.g. plugins/ContentFilter/ContentFilterPlugin.py's own
SitePlugin.needFile() mute check, which had no equivalent method to
override here until needFile() itself was added below. Only needFile()
is exposed as an overridable method for now, not the rest of a plugin's
conceivable surface (addPeer, isServing, ...) -- add more as a real
plugin actually needs to hook them, same "wire it up when there's an
actual caller" discipline SiteStorage.py's own docstring already uses.
"""
import base64
import hashlib
import json
import time

from libp2p.peer.id import ID

from Crypt import CryptBitcoin, CryptEcies, CryptHash

from .PluginManager import acceptPlugins
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


@acceptPlugins
class Site:
    def __init__(self, address: str, site_root, serving: bool = True, allow_create: bool = True,
                 permissions: list | None = None):
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
        # (added/downloaded/size tracking) waits for whatever eventually
        # needs it. permissions itself IS persisted -- SiteManager.load()
        # passes in whatever sites.json had saved, and SiteManager.save()
        # reads this list back out; see that module's own docstring.
        self.permissions: list = list(permissions) if permissions else []
        self.wrapper_key = CryptHash.random()
        self.ajax_key = CryptHash.random()

        # Private-site unlock state -- the decrypted AES content key once
        # unlocked, None while locked. Never persisted by Site itself
        # (SiteManager's settings store is the source of truth for
        # private_key/private_recipients, matching serving/own/peers --
        # see ContentManager.py's own module docstring); this is purely
        # an in-memory cache for the lifetime of this Site instance.
        self.private_key: bytes | None = None

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

    def restorePeer(self, peer_id: ID, ip: str | None, port: int | None, reputation: int = 0) -> PeerRecord:
        """Re-inserts a peer with an explicit reputation, bypassing
        found()'s bump semantics -- used by SiteManager.load() to restore
        peers persisted in sites.json across a restart (see that module's
        own docstring on PeerDb-equivalent persistence), preserving
        earned reputation exactly rather than treating rediscovery as a
        fresh find. Unlike addPeer(), never rejected: a peer already
        blacklisted since it was last persisted stays blacklisted for new
        discoveries via addPeer(), but a straight restore of what was on
        disk isn't a new "should we trust this" decision."""
        record = PeerRecord(peer_id, ip, port)
        record.reputation = reputation
        self.peers[peer_id.to_base58()] = record
        return record

    def getConnectablePeers(self, need_num: int = 5, exclude: set | None = None) -> list[PeerRecord]:
        exclude = exclude or set()
        candidates = [p for p in self.peers.values() if p.peer_id not in exclude]
        candidates.sort(key=lambda p: p.reputation, reverse=True)
        return candidates[:need_num]

    async def needFile(self, inner_path: str, peers: list, priority: int = 0, timeout: float = 60) -> bytes:
        """Thin wrapper around WorkerManager.Scheduler.needFile() -- the
        real per-site fetch entrypoint, matching the original's own
        Site.needFile() shape closely enough for a plugin's registerTo
        ("Site") override to actually mean something (see this class's
        own docstring). Deliberately doesn't hold a persistent Scheduler
        across calls: both existing call sites (P2P/Ui/commands.py's
        fileNeed, P2P/actions.py's siteNeedFile) already constructed a
        fresh one per call before this method existed, so a fresh one
        here changes nothing about in-flight-dedup behavior, just moves
        where it's constructed."""
        from .WorkerManager import Scheduler
        return await Scheduler(self).needFile(inner_path, peers, priority=priority, timeout=timeout)

    async def getPrivatekey(self, user, content_key_b64: str | None = None) -> bytes | None:
        """Returns this site's private-site AES content key, unlocking it
        first if not already cached. See unlockPrivate() for the actual
        owner-vs-recipient logic; this just adds the "already unlocked"
        fast path, matching the original's own getPrivatekey()/
        unlockPrivate() split."""
        if self.private_key is not None:
            return self.private_key
        return await self.unlockPrivate(user, content_key_b64)

    async def unlockPrivate(self, user, content_key_b64: str | None = None) -> bytes | None:
        """Unlock this site's private content key for `user`, caching it
        into self.private_key on success. Returns None on any failure --
        wrong/missing user, not actually a private site, tampered
        envelope, no access yet -- never raises: "no access" is an
        expected, common state on the read path, not an error.

        Reads content.json straight off disk rather than trusting
        self.content_manager.contents: that cache holds *decrypted*
        plaintext once anyone (owner or an already-unlocked recipient)
        has loaded it with a working key (see ContentManager.loadContent()'s
        own docstring) -- so it no longer carries the "privatekey": true
        marker that would tell a second, independent unlock attempt this
        is even a private site. The on-disk envelope is the one place
        that's always in its real, undecrypted shape.

        content_key_b64 is the owner's own path: if this Site instance's
        caller already knows the site's own persisted AES content key
        (SiteManager's setSiteSetting("private_key", ...), b64-encoded),
        pass it and unlocking is immediate -- no envelope/recipient logic
        needed, matching the original's owner shortcut. Omit it (or pass
        None) for the recipient path, which recovers the key via this
        user's own auth_address/auth_privatekey (already used for site
        permissions -- see this class's own module docstring on why a
        private-site recipient doesn't get a separate dedicated key)."""
        if not self.storage.isFile("content.json"):
            return None  # Nothing signed yet -- nothing to unlock
        envelope = await self.storage.loadJson("content.json")
        if not self.content_manager.isPrivate(envelope):
            return None

        if content_key_b64:
            self.private_key = base64.b64decode(content_key_b64)
            return self.private_key

        keys = envelope.get("keys", {})
        keys_sign = envelope.get("keys_sign")
        try:
            valid = bool(keys_sign) and CryptBitcoin.verify(
                json.dumps(keys, sort_keys=True), self.address, keys_sign,
            )
        except Exception:
            valid = False
        if not valid:
            return None

        auth_address = user.getAuthAddress(self.address)
        wrapped_b64 = keys.get(auth_address)
        if not wrapped_b64:
            return None

        auth_privatekey = user.getAuthPrivatekey(self.address)
        try:
            self.private_key = CryptEcies.unwrapKey(base64.b64decode(wrapped_b64), auth_privatekey)
        except Exception:
            return None
        return self.private_key

    def lockPrivate(self) -> None:
        self.private_key = None
