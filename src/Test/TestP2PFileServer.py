import pathlib
import tempfile

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from P2P.FileServer import FileServer
from P2P.Peer import Peer
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.Site import Site
from P2P import compat


def _random_peer_id_str() -> str:
    return ID.from_pubkey(create_new_key_pair().public_key).to_base58()


class TestP2PFileServer:
    def testGetFileForKnownServingSite(self):
        content = b"hello from FileServer"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                site_root = pathlib.Path(site_dir)
                (site_root / "content.json").write_bytes(content)

                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(Site("1Site", site_root))

                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(server_a.host.peer_id, host_b, policy)
                    buff = await peer.getFile("1Site", "content.json")
                    return buff.read()

        assert compat.run(scenario) == content

    def testGetFileForUnknownSiteErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(server_a.host.peer_id, host_b, policy)
                    return await peer.request("getFile", {"site": "1Unknown", "inner_path": "x", "location": 0})

        response = compat.run(scenario)
        assert response == {"error": "Unknown site"}

    def testGetFileForNonServingSiteErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                site_root = pathlib.Path(site_dir)
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(Site("1Site", site_root, serving=False))
                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(server_a.host.peer_id, host_b, policy)
                    return await peer.request("getFile", {"site": "1Site", "inner_path": "content.json", "location": 0})

        response = compat.run(scenario)
        assert response == {"error": "Unknown site"}

    def testPexRoundTripUpdatesRealSite(self):
        candidate_id = _random_peer_id_str()
        requester_id = _random_peer_id_str()

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                site_root = pathlib.Path(site_dir)
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site("1Site", site_root)
                # Pre-seed a known peer on A's site so pex has something to hand back.
                site_a.addPeer(ID.from_base58(candidate_id), "1.1.1.1", 1111, source="tracker")
                server_a.addSite(site_a)
                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(server_a.host.peer_id, host_b, policy)
                    back_peers = await peer.pex("1Site", [{"peer_id": requester_id, "ip": "9.9.9.9", "port": 3333}])
                    return back_peers, site_a.peers

        back_peers, site_a_peers = compat.run(scenario)
        assert back_peers == [{"peer_id": candidate_id, "ip": "1.1.1.1", "port": 1111}]
        assert requester_id in site_a_peers  # the requester got added back via addPeer()
        assert site_a_peers[requester_id].ip == "9.9.9.9"

    def testAddAndRemoveSite(self):
        server = FileServer(pathlib.Path(tempfile.mkdtemp()), ws_port=None)
        site = Site("1Site", pathlib.Path("/tmp/whatever"))
        server.addSite(site)
        assert "1Site" in server.sites
        server.removeSite("1Site")
        assert "1Site" not in server.sites
