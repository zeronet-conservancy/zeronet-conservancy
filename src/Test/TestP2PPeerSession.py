import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.ProtocolRouter import ProtocolRouter
from P2P.PeerSession import PeerSession
from P2P.protocols import getfile, pex, ping
from P2P import compat


def _make_router(host):
    router = ProtocolRouter(host)
    router.register(ping.PROTOCOL_ID, ping.handle)
    router.register(getfile.PROTOCOL_ID, getfile.make_handler(lambda addr: None))
    router.register(pex.PROTOCOL_ID, pex.make_handler(lambda *a: [], lambda *a: None))
    return router


class TestP2PPeerSession:
    def testPing(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    session = PeerSession(host_b, host_a.peer_id)
                    result = await session.ping()
                    return result, session.last_ping_delay

        ok, delay = compat.run(scenario)
        assert ok is True
        assert delay is not None and delay >= 0

    def testUnknownCommandReturnsError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    session = PeerSession(host_b, host_a.peer_id)
                    return await session.request("totallyMadeUpCommand")

        response = compat.run(scenario)
        assert response == {"error": "Unknown command: totallyMadeUpCommand"}

    def testBadActionAndGoodActionTrackReputation(self):
        session = PeerSession(host=None, peer_id=None)
        assert session.bad_actions == 0
        session.badAction()
        session.badAction(4)
        assert session.bad_actions == 5
        session.goodAction()
        assert session.bad_actions == 0

    def testRequestUpdatesLastCmdSent(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    session = PeerSession(host_b, host_a.peer_id)
                    assert session.last_cmd_sent is None
                    await session.request("ping")
                    return session.last_cmd_sent

        assert compat.run(scenario) == "ping"
