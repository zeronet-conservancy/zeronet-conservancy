import json
import pathlib
import tempfile

import trio

from Crypt import CryptBitcoin
from P2P.actions import Actions, ActionError
from P2P import compat


class TestP2PActionsSite:
    def testSiteCreateWithMasterSeedProducesSignedSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                result = await actions.siteCreate()
                site = await actions.site_manager.get(result["address"])
                content = await site.storage.loadJson("content.json")
                return result, site.storage.isFile("index.html"), content

        result, has_index, content = compat.run(scenario)
        assert CryptBitcoin.privatekeyToAddress(result["privatekey"]) == result["address"]
        assert has_index is True
        assert "index.html" in content["files"]
        assert content["postmessage_nonce_security"] is True

    def testSiteCreateStoresPrivatekeyInUsersJson(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                result = await actions.siteCreate()
                user = await actions.user_manager.get()
                return result, user

        result, user = compat.run(scenario)
        assert user.sites[result["address"]]["privatekey"] == result["privatekey"]

    def testSiteCreateWithoutMasterSeedSkipsUserManager(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                result = await actions.siteCreate(use_master_seed=False)
                user = await actions.user_manager.get()
                return result, user

        result, user = compat.run(scenario)
        assert CryptBitcoin.privatekeyToAddress(result["privatekey"]) == result["address"]
        assert user is None

    def testSiteSignWithExplicitPrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                actions.site_manager.add(address)

                succ = await actions.siteSign(address, privatekey=privatekey)
                site = await actions.site_manager.get(address)
                return succ, site.storage.isFile("content.json")

        succ, has_content = compat.run(scenario)
        assert succ is True
        assert has_content is True

    def testSiteSignUsesStoredPrivatekeyFromUser(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                created = await actions.siteCreate()
                # Re-sign without passing privatekey -- must recover it from users.json
                succ = await actions.siteSign(created["address"])
                return succ

        assert compat.run(scenario) is True

    def testSiteSignWithoutPrivatekeyRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                actions.site_manager.add(address)
                try:
                    await actions.siteSign(address)
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testSiteSignUnknownSiteRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                try:
                    await actions.siteSign("1NoSuchSiteAAAAAAAAAAAAAAAA")
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testSiteVerifyAllGoodAfterCreate(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                created = await actions.siteCreate()
                return await actions.siteVerify(created["address"])

        result = compat.run(scenario)
        assert result["bad_files"] == []

    def testSiteVerifyDetectsTamperedFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                created = await actions.siteCreate()
                site = await actions.site_manager.get(created["address"])
                # Tamper with the file's content on disk after signing --
                # hash in content.json no longer matches.
                await site.storage.write("index.html", b"tampered content")
                return await actions.siteVerify(created["address"])

        result = compat.run(scenario)
        assert "index.html" in result["bad_files"]

    def testDbRebuildAndDbQueryRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = actions.site_manager.add(address, own=True)

                schema = {
                    "db_name": "Test", "db_file": "site.db", "version": 1,
                    "maps": {"data\\.json$": {"to_keyvalue": ["title"]}},
                }
                await site.storage.writeJson("dbschema.json", schema)
                await site.storage.writeJson("data.json", {"title": "cli db test"})
                await site.content_manager.sign(privatekey)

                applied = await actions.dbRebuild(address)
                rows = await actions.dbQuery(address, "SELECT * FROM keyvalue WHERE key = 'title'")
                return applied, rows

        applied, rows = compat.run(scenario)
        assert applied is True
        assert rows[0]["value"] == "cli db test"

    def testDbQueryUnknownSiteRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                try:
                    await actions.dbQuery("1NoSuchSiteAAAAAAAAAAAAAAAA", "SELECT 1")
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"


class TestP2PActionsCrypto:
    def testCryptPrivatekeyToAddress(self):
        actions = Actions(pathlib.Path("/tmp"))
        privatekey = CryptBitcoin.newPrivatekey()
        assert actions.cryptPrivatekeyToAddress(privatekey) == CryptBitcoin.privatekeyToAddress(privatekey)

    def testCryptSignAndVerifyRoundTrip(self):
        actions = Actions(pathlib.Path("/tmp"))
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        sign = actions.cryptSign("hello world", privatekey)
        assert actions.cryptVerify("hello world", sign, address) is True
        assert actions.cryptVerify("tampered", sign, address) is False

    def testCryptGetPrivatekeyDeterministic(self):
        actions = Actions(pathlib.Path("/tmp"))
        master_seed = CryptBitcoin.newSeed()
        key1 = actions.cryptGetPrivatekey(master_seed, 0)
        key2 = actions.cryptGetPrivatekey(master_seed, 0)
        key3 = actions.cryptGetPrivatekey(master_seed, 1)
        assert key1 == key2
        assert key1 != key3

    def testCryptGetPrivatekeyRejectsShortSeed(self):
        actions = Actions(pathlib.Path("/tmp"))
        try:
            actions.cryptGetPrivatekey("tooshort")
            assert False, "expected ActionError"
        except ActionError:
            pass


SITE_ADDRESS = "1TestActionsNetSiteAAAAAAAAAAA"[:30]


class TestP2PActionsNetworkingNoPeers:
    """Cases that don't need a real second peer -- error paths and the
    "nothing to announce to" clean-completion path."""

    def testSiteAnnounceWithNoDhtAndNoPeersCompletesCleanly(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                actions.site_manager.add(address)
                return await actions.siteAnnounce(address, enable_dht=False)

        result = compat.run(scenario)
        assert result["peers"] == 0

    def testSiteDownloadRaisesWithoutPeers(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                actions.site_manager.add(address)
                try:
                    await actions.siteDownload(address, enable_dht=False)
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testSiteNeedFileRaisesWithoutPeers(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                actions.site_manager.add(address)
                try:
                    await actions.siteNeedFile(address, "content.json", enable_dht=False)
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"


class TestP2PActionsPeerCommands:
    """peerPing/peerGetFile/peerCmd connect directly via peer_id+multiaddr
    -- real, end-to-end, against a real second FileServer, no DHT needed."""

    def testPeerPingRealRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as ds, tempfile.TemporaryDirectory() as dc:
                from P2P.FileServer import FileServer

                server = FileServer(pathlib.Path(ds), ws_port=None)
                async with server.run():
                    multiaddr = str(server.host.get_addrs()[0])
                    peer_id = server.host.peer_id.to_base58()

                    actions = Actions(pathlib.Path(dc))
                    return await actions.peerPing(peer_id, multiaddr, count=2)

        result = compat.run(scenario)
        assert len(result["results"]) == 2
        assert all(r["ok"] for r in result["results"])

    def testPeerGetFileRealRoundTrip(self):
        content = b'{"hello": "from a real peer"}'

        async def scenario():
            with tempfile.TemporaryDirectory() as ds, tempfile.TemporaryDirectory() as dc, tempfile.TemporaryDirectory() as site_dir:
                from P2P.FileServer import FileServer
                from P2P.Site import Site

                site_root = pathlib.Path(site_dir)
                (site_root / "content.json").write_bytes(content)

                server = FileServer(pathlib.Path(ds), ws_port=None)
                server.addSite(Site(SITE_ADDRESS, site_root))
                async with server.run():
                    multiaddr = str(server.host.get_addrs()[0])
                    peer_id = server.host.peer_id.to_base58()

                    actions = Actions(pathlib.Path(dc))
                    return await actions.peerGetFile(peer_id, multiaddr, SITE_ADDRESS, "content.json")

        result = compat.run(scenario)
        assert result["content"] == content.decode()

    def testPeerCmdRealRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as ds, tempfile.TemporaryDirectory() as dc:
                from P2P.FileServer import FileServer

                server = FileServer(pathlib.Path(ds), ws_port=None)
                async with server.run():
                    multiaddr = str(server.host.get_addrs()[0])
                    peer_id = server.host.peer_id.to_base58()

                    actions = Actions(pathlib.Path(dc))
                    return await actions.peerCmd(peer_id, multiaddr, "ping")

        result = compat.run(scenario)
        assert result == {"body": b"Pong!"}


class TestP2PActionsSiteDownload:
    """Real end-to-end siteDownload()/siteNeedFile(), peer discovery
    bypassed (seeded directly via site.addPeer()) since DHT-based
    discovery is already proven separately in TestP2PKadDHT.py -- this
    tests the CLI's own peer-resolution and fetch wiring."""

    def testSiteDownloadFetchesRealContentFromSeededPeer(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as ds, tempfile.TemporaryDirectory() as dc, \
                    tempfile.TemporaryDirectory() as source_site_dir:
                from P2P.FileServer import FileServer
                from P2P.Site import Site

                source_root = pathlib.Path(source_site_dir)
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                source_site = Site(address, source_root)
                await source_site.storage.write("data.txt", b"hello from source")
                await source_site.content_manager.sign(privatekey)

                source_server = FileServer(pathlib.Path(ds), ws_port=None)
                source_server.addSite(source_site)

                async with source_server.run():
                    multiaddr = source_server.host.get_addrs()[0]
                    tcp_port = multiaddr.value_for_protocol("tcp")

                    actions = Actions(pathlib.Path(dc))
                    await actions.site_manager.load()
                    client_site = actions.site_manager.add(address)
                    client_site.addPeer(source_server.host.peer_id, ip="127.0.0.1", port=int(tcp_port), source="test")

                    return await actions.siteDownload(address, enable_dht=False)

        result = compat.run(scenario)
        assert "data.txt" in result["updated"]

    def testSiteNeedFileFetchesSpecificFileFromSeededPeer(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as ds, tempfile.TemporaryDirectory() as dc, \
                    tempfile.TemporaryDirectory() as source_site_dir:
                from P2P.FileServer import FileServer
                from P2P.Site import Site

                source_root = pathlib.Path(source_site_dir)
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                source_site = Site(address, source_root)
                await source_site.storage.write("data.txt", b"needFile target content")
                await source_site.content_manager.sign(privatekey)

                source_server = FileServer(pathlib.Path(ds), ws_port=None)
                source_server.addSite(source_site)

                async with source_server.run():
                    multiaddr = source_server.host.get_addrs()[0]
                    tcp_port = multiaddr.value_for_protocol("tcp")

                    actions = Actions(pathlib.Path(dc))
                    await actions.site_manager.load()
                    client_site = actions.site_manager.add(address)
                    client_site.addPeer(source_server.host.peer_id, ip="127.0.0.1", port=int(tcp_port), source="test")

                    result = await actions.siteNeedFile(address, "data.txt", enable_dht=False)
                    on_disk = await client_site.storage.read("data.txt")
                    return result, on_disk

        result, on_disk = compat.run(scenario)
        assert result["size"] == len(b"needFile target content")
        assert on_disk == b"needFile target content"


class TestP2PActionsSiteCmd:
    def testSiteCmdTalksToRunningUiServer(self):
        async def scenario():
            from P2P.Ui.UiServer import UiServer

            server = UiServer(sites={})
            async with server.run():
                base_url = server.bound_addresses[0]
                ui_host, port = base_url.replace("http://", "").split(":")

                actions = Actions(pathlib.Path("/tmp"))
                return await actions.siteCmd("ping", wrapper_key="unused-for-ping", ui_host=ui_host, ui_port=int(port))

        reply = compat.run(scenario)
        assert reply["result"] == "pong"
