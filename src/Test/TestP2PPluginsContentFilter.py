import json
import pathlib
import tempfile

import trio_websocket

from P2P.SiteManager import SiteManager
from P2P.plugins.ContentFilter.SiteManagerPlugin import SiteManagerPlugin
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


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/Ui?wrapper_key=%s" % (base_url, site.wrapper_key)


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
