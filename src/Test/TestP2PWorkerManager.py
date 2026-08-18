import json
import pathlib
import tempfile
import time

from libp2p.peer.peerinfo import PeerInfo

from Crypt import CryptBitcoin
from P2P.Host import Host
from P2P.FileServer import FileServer
from P2P.Site import Site
from P2P.Peer import Peer
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.WorkerManager import syncSite, fetchAndVerify, downloadContentJson, publishGossip, NoPeerHadFileError
from P2P import compat


def _sign(content, privatekey):
    sign_content = json.dumps(content, sort_keys=True)
    content = dict(content)
    content["signs"] = {CryptBitcoin.privatekeyToAddress(privatekey): CryptBitcoin.sign(sign_content, privatekey)}
    return content


class TestP2PWorkerManager:
    """Phase 6 end-to-end milestone: two full nodes -- real FileServer/Site
    stack, not scripts -- propagate a real site update: node A publishes,
    node B discovers it, pulls changed files via getFile, and its content
    hash matches node A's. Runs under trio.run() (P2P.compat.run in this
    transition period) with no gevent import anywhere in the call path.
    """

    def testFullSiteUpdatePropagates(self):
        privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(privatekey)
        data_content = b"Hello from node A's real, signed site update!"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:

                # --- Node A: publish a real signed site ---
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                server_a.addSite(site_a)

                await site_a.storage.write("data.json", data_content)
                content = {
                    "address": site_address,
                    "modified": time.time(),
                    "files": {"data.json": {"sha512": _sha512(data_content), "size": len(data_content)}},
                }
                signed_content = _sign(content, privatekey)
                # Apply it to A's own content_manager/storage exactly like a
                # real publish would, so A can actually serve it via getFile.
                assert site_a.content_manager.verifyContentJson(signed_content) is True
                site_a.content_manager.contents["content.json"] = signed_content
                await site_a.storage.writeJson("content.json", signed_content)

                # --- Node B: fresh, knows nothing about this site yet ---
                server_b = FileServer(pathlib.Path(db), ws_port=None)
                site_b = Site(site_address, pathlib.Path(root_b))

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy_b = ConnectionPolicy(server_b.host)
                    peer_a_from_b = Peer(server_a.host.peer_id, server_b.host, policy_b)

                    updated = await syncSite(site_b, [peer_a_from_b])

                    return updated, site_b.content_manager.contents.get("content.json"), await site_b.storage.read("data.json")

        updated, synced_content, synced_data = compat.run(scenario)
        assert updated == ["data.json"]
        assert synced_data == data_content
        assert synced_content["files"]["data.json"]["size"] == len(data_content)

    def testSecondSyncIsNoOpWhenUnchanged(self):
        privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(privatekey)
        data_content = b"unchanged content"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                server_a.addSite(site_a)

                await site_a.storage.write("data.json", data_content)
                content = {
                    "address": site_address,
                    "modified": time.time(),
                    "files": {"data.json": {"sha512": _sha512(data_content), "size": len(data_content)}},
                }
                signed_content = _sign(content, privatekey)
                site_a.content_manager.verifyContentJson(signed_content)
                site_a.content_manager.contents["content.json"] = signed_content
                await site_a.storage.writeJson("content.json", signed_content)

                server_b = FileServer(pathlib.Path(db), ws_port=None)
                site_b = Site(site_address, pathlib.Path(root_b))

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy_b = ConnectionPolicy(server_b.host)
                    peer_a_from_b = Peer(server_a.host.peer_id, server_b.host, policy_b)

                    first = await syncSite(site_b, [peer_a_from_b])
                    second = await syncSite(site_b, [peer_a_from_b])
                    return first, second

        first, second = compat.run(scenario)
        assert first == ["data.json"]
        assert second == []  # nothing changed since -- content.json's "modified" matched, no re-fetch

    def testSyncSiteSkipsFileRefusedByPluginButSyncsRest(self):
        """syncSite() routes every file through site.needFile() now (see
        that function's own docstring) -- a plugin's own per-file refusal
        (e.g. ContentFilter's mute check) should skip just that one file,
        not abort the whole sync. RefusingSite stands in for any such
        plugin override generically, proving the WorkerManager-level
        contract independent of ContentFilter specifically (that plugin's
        own real needFile() override is tested end-to-end in
        TestP2PPluginsContentFilter.py)."""
        privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(privatekey)
        allowed_content = b"allowed file"
        refused_content = b"refused file"

        class RefusingSite(Site):
            async def needFile(self, inner_path, peers, priority=0, timeout=60):
                if inner_path == "refused.json":
                    raise PermissionError("refused: %s" % inner_path)
                return await super().needFile(inner_path, peers, priority=priority, timeout=timeout)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                server_a.addSite(site_a)

                await site_a.storage.write("allowed.json", allowed_content)
                await site_a.storage.write("refused.json", refused_content)
                content = {
                    "address": site_address,
                    "modified": time.time(),
                    "files": {
                        "allowed.json": {"sha512": _sha512(allowed_content), "size": len(allowed_content)},
                        "refused.json": {"sha512": _sha512(refused_content), "size": len(refused_content)},
                    },
                }
                signed_content = _sign(content, privatekey)
                site_a.content_manager.contents["content.json"] = signed_content
                await site_a.storage.writeJson("content.json", signed_content)

                server_b = FileServer(pathlib.Path(db), ws_port=None)
                site_b = RefusingSite(site_address, pathlib.Path(root_b))

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy_b = ConnectionPolicy(server_b.host)
                    peer_a_from_b = Peer(server_a.host.peer_id, server_b.host, policy_b)

                    updated = await syncSite(site_b, [peer_a_from_b])
                    return updated, site_b.storage.isFile("allowed.json"), site_b.storage.isFile("refused.json")

        updated, has_allowed, has_refused = compat.run(scenario)
        assert updated == ["allowed.json"]  # Only the non-refused file made it into the return value
        assert has_allowed is True
        assert has_refused is False  # Refused, not partially written either

    def testFetchAndVerifyRejectsTamperedFile(self):
        privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(privatekey)
        real_content = b"real content"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                server_a.addSite(site_a)
                # Serve a file whose actual bytes don't match what we'll
                # claim in content.json -- simulates a malicious/corrupted peer.
                await site_a.storage.write("data.json", b"TAMPERED BYTES, NOT THE REAL CONTENT")

                server_b = FileServer(pathlib.Path(db), ws_port=None)
                site_b = Site(site_address, pathlib.Path(root_b))
                site_b.content_manager.contents["content.json"] = {
                    "files": {"data.json": {"sha512": _sha512(real_content), "size": len(real_content)}},
                }

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy_b = ConnectionPolicy(server_b.host)
                    peer_a_from_b = Peer(server_a.host.peer_id, server_b.host, policy_b)

                    try:
                        await fetchAndVerify(site_b, "data.json", [peer_a_from_b])
                        return "no error raised"
                    except NoPeerHadFileError:
                        return "rejected"

        assert compat.run(scenario) == "rejected"

    def testPublishGossipPublishesLoadedContentToSiteAddress(self):
        """publishGossip() is publishUpdate()'s gossip-side sibling --
        same already-loaded/signed content, published to the site's
        gossip topic (GossipManager.publish(site.address, body)) instead
        of pushed peer-by-peer. A fake stand-in for GossipManager, not a
        real one, since this is about publishGossip()'s own contract
        (what it passes and when), not gossipsub transport -- that's
        covered by TestP2PGossipIntegration.py's real end-to-end case."""
        privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(privatekey)

        class FakeGossipManager:
            def __init__(self):
                self.published = []

            async def publish(self, address, body):
                self.published.append((address, body))

        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site(site_address, pathlib.Path(root))
                content = {"address": site_address, "modified": time.time(), "files": {}}
                signed_content = _sign(content, privatekey)
                site.content_manager.contents["content.json"] = signed_content

                gossip = FakeGossipManager()
                await publishGossip(site, gossip)
                return gossip.published, signed_content

        published, signed_content = compat.run(scenario)
        assert len(published) == 1
        published_address, published_body = published[0]
        assert published_address == site_address
        assert json.loads(published_body) == signed_content

    def testPublishGossipRaisesWithoutLoadedContent(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1UnloadedSiteAddress", pathlib.Path(root))

                class FakeGossipManager:
                    async def publish(self, address, body):
                        pass

                raised = False
                try:
                    await publishGossip(site, FakeGossipManager())
                except ValueError:
                    raised = True
                return raised

        assert compat.run(scenario) is True


def _sha512(data: bytes) -> str:
    from Crypt import CryptHash
    import io
    return CryptHash.sha512sum(io.BytesIO(data))
