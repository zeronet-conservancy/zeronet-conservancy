import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.ProtocolRouter import ProtocolRouter
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.Peer import Peer
from P2P.protocols import getfile, pex, ping
from P2P import compat


def _make_router(host, site_root_resolver=None, known_peers_provider=None, peer_received_callback=None):
    router = ProtocolRouter(host)
    router.register(ping.PROTOCOL_ID, ping.handle)
    router.register(getfile.PROTOCOL_ID, getfile.make_handler(site_root_resolver or (lambda addr: None)))
    router.register(pex.PROTOCOL_ID, pex.make_handler(
        known_peers_provider or (lambda *a: []),
        peer_received_callback or (lambda *a: None),
    ))
    return router


class TestP2PPeer:
    def testPing(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(host_a.peer_id, host_b, policy)
                    return await peer.ping()

        assert compat.run(scenario) is True

    def testGetFileSingleChunk(self):
        content = b"small file content"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                site_root = pathlib.Path(site_dir)
                (site_root / "data.json").write_bytes(content)

                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a, site_root_resolver=lambda addr: site_root if addr == "1Site" else None)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(host_a.peer_id, host_b, policy)
                    buff = await peer.getFile("1Site", "data.json")
                    return buff.read()

        assert compat.run(scenario) == content

    def testGetFileMultiChunk(self):
        # Bigger than Peer.MAX_READ_SIZE (512KB) so getFile has to loop
        # across several requests, exercising the location/read_bytes
        # continuation logic instead of finishing in one shot.
        content = (b"chunked-content-" * 40000)  # ~680KB

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                site_root = pathlib.Path(site_dir)
                (site_root / "big.bin").write_bytes(content)

                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a, site_root_resolver=lambda addr: site_root if addr == "1Site" else None)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(host_a.peer_id, host_b, policy)
                    # small MAX_READ_SIZE substitute via pos_to chunking isn't exposed,
                    # so drive it directly through multiple manual requests instead:
                    buff = await peer.getFile("1Site", "big.bin")
                    return buff.read()

        assert compat.run(scenario) == content

    def testPex(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a, known_peers_provider=lambda *a: [{"ip": "1.1.1.1", "port": 80}])

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(host_a.peer_id, host_b, policy)
                    return await peer.pex("1Site", [])

        assert compat.run(scenario) == [{"ip": "1.1.1.1", "port": 80}]

    def testSessionReusedAcrossCalls(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(host_a.peer_id, host_b, policy)
                    await peer.ping()
                    await peer.ping()
                    return len(policy.sessions)

        assert compat.run(scenario) == 1
