import pathlib
from contextlib import AsyncExitStack, asynccontextmanager

from libp2p import new_host
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2 import CircuitV2Protocol, CircuitV2Transport
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.protocol import PROTOCOL_ID as RELAY_HOP_PROTOCOL_ID
from libp2p.tools.anyio_service import background_trio_service
from multiaddr import Multiaddr

from . import identity
from .Tor import TorSocksTransport


class Host:
    """Owns the libp2p swarm, identity keypair and listen addrs for one node.

    Lifecycle only in Phase 1 -- no application protocols registered yet.
    Must be run inside a trio event loop (`trio.run`), never asyncio or gevent directly.

    Phase 9 -- circuit-relay v2, built up in slices:

    `enable_relay_hop` (first slice): a node opts in to relaying traffic
    for other peers (the HOP side of the protocol) -- proved
    CircuitV2Protocol wires cleanly into this Host's own run() lifecycle
    via py-libp2p's background_trio_service.

    `enable_relay_client` (second slice): a node can reach, and be reached
    through, a relay. Needs CircuitV2Protocol running regardless of
    allow_hop (its STOP handler is what lets this host *receive* a
    relayed connection someone else dialed in through), plus a
    CircuitV2Transport for the methods below. Deliberately not
    registered into the swarm's own dialer as a generic transport (no
    documented py-libp2p API for that outside its internal wiring) --
    reserve_relay()/dial_via_relay() call the transport's own
    reservation/dial_peer_info() methods directly instead, which is
    exactly what CircuitV2Transport.dial() itself does under the hood
    for a /p2p-circuit multiaddr.

    `enable_relay_discovery` (this slice): CircuitV2Transport already
    builds a RelayDiscovery (py-libp2p's own relay-finding logic) --
    this just runs it as a background service, same background_trio_
    service pattern as the protocol itself. RelayDiscovery only scans
    peers this host is ALREADY connected to (host.get_connected_peers())
    for relay-protocol support -- it's not a bootstrap mechanism, so
    connect()ing to some peers first (via this stack's existing DHT/PEX/
    tracker discovery) is still the caller's job, same division of labor
    as SiteManager's "add() doesn't auto-fetch" elsewhere. Once a relay
    is found, auto_reserve happens automatically -- py-libp2p ties it to
    RelayConfig.enable_client, which is already True whenever
    enable_relay_client=True, not a separate flag here. reserve_relay()/
    dial_via_relay() can now omit relay_peer_info entirely and fall back
    to whatever's been discovered so far; discover_relays() forces an
    immediate scan on demand (e.g. right after a fresh connect()) rather
    than waiting up to discovery_interval for the next periodic pass.
    The Tor-vs-relay decision this phase's own risk section flags
    remains open -- nothing here drops or replaces Tor.
    """

    def __init__(self, data_dir: pathlib.Path, tcp_port: int = 0, ws_port: int | None = 0,
                 enable_relay_hop: bool = False, enable_relay_client: bool = False,
                 enable_relay_discovery: bool = False, tor_socks_proxy: tuple[str, int] | None = None):
        if enable_relay_discovery and not enable_relay_client:
            raise ValueError("enable_relay_discovery requires enable_relay_client")
        self.key_pair = identity.load_or_create(data_dir)
        self._tcp_port = tcp_port
        self._ws_port = ws_port
        self._enable_relay_hop = enable_relay_hop
        self._enable_relay_client = enable_relay_client
        self._enable_relay_discovery = enable_relay_discovery
        self._tor_socks_proxy = tor_socks_proxy
        self._host = new_host(key_pair=self.key_pair, enable_websocket=ws_port is not None)
        if tor_socks_proxy is not None:
            self._host.get_network().transport_manager.add_transport(
                TorSocksTransport(*tor_socks_proxy)
            )
        self.peer_id = self._host.get_id()
        self.relay_protocol: CircuitV2Protocol | None = None
        self.relay_transport: CircuitV2Transport | None = None

    def _listen_addrs(self) -> list[Multiaddr]:
        addrs = [Multiaddr(f"/ip4/0.0.0.0/tcp/{self._tcp_port}")]
        if self._ws_port is not None:
            addrs.append(Multiaddr(f"/ip4/0.0.0.0/tcp/{self._ws_port}/ws"))
        return addrs

    @asynccontextmanager
    async def run(self):
        """Async context manager: `async with host.run(): ...`"""
        async with self._host.run(listen_addrs=self._listen_addrs()):
            if not self._enable_relay_hop and not self._enable_relay_client:
                yield
                return
            self.relay_protocol = CircuitV2Protocol(self._host, allow_hop=self._enable_relay_hop)
            try:
                async with AsyncExitStack() as stack:
                    await stack.enter_async_context(background_trio_service(self.relay_protocol))
                    if self._enable_relay_client:
                        roles = RelayRole.STOP | RelayRole.CLIENT
                        if self._enable_relay_hop:
                            roles |= RelayRole.HOP
                        self.relay_transport = CircuitV2Transport(
                            self._host, self.relay_protocol, RelayConfig(roles=roles)
                        )
                        if self._enable_relay_discovery:
                            await stack.enter_async_context(
                                background_trio_service(self.relay_transport.discovery)
                            )
                    yield
            finally:
                self.relay_protocol = None
                self.relay_transport = None

    def _resolveRelay(self, relay_peer_info: PeerInfo | None) -> PeerInfo:
        if self.relay_transport is None:
            raise RuntimeError("Host was not started with enable_relay_client=True")
        if relay_peer_info is not None:
            return relay_peer_info
        relay_peer_id = self.relay_transport.discovery.get_relay()
        if relay_peer_id is None:
            raise RuntimeError(
                "No relay_peer_info given and none discovered yet -- "
                "call discover_relays() after connecting to some peers, or pass one explicitly"
            )
        return self._host.get_peerstore().peer_info(relay_peer_id)

    async def discover_relays(self, relay_peer_info: PeerInfo | None = None):
        """Force an immediate scan of currently-connected peers for
        relay-protocol support (normally happens automatically every
        discovery_interval once enable_relay_discovery=True, but this
        runs it right now -- e.g. straight after a fresh connect()).
        Returns the peer IDs of every relay discovered so far. Requires
        enable_relay_client=True; works whether or not the periodic
        background service is running."""
        if self.relay_transport is None:
            raise RuntimeError("Host was not started with enable_relay_client=True")
        await self.relay_transport.discovery.discover_relays()
        return self.relay_transport.discovery.get_relays()

    async def reserve_relay(self, relay_peer_info: PeerInfo | None = None) -> bool:
        """Ask `relay_peer_info` to forward CONNECT requests for this host
        to it -- required before any other peer can dial_via_relay() to
        reach this host. If omitted, falls back to a relay already found
        via discover_relays()/enable_relay_discovery. Requires
        enable_relay_client=True."""
        relay_peer_info = self._resolveRelay(relay_peer_info)
        await self._host.connect(relay_peer_info)
        stream = await self._host.new_stream(relay_peer_info.peer_id, [RELAY_HOP_PROTOCOL_ID])
        try:
            return await self.relay_transport._make_reservation(stream, relay_peer_info.peer_id)
        finally:
            await stream.close()

    async def dial_via_relay(self, relay_peer_info: PeerInfo | None, dest_peer_id) -> None:
        """Reach `dest_peer_id` through `relay_peer_info` without ever
        connecting to it directly -- dest_peer_id must have already
        reserve_relay()'d on the same relay. If relay_peer_info is None,
        falls back to a relay already found via discover_relays()/
        enable_relay_discovery. On success the connection is registered
        with the swarm like any other; host.new_stream(dest_peer_id, ...)
        works transparently afterwards. Requires enable_relay_client=True."""
        relay_peer_info = self._resolveRelay(relay_peer_info)
        raw_conn = await self.relay_transport.dial_peer_info(
            PeerInfo(dest_peer_id, []), relay_info=relay_peer_info
        )
        await self._host.upgrade_outbound_connection(raw_conn, dest_peer_id)

    def get_addrs(self) -> list[Multiaddr]:
        return self._host.get_addrs()

    def get_network(self):
        return self._host.get_network()

    def get_peerstore(self):
        return self._host.get_peerstore()

    async def connect(self, peer_info):
        await self._host.connect(peer_info)

    @property
    def raw(self):
        """Escape hatch for code that needs the underlying IHost directly (e.g. protocol registration in Phase 2)."""
        return self._host
