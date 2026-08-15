import json
import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from Crypt import CryptBitcoin
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.FileServer import FileServer
from P2P.Peer import Peer
from P2P.Site import Site
from P2P.WorkerManager import publishUpdate
from P2P import compat


async def _signedSite(site_root, address, privatekey, modified_offset=0):
    site = Site(address, site_root)
    content = await site.content_manager.sign(privatekey)
    if modified_offset:
        content["modified"] += modified_offset
        content.pop("signs", None)
        sign_content = json.dumps(content, sort_keys=True)
        content["signs"] = {address: CryptBitcoin.sign(sign_content, privatekey)}
        await site.storage.writeJson("content.json", content)
        site.content_manager.contents["content.json"] = content
    return site


class TestP2PUpdateProtocol:
    def testPushUpdateAppliesNewerValidContent(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_a_dir, tempfile.TemporaryDirectory() as site_b_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                site_a = await _signedSite(pathlib.Path(site_a_dir), address, privatekey)
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(site_a)

                # site_b has a newer version of the same site's content.json
                site_b = await _signedSite(pathlib.Path(site_b_dir), address, privatekey, modified_offset=100)
                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    peer = Peer(server_a.host.peer_id, host_b, ConnectionPolicy(host_b))

                    body = json.dumps(site_b.content_manager.contents["content.json"]).encode("utf8")
                    reply = await peer.pushUpdate(address, "content.json", body)

                    on_disk = await site_a.storage.loadJson("content.json")
                    return reply, on_disk["modified"], site_a.content_manager.contents["content.json"]["modified"]

        reply, disk_modified, cached_modified = compat.run(scenario)
        assert "ok" in reply
        assert disk_modified == cached_modified

    def testPushUpdateRejectsOlderOrSameContent(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                site_a = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                original_modified = site_a.content_manager.contents["content.json"]["modified"]
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(site_a)

                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    peer = Peer(server_a.host.peer_id, host_b, ConnectionPolicy(host_b))

                    # Re-send the SAME content (same "modified") site_a already has
                    body = json.dumps(site_a.content_manager.contents["content.json"]).encode("utf8")
                    reply = await peer.pushUpdate(address, "content.json", body)
                    return reply, site_a.content_manager.contents["content.json"]["modified"], original_modified

        reply, modified_after, original_modified = compat.run(scenario)
        assert "error" not in reply
        assert "not updated" in reply.get("ok", "")
        assert modified_after == original_modified

    def testPushUpdateRejectsInvalidSignature(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                site_a = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(site_a)

                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    peer = Peer(server_a.host.peer_id, host_b, ConnectionPolicy(host_b))

                    forged = dict(site_a.content_manager.contents["content.json"])
                    forged["modified"] += 1000
                    forged["title"] = "forged"
                    # No re-sign -- signature no longer matches the tampered content
                    body = json.dumps(forged).encode("utf8")
                    return await peer.pushUpdate(address, "content.json", body)

        reply = compat.run(scenario)
        assert "error" in reply

    def testPushUpdateRejectsUnknownSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                server_a = FileServer(pathlib.Path(da), ws_port=None)  # No sites added
                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    peer = Peer(server_a.host.peer_id, host_b, ConnectionPolicy(host_b))
                    return await peer.pushUpdate("1UnknownSiteAddress", "content.json", b"{}")

        reply = compat.run(scenario)
        assert reply["error"] == "Unknown site"

    def testPushUpdateRejectsNonContentJsonPath(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site_a = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(site_a)

                host_b = FileServer(pathlib.Path(db), ws_port=None).host

                async with server_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    peer = Peer(server_a.host.peer_id, host_b, ConnectionPolicy(host_b))
                    return await peer.pushUpdate(address, "data/somefile.json", b"{}")

        reply = compat.run(scenario)
        assert "Only content.json" in reply["error"]


class TestP2PPublishUpdate:
    def testPublishUpdatePushesToRealPeerAndCountsSuccess(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as site_a_dir, tempfile.TemporaryDirectory() as site_b_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                # site_a: the publisher, has the newer signed content
                site_a = await _signedSite(pathlib.Path(site_a_dir), address, privatekey, modified_offset=100)
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(site_a)

                # site_b: the receiving peer, has the older version and is serving it
                site_b = await _signedSite(pathlib.Path(site_b_dir), address, privatekey)
                server_b = FileServer(pathlib.Path(db), ws_port=None)
                server_b.addSite(site_b)

                async with server_a.run(), server_b.run():
                    await server_a.host.connect(PeerInfo(server_b.host.peer_id, server_b.host.get_addrs()))
                    peer_b = Peer(server_b.host.peer_id, server_a.host, server_a.connection_policy)

                    published = await publishUpdate(site_a, [peer_b])
                    on_disk = await site_b.storage.loadJson("content.json")
                    return published, on_disk["modified"], site_a.content_manager.contents["content.json"]["modified"]

        published, disk_modified, published_modified = compat.run(scenario)
        assert published == 1
        assert disk_modified == published_modified

    def testPublishUpdateRaisesWithoutLoadedContent(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                site = Site("1TestNoContentSiteAAAAAAAAAA", pathlib.Path(d))
                try:
                    await publishUpdate(site, [])
                    return "no-error"
                except ValueError:
                    return "raised"

        assert compat.run(scenario) == "raised"
