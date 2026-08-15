import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.ProtocolRouter import ProtocolRouter, call
from P2P.SiteStorage import SiteStorage
from P2P import compat
from P2P.protocols import getfile


class TestP2PGetFile:
    """Phase 2 milestone: one libp2p host requests getFile from another and
    receives correct bytes for a real site file, msgpack-encoded, through
    ProtocolRouter + wire.py -- the first ZeroNet command reimplemented as
    a libp2p protocol handler instead of a branch in FileRequest.route().
    """

    def testGetFileRoundTrip(self):
        site_content = b"Hello from a real site file served over libp2p!"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                storage = SiteStorage(pathlib.Path(site_dir))
                await storage.write("content.json", site_content)

                def site_storage_resolver(site_address):
                    if site_address == "1TestSiteAddress":
                        return storage
                    return None

                host_a = Host(pathlib.Path(da))  # server: hosts the site
                host_b = Host(pathlib.Path(db))  # client: requests the file

                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(getfile.PROTOCOL_ID, getfile.make_handler(site_storage_resolver))

                    addrs_a = host_a.get_addrs()
                    await host_b.connect(PeerInfo(host_a.peer_id, addrs_a))

                    response = await call(host_b, host_a.peer_id, getfile.PROTOCOL_ID, {
                        "site": "1TestSiteAddress",
                        "inner_path": "content.json",
                        "location": 0,
                    })
                    return response

        response = compat.run(scenario)
        assert "error" not in response, response
        assert response["body"] == site_content
        assert response["size"] == len(site_content)
        assert response["location"] == len(site_content)

    def testUnknownInnerPathReturnsFileReadError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                storage = SiteStorage(pathlib.Path(site_dir))

                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(getfile.PROTOCOL_ID, getfile.make_handler(lambda addr: storage))
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    return await call(host_b, host_a.peer_id, getfile.PROTOCOL_ID, {
                        "site": "1Site", "inner_path": "missing.json", "location": 0,
                    })

        response = compat.run(scenario)
        assert response == {"error": "File read error"}

    def testTraversalInnerPathReturnsInvalidError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                storage = SiteStorage(pathlib.Path(site_dir))

                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(getfile.PROTOCOL_ID, getfile.make_handler(lambda addr: storage))
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    return await call(host_b, host_a.peer_id, getfile.PROTOCOL_ID, {
                        "site": "1Site", "inner_path": "../../etc/passwd", "location": 0,
                    })

        response = compat.run(scenario)
        assert response == {"error": "Invalid inner_path"}
