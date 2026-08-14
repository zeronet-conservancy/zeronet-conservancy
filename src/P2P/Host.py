import pathlib

from libp2p import new_host
from multiaddr import Multiaddr

from . import identity


class Host:
    """Owns the libp2p swarm, identity keypair and listen addrs for one node.

    Lifecycle only in Phase 1 -- no application protocols registered yet.
    Must be run inside a trio event loop (`trio.run`), never asyncio or gevent directly.
    """

    def __init__(self, data_dir: pathlib.Path, tcp_port: int = 0, ws_port: int | None = 0):
        self.key_pair = identity.load_or_create(data_dir)
        self._tcp_port = tcp_port
        self._ws_port = ws_port
        self._host = new_host(key_pair=self.key_pair, enable_websocket=ws_port is not None)
        self.peer_id = self._host.get_id()

    def _listen_addrs(self) -> list[Multiaddr]:
        addrs = [Multiaddr(f"/ip4/0.0.0.0/tcp/{self._tcp_port}")]
        if self._ws_port is not None:
            addrs.append(Multiaddr(f"/ip4/0.0.0.0/tcp/{self._ws_port}/ws"))
        return addrs

    def run(self):
        """Async context manager: `async with host.run(): ...`"""
        return self._host.run(listen_addrs=self._listen_addrs())

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
