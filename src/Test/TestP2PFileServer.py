import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from P2P.FileServer import FileServer
from P2P.Peer import Peer
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P import compat


class FakePeer:
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port


class FakeSite:
    """Minimal duck-typed stand-in for Site.py's real interface, matching
    the methods FileServer actually calls (address, site_root, isServing(),
    getConnectablePeers(), addPeer())."""

    def __init__(self, address, site_root, serving=True):
        self.address = address
        self.site_root = site_root
        self._serving = serving
        self.known_peers = [FakePeer("1.1.1.1", 1111)]
        self.received_peers = []

    def isServing(self):
        return self._serving

    def getConnectablePeers(self, need_num=5, ignore=None):
        ignore = ignore or []
        return [p for p in self.known_peers if (p.ip, p.port) not in ignore][:need_num]

    def addPeer(self, ip, port, source="other"):
        self.received_peers.append((ip, port, source))


class TestP2PFileServer:
    def testGetFileForKnownServingSite(self):
        content = b"hello from FileServer"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                site_root = pathlib.Path(site_dir)
                (site_root / "content.json").write_bytes(content)

                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(FakeSite("1Site", site_root))

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
                server_a.addSite(FakeSite("1Site", site_root, serving=False))
                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(server_a.host.peer_id, host_b, policy)
                    return await peer.request("getFile", {"site": "1Site", "inner_path": "content.json", "location": 0})

        response = compat.run(scenario)
        assert response == {"error": "Unknown site"}

    def testPexRoundTripUpdatesRealSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                site_root = pathlib.Path(site_dir)
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                fake_site_a = FakeSite("1Site", site_root)
                server_a.addSite(fake_site_a)
                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy = ConnectionPolicy(host_b)
                    peer = Peer(server_a.host.peer_id, host_b, policy)
                    back_peers = await peer.pex("1Site", [{"ip": "9.9.9.9", "port": 3333}])
                    return back_peers, fake_site_a.received_peers

        back_peers, received = compat.run(scenario)
        assert back_peers == [{"ip": "1.1.1.1", "port": 1111}]
        assert received == [("9.9.9.9", 3333, "pex")]

    def testAddAndRemoveSite(self):
        server = FileServer(pathlib.Path(tempfile.mkdtemp()), ws_port=None)
        site = FakeSite("1Site", pathlib.Path("/tmp/whatever"))
        server.addSite(site)
        assert "1Site" in server.sites
        server.removeSite("1Site")
        assert "1Site" not in server.sites
