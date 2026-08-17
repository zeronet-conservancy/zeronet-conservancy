import json
import pathlib
import tempfile

import httpx
import pytest
import trio_websocket

from P2P.Site import Site
from P2P.SiteManager import SiteManager
from P2P.SiteStorage import SiteStorage
from P2P.WorkerManager import NoPeerHadFileError
from P2P.plugins.ContentFilter.SiteManagerPlugin import SiteManagerPlugin
from P2P.plugins.ContentFilter.SitePlugin import SitePlugin, MutedError
from P2P.plugins.ContentFilter.SiteStoragePlugin import SiteStoragePlugin
from P2P.plugins.ContentFilter import commands as _cf_commands  # noqa: F401 -- registers siteblock* commands
from P2P.Ui.UiServer import UiServer
from P2P import compat


# Composed directly via multiple inheritance rather than through the real
# plugin_manager.registerTo()/acceptPlugins() machinery -- same reasoning
# and same workaround as TestP2PPluginsZeroname.py: by the time this test
# file runs, other test modules have already imported and decorated the
# real SiteManager class without this plugin. This tests the plugin's
# actual add()-blocking logic (the real risk), not the production
# bootstrap-ordering wiring, which is separate, already-documented
# follow-up work (see P2P.PluginManager's own module docstring).
class ContentFilterSiteManager(SiteManagerPlugin, SiteManager):
    pass


class ContentFilterSite(SitePlugin, Site):
    pass


class ContentFilterSiteStorage(SiteStoragePlugin, SiteStorage):
    pass


