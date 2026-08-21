"""LAN peer discovery via UDP broadcast, ported from
plugins/AnnounceLocal/{AnnounceLocalPlugin,BroadcastServer}.py -- real
trio UDP sockets, not a stub: LocalAnnouncer binds a real socket and both
sends and receives real broadcast packets on the local network.

Deliberately simplified relative to the original's own two-round-trip
protocol (discoverRequest -> discoverResponse carrying a sites_changed
counter -> siteListRequest -> siteListResponse -> addPeer): this stack's
own discover() broadcasts our OWN currently-served site hashes directly
in a single packet, rather than negotiating whether the receiver already
has an up-to-date list first. Every peer already calls discover()
periodically (via SiteAnnouncer.announce()'s own call, same cadence as
its tracker/DHT/PEX rounds), so mutual discovery still happens -- A
learns about B from B's own next broadcast, not from an explicit
response to A's request -- at the cost of slightly more UDP traffic per
broadcast (every site's own 20-byte address hash, not just a changed/
unchanged flag) in exchange for a single-message protocol with no
request/response state machine to track.

Wire format is plain JSON, not msgpack -- LAN-only, so packet size budget
is generous, and there's no wire-compatibility reason to prefer msgpack
here specifically (this is a clean-break migration; nothing on the LAN
speaks the original's own msgpack framing anyway).

Port advertised in the broadcast is the real bound libp2p TCP listen
port (parsed from host.get_addrs(), same "/ws" addr filtering + tcp
protocol extraction P2P/app.py's own _connectTor() already established),
not the UDP discovery port itself -- addPeer()'s ip/port are best-effort
dial info (see Site.py's own docstring: actual dialing goes through the
host's peerstore, populated by a real connection or DHT lookup), so
getting this right matters for a freshly-discovered LAN peer to be
reachable at all before any other discovery path has touched it.
"""
import json
import logging
import socket as socket_module
from contextlib import asynccontextmanager

import trio
from libp2p.peer.id import ID

DISCOVER_PORT = 15441  # Deliberately different from the original's 1544 -- no reason to risk colliding with a legacy client's own listener on the same LAN
MAX_PACKET = 8192


class LocalAnnouncer:
    def __init__(self, host, sites: dict, listen_port: int = DISCOVER_PORT):
        self.host = host
        self.sites = sites  # site address -> Site, the same dict FileServer/UiApp already hold a reference to
        self.listen_port = listen_port
        self.log = logging.getLogger("P2P.discovery.LocalAnnouncer")
        self._socket = None

    @asynccontextmanager
    async def run(self):
        """Async context manager: `async with local_announcer.run(): ...`
        -- same shape as Host.run()/FileServer.run(), so P2P/app.py's own
        AsyncExitStack wiring can treat it identically. Binds the
        broadcast listen socket and runs the receive loop for the
        context's lifetime; if the port can't be bound, logs a warning
        and yields anyway rather than raising -- matching the original's
        own createBroadcastSocket() retry-then-give-up behavior. LAN
        discovery is a nice-to-have on top of tracker/DHT/PEX, not
        something that should ever crash startup."""
        sock = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
        sock.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
        if hasattr(socket_module, "SO_REUSEPORT"):
            try:
                sock.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEPORT, 1)
            except OSError:
                pass
        try:
            await sock.bind(("", self.listen_port))
        except OSError as err:
            self.log.warning("Unable to bind LAN discovery socket on port %s: %s", self.listen_port, err)
            yield
            return

        self._socket = sock
        try:
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._receiveLoop)
                yield
                nursery.cancel_scope.cancel()
        finally:
            self._socket = None
            sock.close()

    async def _receiveLoop(self) -> None:
        while True:
            try:
                data, addr = await self._socket.recvfrom(MAX_PACKET)
            except (trio.ClosedResourceError, OSError):
                return
            self._handlePacket(data, addr)

    def _handlePacket(self, data: bytes, addr) -> None:
        try:
            message = json.loads(data.decode("utf8"))
            peer_id = ID.from_base58(message["peer_id"])
            port = int(message["port"])
            hashes = set(message["sites"])
        except Exception:
            return
        if peer_id == self.host.peer_id:
            return  # Our own broadcast, echoed back by a shared broadcast address -- ignore
        ip = addr[0]
        for site in self.sites.values():
            if site.address_sha1.hex() in hashes:
                site.addPeer(peer_id, ip, port, source="local")

    def _ourFileserverPort(self) -> int:
        tcp_addrs = [addr for addr in self.host.get_addrs() if "/ws" not in str(addr)]
        return int(tcp_addrs[0].value_for_protocol("tcp")) if tcp_addrs else 0

    async def discover(self) -> None:
        """Broadcasts our own peer_id, real listen port, and currently-
        served site hashes to the LAN. A real UDP broadcast to
        255.255.255.255 -- SO_BROADCAST is required for the packet to
        actually leave the sending interface, same as the original."""
        if self._socket is None or not self.sites:
            return
        message = json.dumps({
            "peer_id": self.host.peer_id.to_base58(),
            "port": self._ourFileserverPort(),
            "sites": [site.address_sha1.hex() for site in self.sites.values()],
        }).encode("utf8")
        if len(message) > MAX_PACKET:
            self.log.warning("LAN discovery broadcast too large (%s bytes), skipping", len(message))
            return
        send_sock = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
        try:
            send_sock.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_BROADCAST, 1)
            await send_sock.sendto(message, ("255.255.255.255", self.listen_port))
        except OSError as err:
            self.log.debug("LAN discovery broadcast failed: %s", err)
        finally:
            send_sock.close()
