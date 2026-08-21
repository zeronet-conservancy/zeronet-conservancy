import pathlib
import tempfile

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.ProtocolRouter import ProtocolRouter
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.Peer import Peer
from P2P.SiteStorage import SiteStorage
from P2P.protocols import getfile, pex, ping
from P2P import compat


def _make_router(host, site_storage_resolver=None, known_peers_provider=None, peer_received_callback=None):
    router = ProtocolRouter(host)
    router.register(ping.PROTOCOL_ID, ping.handle)
    router.register(getfile.PROTOCOL_ID, getfile.make_handler(site_storage_resolver or (lambda addr: None)))
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
                storage = SiteStorage(site_root)

                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a, site_storage_resolver=lambda addr: storage if addr == "1Site" else None)

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
                storage = SiteStorage(site_root)

                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a, site_storage_resolver=lambda addr: storage if addr == "1Site" else None)

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
        candidate_id = ID.from_pubkey(create_new_key_pair().public_key).to_base58()

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                _make_router(host_a, known_peers_provider=lambda *a: [
                    {"peer_id": candidate_id, "ip": "1.1.1.1", "port": 80}
                ])

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(host_a.peer_id, host_b, policy)
                    return await peer.pex("1Site", [])

        assert compat.run(scenario) == [{"peer_id": candidate_id, "ip": "1.1.1.1", "port": 80}]

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

    def testGetFileRangeReconstructsPieceByPieceOutOfOrder(self):
        """Bigfile scoping's "Layer A" end to end: the wire protocol's
        existing pos_from/pos_to range support (Peer.getFile()) composed
        with SiteStorage's new createSparseFile()/writeRange() -- a
        downloader fetching three independent byte ranges out of order
        and reconstructing the exact original file locally, with no
        piece hashing/piecefields/scheduling involved yet (those are
        still-open Layers B-D)."""
        piece_a = b"A" * 100
        piece_b = b"B" * 100
        piece_c = b"C" * 100
        content = piece_a + piece_b + piece_c

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as seed_dir, tempfile.TemporaryDirectory() as dl_dir:
                seed_storage = SiteStorage(pathlib.Path(seed_dir))
                await seed_storage.write("big.bin", content)
                download_storage = SiteStorage(pathlib.Path(dl_dir))

                host_a = Host(pathlib.Path(da), ws_port=None)  # seeder
                host_b = Host(pathlib.Path(db), ws_port=None)  # downloader
                _make_router(host_a, site_storage_resolver=lambda addr: seed_storage if addr == "1Site" else None)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(host_a.peer_id, host_b, policy)

                    download_storage.createSparseFile("big.bin", len(content))

                    # Fetch the middle piece first, then last, then first --
                    # deliberately out of order, like real peer-piece
                    # scheduling would produce.
                    for pos_from, pos_to in [(100, 200), (200, 300), (0, 100)]:
                        buff = await peer.getFile("1Site", "big.bin", pos_from=pos_from, pos_to=pos_to)
                        await download_storage.writeRange("big.bin", pos_from, buff.read())

                    return await download_storage.read("big.bin")

        assert compat.run(scenario) == content
