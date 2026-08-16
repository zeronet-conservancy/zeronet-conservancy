"""Trio port of a scoped slice of Tor/TorManager.py -- talking to a
locally-running Tor daemon's control port to manage onion (hidden)
services, using the same line-based control protocol (PROTOCOLINFO/
AUTHENTICATE/ADD_ONION/DEL_ONION/SIGNAL) over a plain trio.SocketStream
instead of a blocking socket.

Scoped to the control-port half only -- creating/removing onion
services pointing at this node's own TCP listen port, and status/
lifecycle tracking. This is a real, self-contained, useful slice on its
own: once an onion service is ADD_ONION'd against P2P.Host's TCP port,
inbound connections arriving via that .onion address show up as
ordinary plaintext TCP connections on the existing listener -- Tor
itself terminates the onion routing locally before handing the
connection off, so nothing in P2P.Host/libp2p's transport layer needs
to change for INBOUND onion reachability.

Deliberately NOT ported in this slice: createSocket() -- dialing OUT to
a peer's .onion address through Tor's SOCKS5 proxy. That needs a custom
libp2p ITransport wrapping a SOCKS5-proxied connection (libp2p's own TCP
transport dials real IPs directly, no proxy hook), real, separate work,
and PySocks (the `socks` package the original imports for this) isn't
even a dependency of this stack yet. Also not ported: the Windows
self-bundled tor.exe subprocess management (startTor/stopTor/atexit) --
this stack is Linux-first, matching the original's own
`sys.platform.startswith("win")` gate around that code. Also not
ported: the addOnion() self-blacklist of the newly created onion address
via SiteManager.peer_blacklist -- P2P.SiteManager has no peer_blacklist
concept yet (see its own module docstring); nothing to append to.
setStatus() doesn't push a UI update either (the original calls
main.ui_server.updateWebsocket()) -- that's a job for whatever wires this
into P2P/app.py, via UiApp.broadcast("serverChanged", ...), once this
class actually gets instantiated from there.

config.tor's three-way "off"/"same-onion-for-every-site"/"different-
onion-per-site" toggle becomes a single `always_different_onions`
constructor bool instead of a live global-config read -- same
adaptation this stack makes everywhere else (see e.g. P2P.Site's own
constructor params replacing scattered config.* reads).

Two bugs found and fixed while writing this port's tests (against a real
fake control-port server, not a mock -- see TestP2PTor.py):

1. The original's send() loops reading until the accumulated response
   ends with literally "250 OK\r\n", which hangs forever on any *other*
   terminal response -- e.g. a real "515 Authentication failed\r\n" on a
   bad password, which Tor's control protocol does not follow with
   anything further. This port instead recognizes any final response
   line (three digits + space, per the control protocol's own
   continuation-vs-final convention of "250-" vs "250 "), not just a
   successful one.
2. The original's lock is a gevent.lock.RLock (reentrant); trio.Lock is
   not. request()'s reconnect-on-demand path (holding the lock, then
   calling connect() which also acquired the lock) and getOnion()'s
   create-if-missing path (holding the lock, then calling addOnion() ->
   request(), which also acquires it) would both deadlock/error under
   trio.Lock's non-reentrant semantics. Fixed by having exactly one
   lock-acquisition point per call chain (_connectControllerLocked()
   assumes its caller already holds the lock) and a second, separate
   lock for the onion-creation bookkeeping specifically so it doesn't
   need to nest inside the connection lock at all.
"""
import binascii
import logging
import random
import re

import trio
from multiaddr import Multiaddr
from libp2p.io.trio import TrioTCPStream
from libp2p.network.connection.raw_connection import RawConnection
from libp2p.transport.exceptions import OpenConnectionError
from libp2p.transport.tcp.tcp import TCP

_FINAL_LINE_RE = re.compile(r"\d{3} [^\r\n]*\r\n$")  # "250 OK", "515 Authentication failed", etc. -- not "250-..." continuations


