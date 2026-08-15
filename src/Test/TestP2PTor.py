"""Tests P2P.Tor.TorManager against a real trio TCP server speaking a
minimal but faithful subset of the Tor control-port protocol -- no real
`tor` binary is available in this environment (or most CI), so this is
the honest substitute: real sockets, real line protocol, not a mocked
Python object standing in for TorManager's own logic."""
import pathlib
import re
import tempfile

import trio

from P2P.Tor import TorManager
from P2P import compat


class _FakeTorControlServer:
    """Understands PROTOCOLINFO, AUTHENTICATE, GETINFO version, ADD_ONION,
    DEL_ONION, SIGNAL NEWNYM -- enough of the real protocol to exercise
    TorManager's control flow end to end."""

    def __init__(self, cookie_file: pathlib.Path | None = None, version: str = "0.4.7.13",
                 fail_auth: bool = False):
        self.cookie_file = cookie_file
        self.version = version
        self.fail_auth = fail_auth
        self._onion_counter = 0

    async def serve(self, stream: trio.SocketStream) -> None:
        buf = b""
        while True:
            chunk = await stream.receive_some(4096)
            if not chunk:
                return
            buf += chunk
            while b"\r\n" in buf:
                line, buf = buf.split(b"\r\n", 1)
                await self._handle(line.decode("utf8"), stream)

    async def _handle(self, line: str, stream: trio.SocketStream) -> None:
        if line == "PROTOCOLINFO":
            if self.cookie_file:
                await stream.send_all(('250-COOKIEFILE="%s"\r\n250 OK\r\n' % self.cookie_file).encode())
            else:
                await stream.send_all(b"250 OK\r\n")
        elif line.startswith("AUTHENTICATE"):
            if self.fail_auth:
                await stream.send_all(b"515 Authentication failed\r\n")
            else:
                await stream.send_all(b"250 OK\r\n")
        elif line == "GETINFO version":
            await stream.send_all(("250-version=%s\r\n250 OK\r\n" % self.version).encode())
        elif line.startswith("ADD_ONION"):
            self._onion_counter += 1
            service_id = "fakeonion%d" % self._onion_counter
            await stream.send_all(
                ("250-ServiceID=%s\r\n250-PrivateKey=ED25519-V3:fakekey%d\r\n250 OK\r\n"
                 % (service_id, self._onion_counter)).encode()
            )
        elif line.startswith("DEL_ONION"):
            await stream.send_all(b"250 OK\r\n")
        elif line == "SIGNAL NEWNYM":
            await stream.send_all(b"250 OK\r\n")
        else:
            await stream.send_all(b"510 Unrecognized command\r\n")


async def _startFakeServer(nursery, **server_kwargs):
    server = _FakeTorControlServer(**server_kwargs)

    async def _serve(*, task_status=trio.TASK_STATUS_IGNORED):
        await trio.serve_tcp(server.serve, 0, host="127.0.0.1", task_status=task_status)

    listeners = await nursery.start(_serve)
    port = listeners[0].socket.getsockname()[1]
    return port


class TestP2PTor:
    def testConnectWithNoCookieOrPassword(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery)
                manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                connected = await manager.connect()
                status = manager.status
                nursery.cancel_scope.cancel()
                return connected, status

        connected, status = compat.run(scenario)
        assert connected is True
        assert status.startswith("Connected")

    def testConnectWithCookieFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                cookie_path = pathlib.Path(d) / "control_auth_cookie"
                cookie_path.write_bytes(b"\x01\x02\x03\x04")

                async with trio.open_nursery() as nursery:
                    port = await _startFakeServer(nursery, cookie_file=cookie_path)
                    manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                    connected = await manager.connect()
                    nursery.cancel_scope.cancel()
                    return connected

        assert compat.run(scenario) is True

    def testConnectFailsOnBadAuth(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery, fail_auth=True)
                manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                connected = await manager.connect()
                enabled = manager.enabled
                status = manager.status
                nursery.cancel_scope.cancel()
                return connected, enabled, status

        connected, enabled, status = compat.run(scenario)
        assert connected is False
        assert enabled is False
        assert "Error" in status

    def testConnectFailsOnOldVersion(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery, version="0.2.0.1")
                manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                connected = await manager.connect()
                nursery.cancel_scope.cancel()
                return connected

        assert compat.run(scenario) is False

    def testConnectFailsWhenNoServerListening(self):
        async def scenario():
            manager = TorManager(control_ip="127.0.0.1", control_port=1, fileserver_port=15441)
            return await manager.connect()

        connected = compat.run(scenario)
        assert connected is False

    def testGetOnionCreatesAndReusesGlobalOnion(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery)
                manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                await manager.connect()

                onion_a = await manager.getOnion("1SiteAddressAAAAAAAAAAAAAAAA")
                onion_b = await manager.getOnion("1SiteAddressBBBBBBBBBBBBBBBB")  # Same global onion
                nursery.cancel_scope.cancel()
                return onion_a, onion_b

        onion_a, onion_b = compat.run(scenario)
        assert onion_a is not None
        assert onion_a == onion_b  # always_different_onions=False by default

    def testGetOnionCreatesSeparateOnionsWhenAlwaysDifferent(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery)
                manager = TorManager(
                    control_ip="127.0.0.1", control_port=port, fileserver_port=15441,
                    always_different_onions=True,
                )
                await manager.connect()

                onion_a = await manager.getOnion("1SiteAddressAAAAAAAAAAAAAAAA")
                onion_b = await manager.getOnion("1SiteAddressBBBBBBBBBBBBBBBB")
                nursery.cancel_scope.cancel()
                return onion_a, onion_b

        onion_a, onion_b = compat.run(scenario)
        assert onion_a != onion_b

    def testDelOnionRemovesPrivatekey(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery)
                manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                await manager.connect()

                onion = await manager.getOnion("1SiteAddressAAAAAAAAAAAAAAAA")
                deleted = await manager.delOnion(onion)
                still_present = onion in manager.privatekeys
                nursery.cancel_scope.cancel()
                return deleted, still_present

        deleted, still_present = compat.run(scenario)
        assert deleted is True
        assert still_present is False

    def testResetCircuitsSendsSignalNewnym(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery)
                manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                await manager.connect()
                await manager.resetCircuits()
                status = manager.status
                nursery.cancel_scope.cancel()
                return status

        status = compat.run(scenario)
        assert "Reset circuits error" not in status  # No error path taken

    def testGetPrivatekeyReturnsStoredKey(self):
        async def scenario():
            async with trio.open_nursery() as nursery:
                port = await _startFakeServer(nursery)
                manager = TorManager(control_ip="127.0.0.1", control_port=port, fileserver_port=15441)
                await manager.connect()
                onion = await manager.getOnion("1SiteAddressAAAAAAAAAAAAAAAA")
                key = manager.getPrivatekey(onion)
                nursery.cancel_scope.cancel()
                return key

        key = compat.run(scenario)
        assert re.match(r"^fakekey\d+$", key)
