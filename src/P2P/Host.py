import pathlib
from contextlib import asynccontextmanager

from libp2p import new_host
from libp2p.relay.circuit_v2 import CircuitV2Protocol
from libp2p.tools.anyio_service import background_trio_service
from multiaddr import Multiaddr

from . import identity


class Host:
    """Owns the libp2p swarm, identity keypair and listen addrs for one node.

    Lifecycle only in Phase 1 -- no application protocols registered yet.
    Must be run inside a trio event loop (`trio.run`), never asyncio or gevent directly.

    Phase 9, first slice -- circuit-relay v2 SERVER role only
    (`enable_relay_hop`): a node can opt in to relaying traffic for other
    peers (the HOP side of the protocol), proving CircuitV2Protocol wires
    cleanly into this Host's own run() lifecycle via py-libp2p's
    background_trio_service. Deliberately NOT included in this slice:
    the CLIENT side (CircuitV2Transport, dialing a peer through
    /p2p-circuit when direct connection fails) -- that needs the
    transport registered into the swarm's dialer, relay discovery/
    reservation bookkeeping, and answers the actual "can a NAT'd node be
    reached" milestone this stack doesn't yet make. This slice is
    additive infrastructure toward that, not the milestone itself. The
    Tor-vs-relay decision this phase's own risk section flags also
    remains open -- nothing here drops or replaces Tor.
    """

    def __init__(self, data_dir: pathlib.Path, tcp_port: int = 0, ws_port: int | None = 0,
                 enable_relay_hop: bool = False):
        self.key_pair = identity.load_or_create(data_dir)
        self._tcp_port = tcp_port
        self._ws_port = ws_port
        self._enable_relay_hop = enable_relay_hop
        self._host = new_host(key_pair=self.key_pair, enable_websocket=ws_port is not None)
        self.peer_id = self._host.get_id()
        self.relay_protocol: CircuitV2Protocol | None = None

    def _listen_addrs(self) -> list[Multiaddr]:
        addrs = [Multiaddr(f"/ip4/0.0.0.0/tcp/{self._tcp_port}")]
        if self._ws_port is not None:
            addrs.append(Multiaddr(f"/ip4/0.0.0.0/tcp/{self._ws_port}/ws"))
        return addrs

    @asynccontextmanager
    async def run(self):
        """Async context manager: `async with host.run(): ...`"""
        async with self._host.run(listen_addrs=self._listen_addrs()):
            if not self._enable_relay_hop:
                yield
                return
            self.relay_protocol = CircuitV2Protocol(self._host, allow_hop=True)
            try:
                async with background_trio_service(self.relay_protocol):
                    yield
            finally:
                self.relay_protocol = None

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