class TorSocksTransport(TCP):
    """libp2p transport for /onion and /onion3 addresses via SOCKS5.

    The destination is sent as a domain name so Tor resolves the onion
    address inside the proxy.  Normal IP/DNS TCP addresses remain owned by
    libp2p's regular TCP transport.
    """

    def __init__(self, proxy_ip: str = "127.0.0.1", proxy_port: int = 9050):
        super().__init__()
        self.proxy_ip = proxy_ip
        self.proxy_port = proxy_port

    def can_dial(self, maddr: Multiaddr) -> bool:
        return any(protocol.name in {"onion", "onion3"} for protocol in maddr.protocols())

    def can_listen(self, maddr: Multiaddr) -> bool:
        return False

    def protocols(self) -> list[str]:
        return ["onion", "onion3"]

    async def dial(self, maddr: Multiaddr):
        protocols = {protocol.name for protocol in maddr.protocols()}
        protocol = "onion3" if "onion3" in protocols else "onion"
        target = maddr.value_for_protocol(protocol)
        if not target or ":" not in target:
            raise OpenConnectionError("Invalid Tor onion multiaddr: %s" % maddr)
        target_host, target_port = target.rsplit(":", 1)
        try:
            target_port = int(target_port)
            if not 1 <= target_port <= 65535:
                raise ValueError
        except ValueError as err:
            raise OpenConnectionError("Invalid Tor onion port: %s" % target) from err
        if len(target_host) > 255:
            raise OpenConnectionError("Invalid Tor onion hostname: %s" % target_host)

        try:
            stream = await trio.open_tcp_stream(self.proxy_ip, self.proxy_port)
            await stream.send_all(b"\x05\x01\x00")  # SOCKS5, one method, no auth
            greeting = await self._receive_exactly(stream, 2)
            if greeting != b"\x05\x00":
                raise OpenConnectionError("Tor SOCKS5 proxy requires unsupported authentication")
            host_bytes = target_host.encode("idna")
            request = b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + target_port.to_bytes(2, "big")
            await stream.send_all(request)
            header = await self._receive_exactly(stream, 4)
            if header[0] != 5 or header[1] != 0:
                raise OpenConnectionError("Tor SOCKS5 CONNECT failed (reply=%d)" % header[1])
            address_length = {1: 4, 4: 16}.get(header[3])
            if address_length is None:
                address_length = (await self._receive_exactly(stream, 1))[0]
            await self._receive_exactly(stream, address_length + 2)
            return RawConnection(TrioTCPStream(stream), True)
        except OpenConnectionError:
            raise
        except (OSError, trio.TooSlowError, trio.BrokenResourceError, trio.ClosedResourceError) as err:
            raise OpenConnectionError("Tor SOCKS5 connection failed: %s" % err) from err

    @staticmethod
    async def _receive_exactly(stream: trio.SocketStream, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            chunk = await stream.receive_some(count - len(data))
            if not chunk:
                raise OpenConnectionError("Tor SOCKS5 proxy closed the connection")
            data.extend(chunk)
        return bytes(data)


class TorManager:
    def __init__(self, control_ip: str = "127.0.0.1", control_port: int = 9051,
                 fileserver_port: int = 15441, password: str | None = None,
                 hs_limit: int = 10, always_different_onions: bool = False):
        self.control_ip = control_ip
        self.control_port = control_port
        self.fileserver_port = fileserver_port
        self.password = password
        self.hs_limit = hs_limit
        self.always_different_onions = always_different_onions

        self.log = logging.getLogger("P2P.TorManager")
        self.privatekeys: dict[str, str] = {}  # onion address -> ed25519 privatekey
        self.site_onions: dict[str, str] = {}  # site address (or "global") -> onion address
        self.status = "Waiting"
        self.enabled = True
        self._stream: trio.SocketStream | None = None
        self._lock = trio.Lock()  # Guards the control connection (connect/send)
        self._onion_lock = trio.Lock()  # Guards getOnion()'s create-if-missing check, separate from
        # _lock since getOnion() -> addOnion() -> request() needs _lock too, and trio.Lock isn't
        # reentrant (unlike the original's gevent.lock.RLock -- caught by a real re-acquire test failure)

    def setStatus(self, status: str) -> None:
        self.status = status

    async def start(self) -> bool:
        """Try to connect to the control port; disables this manager on
        any failure rather than falling back to spawning a bundled Tor
        client (see module docstring)."""
        return await self.connect()

    async def connect(self) -> bool:
        self.site_onions = {}
        self.privatekeys = {}
        async with self._lock:
            return await self._connectControllerLocked()

    async def _connectControllerLocked(self) -> bool:
        """Caller must already hold self._lock -- shared by connect() and
        request() (which needs to reconnect-on-demand from inside its own
        already-held lock; trio.Lock isn't reentrant, unlike the
        original's gevent.lock.RLock, so the lock has to be acquired
        exactly once per call chain, not per method)."""
        try:
            stream = await trio.open_tcp_stream(self.control_ip, self.control_port)
        except OSError as err:
            self._stream = None
            self.setStatus("Error (%s)" % err)
            self.enabled = False
            return False

        self._stream = stream
        res_protocol = await self._send("PROTOCOLINFO", stream)
        cookie_match = re.search('COOKIEFILE="(.*?)"', res_protocol)

        if self.password:
            res_auth = await self._send('AUTHENTICATE "%s"' % self.password, stream)
        elif cookie_match:
            cookie_file = cookie_match.group(1).encode("ascii").decode("unicode_escape")
            try:
                with open(cookie_file, "rb") as f:
                    auth_hex = binascii.b2a_hex(f.read())
            except OSError as err:
                return await self._failConnect("cookie file: %s" % err)
            res_auth = await self._send("AUTHENTICATE %s" % auth_hex.decode("utf8"), stream)
        else:
            res_auth = await self._send("AUTHENTICATE", stream)

        if "250 OK" not in res_auth:
            return await self._failConnect("Authenticate error %s" % res_auth)

        res_version = await self._send("GETINFO version", stream)
        match = re.search(r"version=([0-9.]+)", res_version)
        version = match.group(1) if match else "0"
        if float(version.replace(".", "0", 2)) < 207.5:
            return await self._failConnect("Tor version >=0.2.7.5 required, found: %s" % version)

        self.setStatus("Connected (%s)" % res_auth.strip())
        return True

    async def _failConnect(self, reason: str) -> bool:
        await self._closeStream()
        self.setStatus("Error (%s)" % reason)
        self.enabled = False
        return False

    async def _closeStream(self) -> None:
        if self._stream is not None:
            try:
                await self._stream.aclose()
            except trio.BrokenResourceError:
                pass
        self._stream = None

    async def disconnect(self) -> None:
        await self._closeStream()

    async def _send(self, cmd: str, stream: trio.SocketStream | None = None) -> str:
        stream = stream or self._stream
        self.log.debug("> %s", cmd)
        await stream.send_all(("%s\r\n" % cmd).encode("utf8"))
        back = ""
        while not _FINAL_LINE_RE.search(back):
            chunk = await stream.receive_some(1024 * 64)
            if not chunk:
                break
            back += chunk.decode("utf8")
        self.log.debug("< %s", back.strip())
        return back

    async def request(self, cmd: str) -> str:
        async with self._lock:
            if not self.enabled:
                return ""
            if self._stream is None:
                if not await self._connectControllerLocked():
                    return ""
            return await self._send(cmd)

    async def resetCircuits(self) -> None:
        res = await self.request("SIGNAL NEWNYM")
        if "250 OK" not in res:
            self.setStatus("Reset circuits error (%s)" % res.strip())
            self.log.error("Tor reset circuits error: %s", res)

    async def addOnion(self) -> str | None:
        if len(self.privatekeys) >= self.hs_limit:
            candidates = [key for key in self.privatekeys if key != self.site_onions.get("global")]
            return random.choice(candidates) if candidates else None

        result = await self._makeOnionAndKey()
        if not result:
            return None
        onion_address, onion_privatekey = result
        self.privatekeys[onion_address] = onion_privatekey
        self.setStatus("OK (%s onions running)" % len(self.privatekeys))
        return onion_address

    async def _makeOnionAndKey(self) -> tuple[str, str] | None:
        res = await self.request("ADD_ONION NEW:ED25519-V3 port=%s" % self.fileserver_port)
        match = re.search(r"ServiceID=([A-Za-z0-9]+).*PrivateKey=ED25519-V3:(.*?)[\r\n]", res, re.DOTALL)
        if match:
            return match.groups()
        self.setStatus("AddOnion error (%s)" % res.strip())
        self.log.error("Tor addOnion error: %s", res)
        return None

    async def delOnion(self, address: str) -> bool:
        res = await self.request("DEL_ONION %s" % address)
        if "250 OK" in res:
            del self.privatekeys[address]
            self.setStatus("OK (%s onion running)" % len(self.privatekeys))
            return True
        self.setStatus("DelOnion error (%s)" % res.strip())
        self.log.error("Tor delOnion error: %s", res)
        await self.disconnect()
        return False

    def getPrivatekey(self, address: str) -> str:
        return self.privatekeys[address]

    async def getOnion(self, site_address: str) -> str | None:
        if not self.enabled:
            return None

        if self.always_different_onions:
            onion = self.site_onions.get(site_address)
        else:
            onion = self.site_onions.get("global")
            site_address = "global"

        if not onion:
            async with self._onion_lock:
                onion = self.site_onions.get(site_address)  # Recheck under lock
                if not onion:
                    onion = await self.addOnion()
                    if onion:
                        self.site_onions[site_address] = onion
                        self.log.debug("Created new hidden service for %s: %s", site_address, onion)
        return onion
