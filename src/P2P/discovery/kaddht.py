"""Kademlia DHT discovery, replacing src/DHT/DHTServer.py + aiobtdht/
aio-krpc-server entirely. Validated in the Phase 0 spike: provide()/
find_providers() round-trip cleanly, and a custom protocol_prefix keeps
this DHT in its own namespace, isolated from the public IPFS swarm --
zeronet-conservancy's clean-break network shouldn't share a routing table
with unrelated IPFS traffic.

Site addresses are keyed by their raw hash bytes (site.address_sha1 today);
kad-dht's provide()/find_providers() take str keys, so they're hex-encoded
at the boundary here rather than pushing that detail on every caller.
"""
import hashlib

from libp2p.kad_dht.kad_dht import KadDHT, DHTMode
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.tools.anyio_service import background_trio_service

DEFAULT_PROTOCOL_PREFIX = "/zeronet"
IDENTITY_NAMESPACE = b"zeronet:identity:v1:"


class KadDHTDiscovery:
    def __init__(self, host, protocol_prefix: str = DEFAULT_PROTOCOL_PREFIX):
        self._dht = KadDHT(host.raw, DHTMode.SERVER, protocol_prefix=protocol_prefix)

    def run(self):
        """Async context manager: `async with discovery.run(): ...`"""
        return background_trio_service(self._dht)

    async def add_peer(self, peer_id: ID) -> None:
        """Seed the routing table with a known peer (e.g. a bootstrap node,
        or a peer already connected via another discovery path)."""
        await self._dht.add_peer(peer_id)

    async def announce(self, site_hash: bytes) -> None:
        await self._dht.provide(site_hash.hex())

    async def find_peers(self, site_hash: bytes) -> list[PeerInfo]:
        return await self._dht.find_providers(site_hash.hex())

    @staticmethod
    def identity_key(domain: str, auth_type: str, username: str) -> bytes:
        """Return the opaque DHT key for a ZeroNet identity record.

        The DHT never receives the plaintext username. The provider still
        owns the signed certificate and is responsible for uniqueness and
        revocation; this key only discovers provider peers.
        """
        identity = "%s\x00%s\x00%s" % (domain.strip().lower(), auth_type.strip().lower(), username.strip())
        return hashlib.sha256(IDENTITY_NAMESPACE + identity.encode("utf-8")).digest()

    async def announce_identity(self, domain: str, auth_type: str, username: str) -> bytes:
        key = self.identity_key(domain, auth_type, username)
        await self._dht.provide(key.hex())
        return key

    async def find_identity_providers(self, domain: str, auth_type: str, username: str) -> list[PeerInfo]:
        key = self.identity_key(domain, auth_type, username)
        return await self._dht.find_providers(key.hex())

    async def announce_provider(self, domain: str) -> bytes:
        key = self.identity_key(domain, "provider", "*")
        await self._dht.provide(key.hex())
        return key

    async def find_providers(self, domain: str) -> list[PeerInfo]:
        key = self.identity_key(domain, "provider", "*")
        return await self._dht.find_providers(key.hex())