_DB_SCHEMA = {
    "db_name": "TestSite",
    "db_file": "site.db",
    "version": 1,
    "maps": {"(.*/)?data\\.json$": {"to_keyvalue": ["title"]}},
}


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsContentFilterStorage:
    def testAddRejectsBlockedSite(self):
        with tempfile.TemporaryDirectory() as d:
            site_manager = ContentFilterSiteManager(pathlib.Path(d))
            from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
            smp.filter_storage.siteblockAdd("1BlockedSiteAAAAAAAAAAAAAAAA", reason="test")

            assert site_manager.add("1BlockedSiteAAAAAAAAAAAAAAAA") is False

    def testAddAllowsUnblockedSite(self):
        with tempfile.TemporaryDirectory() as d:
            site_manager = ContentFilterSiteManager(pathlib.Path(d))
            site = site_manager.add("1AllowedSiteAAAAAAAAAAAAAAAA")
            assert site is not False
            assert site.address == "1AllowedSiteAAAAAAAAAAAAAAAA"

    def testAddIgnoreBlockBypassesBlock(self):
        with tempfile.TemporaryDirectory() as d:
            site_manager = ContentFilterSiteManager(pathlib.Path(d))
            from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
            smp.filter_storage.siteblockAdd("1BlockedSiteBAAAAAAAAAAAAAAA", reason="test")

            site = site_manager.add("1BlockedSiteBAAAAAAAAAAAAAAA", ignore_block=True)
            assert site is not False

    def testSiteblockPersistsAcrossReload(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            first = ContentFilterSiteManager(data_dir)
            from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
            smp.filter_storage.siteblockAdd("1PersistedBlockAAAAAAAAAAAAA", reason="persisted")

            second = ContentFilterSiteManager(data_dir)  # Fresh instance, same data_dir
            assert second.add("1PersistedBlockAAAAAAAAAAAAA") is False


class TestP2PPluginsContentFilterCommands:
    def testSiteblockAddListGetRemoveRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = ContentFilterSiteManager(data_dir)
                admin_address = "1TestCfAdminSiteAAAAAAAAAAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                target_address = "1TestCfTargetSiteAAAAAAAAAA2"

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        add_reply = await _call(
                            ws, "siteblockAdd", {"site_address": target_address, "reason": "spam"}, msg_id=1
                        )
                        list_reply = await _call(ws, "siteblockList", msg_id=2)
                        get_reply = await _call(ws, "siteblockGet", {"site_address": target_address}, msg_id=3)
                        remove_reply = await _call(
                            ws, "siteblockRemove", {"site_address": target_address}, msg_id=4
                        )
                        get_after_remove = await _call(ws, "siteblockGet", {"site_address": target_address}, msg_id=5)
                        return add_reply, list_reply, get_reply, remove_reply, get_after_remove

        add_reply, list_reply, get_reply, remove_reply, get_after_remove = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert "1TestCfTargetSiteAAAAAAAAAA2" in list_reply["result"]
        assert get_reply["result"]["reason"] == "spam"
        assert remove_reply["result"] == "ok"
        assert "error" in get_after_remove["result"]

    def testSiteblockAddRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = ContentFilterSiteManager(data_dir)
                address = "1TestCfNonAdminSiteAAAAAAAAA1"
                site = site_manager.add(address)  # No ADMIN permission

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteblockAdd", {"site_address": "1SomeOtherSiteAAAAAAAAAAAAA"})

        reply = compat.run(scenario)
        assert "error" in reply

    def testMuteAddListRemoveRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = ContentFilterSiteManager(data_dir)
                admin_site = site_manager.add("1TestCfMuteAdminSiteAAAAAAAAAA1")
                admin_site.permissions = ["ADMIN"]
                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        add_reply = await _call(ws, "muteAdd", {
                            "auth_address": "1AuthAddressAAAAAAAAAAAAAAAA",
                            "cert_user_id": "alice@example",
                            "reason": "spam",
                        }, msg_id=1)
                        list_reply = await _call(ws, "muteList", msg_id=2)
                        remove_reply = await _call(ws, "muteRemove", {
                            "auth_address": "1AuthAddressAAAAAAAAAAAAAAAA",
                        }, msg_id=3)
                        return add_reply, list_reply, remove_reply

        add_reply, list_reply, remove_reply = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert list_reply["result"]["1AuthAddressAAAAAAAAAAAAAAAA"]["cert_user_id"] == "alice@example"
        assert remove_reply["result"] == "ok"

    def testContentFilterDashboardPageListsAndRemoves(self):
        """siteblockAdd was reachable (the Sidebar's "Delete site ->
        Blacklist" flow), but siteblockList/siteblockRemove/muteAdd/
        muteList/muteRemove had no UI anywhere -- found auditing every
        P2P plugin for the same "backend works, nothing calls it" gap
        SiteBuilder had. Covers the new /ContentFilter dashboard page
        (added alongside /Config/Plugins/SiteBuilder) actually rendering,
        and its remove buttons' commands (siteblockRemove/muteRemove)
        really clearing a real block/mute, not just returning "ok"."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = ContentFilterSiteManager(data_dir)
                admin_address = "1TestCfDashAdminSiteAAAAAAAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]
                server = UiServer(sites=site_manager.sites, site_manager=site_manager, homepage=admin_address)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        page = await client.get("%s/ContentFilter" % base_url)

                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        await _call(ws, "siteblockAdd", {"site_address": "1TestCfDashBlockedSiteAAAA2", "reason": "spam"}, msg_id=1)
                        await _call(ws, "muteAdd", {"auth_address": "1TestCfDashMutedAuthAAAAAA3", "reason": "spam"}, msg_id=2)
                        before_blocks = await _call(ws, "siteblockList", msg_id=3)
                        before_mutes = await _call(ws, "muteList", msg_id=4)
                        await _call(ws, "siteblockRemove", {"site_address": "1TestCfDashBlockedSiteAAAA2"}, msg_id=5)
                        await _call(ws, "muteRemove", {"auth_address": "1TestCfDashMutedAuthAAAAAA3"}, msg_id=6)
                        after_blocks = await _call(ws, "siteblockList", msg_id=7)
                        after_mutes = await _call(ws, "muteList", msg_id=8)
                        return page.status_code, page.text, before_blocks, before_mutes, after_blocks, after_mutes

        status, body, before_blocks, before_mutes, after_blocks, after_mutes = compat.run(scenario)
        assert status == 200
        assert '"contentfilter"' in body
        assert "siteblockList" in body
        assert "muteList" in body
        assert "siteblockRemove" in body
        assert "muteRemove" in body
        assert "1TestCfDashBlockedSiteAAAA2" in before_blocks["result"]
        assert "1TestCfDashMutedAuthAAAAAA3" in before_mutes["result"]
        assert "1TestCfDashBlockedSiteAAAA2" not in after_blocks["result"]
        assert "1TestCfDashMutedAuthAAAAAA3" not in after_mutes["result"]


class TestP2PPluginsContentFilterEnforcement:
    """Site.needFile() mute enforcement -- the real per-file hook
    SitePlugin.py attaches to now that P2P.Site is @acceptPlugins (see
    that module's own docstring). Composed via multiple inheritance, same
    reasoning as ContentFilterSiteManager above."""

    def testNeedFileRefusesMutedAuthor(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
                from P2P.plugins.ContentFilter.storage import ContentFilterStorage
                smp.filter_storage = ContentFilterStorage(pathlib.Path(d) / "filter")
                smp.filter_storage.muteAdd("1MutedAuthorAAAAAAAAAAAAAAAA", reason="spam")

                site = ContentFilterSite("1TestMuteEnforceSiteAAAAAAAA1", pathlib.Path(d) / "site")
                with pytest.raises(MutedError):
                    await site.needFile("data/users/1MutedAuthorAAAAAAAAAAAAAAAA/data.json", [])

        compat.run(scenario)

    def testNeedFileAllowsUnmutedAuthor(self):
        """No mute match -- the override delegates to the real Scheduler,
        proven by getting the real "no peers available" failure instead
        of MutedError (an empty peers list can't succeed any other way)."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
                from P2P.plugins.ContentFilter.storage import ContentFilterStorage
                smp.filter_storage = ContentFilterStorage(pathlib.Path(d) / "filter")
                smp.filter_storage.muteAdd("1MutedAuthorBBBBBBBBBBBBBBBB", reason="spam")

                site = ContentFilterSite("1TestMuteAllowSiteAAAAAAAAA1", pathlib.Path(d) / "site")
                with pytest.raises(NoPeerHadFileError):
                    await site.needFile("data/users/1UnmutedAuthorAAAAAAAAAAAAA/data.json", [])

        compat.run(scenario)

    def testSyncSiteSkipsMutedAuthorButSyncsRest(self):
        """End-to-end proof that the mute check applies during a real bulk
        WorkerManager.syncSite() run, not just a single needFile() call --
        two real FileServer nodes, a real signed content.json listing one
        muted-author file and one unmuted file, only the unmuted one ends
        up synced. Generic per-file-skip behavior is already proven at the
        WorkerManager level in TestP2PWorkerManager.py's own
        testSyncSiteSkipsFileRefusedByPluginButSyncsRest; this confirms
        ContentFilter's actual plugin is what's wired into that path."""
        import time

        from libp2p.peer.peerinfo import PeerInfo
        from Crypt import CryptBitcoin, CryptHash
        from P2P.ConnectionPolicy import ConnectionPolicy
        from P2P.FileServer import FileServer
        from P2P.Peer import Peer
        from P2P.WorkerManager import syncSite

        def _sha512(data: bytes) -> str:
            import io
            return CryptHash.sha512sum(io.BytesIO(data))

        def _sign(content, privatekey):
            sign_content = json.dumps(content, sort_keys=True)
            content = dict(content)
            content["signs"] = {CryptBitcoin.privatekeyToAddress(privatekey): CryptBitcoin.sign(sign_content, privatekey)}
            return content

        privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(privatekey)
        muted_author = "1MutedAuthorEEEEEEEEEEEEEEEEE"
        muted_content = b"spam post"
        normal_content = b"real post"

        async def scenario():
            with tempfile.TemporaryDirectory() as d, \
                    tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
                from P2P.plugins.ContentFilter.storage import ContentFilterStorage
                smp.filter_storage = ContentFilterStorage(pathlib.Path(d) / "filter")
                smp.filter_storage.muteAdd(muted_author, reason="spam")

                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                server_a.addSite(site_a)

                muted_path = "data/users/%s/data.json" % muted_author
                await site_a.storage.write(muted_path, muted_content)
                await site_a.storage.write("data/normal.json", normal_content)
                content = {
                    "address": site_address,
                    "modified": time.time(),
                    "files": {
                        muted_path: {"sha512": _sha512(muted_content), "size": len(muted_content)},
                        "data/normal.json": {"sha512": _sha512(normal_content), "size": len(normal_content)},
                    },
                }
                signed_content = _sign(content, privatekey)
                site_a.content_manager.contents["content.json"] = signed_content
                await site_a.storage.writeJson("content.json", signed_content)

                server_b = FileServer(pathlib.Path(db), ws_port=None)
                site_b = ContentFilterSite(site_address, pathlib.Path(root_b))

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy_b = ConnectionPolicy(server_b.host)
                    peer_a_from_b = Peer(server_a.host.peer_id, server_b.host, policy_b)

                    updated = await syncSite(site_b, [peer_a_from_b])
                    return updated, site_b.storage.isFile(muted_path), site_b.storage.isFile("data/normal.json")

        updated, has_muted, has_normal = compat.run(scenario)
        assert updated == ["data/normal.json"]
        assert has_muted is False
        assert has_normal is True


class TestP2PPluginsContentFilterDbEnforcement:
    """SiteStorage.updateDbFile() mute enforcement -- the second real hook,
    now that SiteStorage.write()/delete() auto-call updateDbFile() on
    every write (see SiteStorage.py's own docstring)."""

    def testWriteSkipsIndexingMutedAuthorData(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
                from P2P.plugins.ContentFilter.storage import ContentFilterStorage
                smp.filter_storage = ContentFilterStorage(pathlib.Path(d) / "filter")
                smp.filter_storage.muteAdd("1MutedAuthorCCCCCCCCCCCCCCCC", reason="spam")

                storage = ContentFilterSiteStorage(pathlib.Path(d) / "site")
                schema = dict(_DB_SCHEMA)
                await storage.writeJson("dbschema.json", schema)
                await storage.write(
                    "data/users/1MutedAuthorCCCCCCCCCCCCCCCC/data.json",
                    json.dumps({"title": "spam post"}).encode(),
                )
                res = await storage.query("SELECT * FROM keyvalue WHERE key = 'title'")
                return res.fetchone()

        row = compat.run(scenario)
        assert row is None  # Never indexed at all -- updateDbFile() returned False before any insert

    def testWriteIndexesUnmutedAuthorData(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.plugins.ContentFilter import SiteManagerPlugin as smp
                from P2P.plugins.ContentFilter.storage import ContentFilterStorage
                smp.filter_storage = ContentFilterStorage(pathlib.Path(d) / "filter")
                smp.filter_storage.muteAdd("1MutedAuthorDDDDDDDDDDDDDDDD", reason="spam")

                storage = ContentFilterSiteStorage(pathlib.Path(d) / "site")
                schema = dict(_DB_SCHEMA)
                await storage.writeJson("dbschema.json", schema)
                await storage.write(
                    "data/users/1UnmutedAuthorBBBBBBBBBBBBBB/data.json",
                    json.dumps({"title": "real post"}).encode(),
                )
                res = await storage.query("SELECT * FROM keyvalue WHERE key = 'title'")
                return res.fetchone()

        row = compat.run(scenario)
        assert row["value"] == "real post"
