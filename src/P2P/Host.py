import pathlib
from contextlib import asynccontextmanager

from libp2p import new_host
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2 import CircuitV2Protocol, CircuitV2Transport
from libp2p.relay.circuit_v2.config import RelayConfig, RelayRole
from libp2p.relay.circuit_v2.protocol import PROTOCOL_ID as RELAY_HOP_PROTOCOL_ID
from libp2p.tools.anyio_service import background_trio_service
from multiaddr import Multiaddr

from . import identity


class Host:
    """Owns the libp2p swarm, identity keypair and listen addrs for one node.

    Lifecycle only in Phase 1 -- no application protocols registered yet.
    Must be run inside a trio event loop (`trio.run`), never asyncio or gevent directly.

    Phase 9 -- circuit-relay v2, built up in slices:

    `enable_relay_hop` (first slice): a node opts in to relaying traffic
    for other peers (the HOP side of the protocol) -- proved
    CircuitV2Protocol wires cleanly into this Host's own run() lifecycle
    via py-libp2p's background_trio_service.

    `enable_relay_client` (this slice): a node can reach, and be reached
    through, a relay. Needs CircuitV2Protocol running regardless of
    allow_hop (its STOP handler is what lets this host *receive* a
    relayed connection someone else dialed in through), plus a
    CircuitV2Transport for the two new methods below. Deliberately not
    registered into the swarm's own dialer as a generic transport (no
    documented py-libp2p API for that outside its internal wiring) --
    reserve_relay()/dial_via_relay() call the transport's own
    reservation/dial_peer_info() methods directly instead, which is
    exactly what CircuitV2Transport.dial() itself does under the hood
    for a /p2p-circuit multiaddr. discovery/auto-reserve/DHT-backed relay
    finding (RelayDiscovery's own background loop) is NOT started --
    reservations are explicit, caller-driven, matching this stack's
    "add() doesn't auto-fetch" pattern elsewhere (see SiteManager).
    The Tor-vs-relay decision this phase's own risk section flags
    remains open -- nothing here drops or replaces Tor.
    """

    def __init__(self, data_dir: pathlib.Path, tcp_port: int = 0, ws_port: int | None = 0,
                 enable_relay_hop: bool = False, enable_relay_client: bool = False):
        self.key_pair = identity.load_or_create(data_dir)
        self._tcp_port = tcp_port
        self._ws_port = ws_port
        self._enable_relay_hop = enable_relay_hop
        self._enable_relay_client = enable_relay_client
        self._host = new_host(key_pair=self.key_pair, enable_websocket=ws_port is not None)
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
                async with background_trio_service(self.relay_protocol):
                    if self._enable_relay_client:
                        roles = RelayRole.STOP | RelayRole.CLIENT
                        if self._enable_relay_hop:
                            roles |= RelayRole.HOP
                        self.relay_transport = CircuitV2Transport(
                            self._host, self.relay_protocol, RelayConfig(roles=roles)
                        )
                    yield
            finally:
                self.relay_protocol = None
                self.relay_transport = None

    async def reserve_relay(self, relay_peer_info: PeerInfo) -> bool:
        """Ask `relay_peer_info` to forward CONNECT requests for this host
        to it -- required before any other peer can dial_via_relay() to
        reach this host. Requires enable_relay_client=True."""
        if self.relay_transport is None:
            raise RuntimeError("Host was not started with enable_relay_client=True")
        await self._host.connect(relay_peer_info)
        stream = await self._host.new_stream(relay_peer_info.peer_id, [RELAY_HOP_PROTOCOL_ID])
        try:
            return await self.relay_transport._make_reservation(stream, relay_peer_info.peer_id)
        finally:
            await stream.close()

    async def dial_via_relay(self, relay_peer_info: PeerInfo, dest_peer_id) -> None:
        """Reach `dest_peer_id` through `relay_peer_info` without ever
        connecting to it directly -- dest_peer_id must have already
        reserve_relay()'d on the same relay. On success the connection is
        registered with the swarm like any other; host.new_stream(dest_peer_id, ...)
        works transparently afterwards. Requires enable_relay_client=True."""
        if self.relay_transport is None:
            raise RuntimeError("Host was not started with enable_relay_client=True")
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
