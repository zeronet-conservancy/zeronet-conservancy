import json
import pathlib
import tempfile

import trio_websocket

from P2P.SiteManager import SiteManager
from P2P.UserManager import UserManager
from P2P.plugins.UiSiteBuilder import commands as _sb_commands  # noqa: F401 -- registers siteBuilder* commands
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsUiSiteBuilder:
    def testStartersListsBundledStarters(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                admin_address = "1TestSbStartersAdminSiteAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        return await _call(ws, "siteBuilderStarters")

        reply = compat.run(scenario)
        ids = {starter["id"] for starter in reply["result"]}
        assert "blank" in ids
        assert all(starter["title"] for starter in reply["result"])

    def testCreateSignsRealSiteWithStarterContentAndMarksOwned(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                admin_address = "1TestSbCreateAdminSiteAAAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        reply = await _call(ws, "siteBuilderCreate", {"starter": "blank"})

                new_address = reply["result"]["address"]
                site = site_manager.sites[new_address]
                content = site.content_manager.contents["content.json"]
                return (
                    new_address in site_manager.sites,
                    site_manager.isOwn(new_address),
                    list(site.permissions),
                    content["title"],
                    "signs" in content and new_address in content["signs"],
                    site.storage.isFile("index.html"),
                    site.storage.isFile("builder/editor.html"),
                    site.storage.isFile("data/settings.json"),
                    site.storage.isFile("data-default/settings.json"),
                )

        (
            registered, is_own, permissions, title, is_signed,
            has_index, has_editor, has_data_settings, has_default_settings,
        ) = compat.run(scenario)
        assert registered is True
        assert is_own is True
        # Must have ADMIN on itself right away, not just SiteManager's own
        # "own" setting -- otherwise the site's own sidebar/owner controls
        # don't render until a restart round-trips permissions through
        # sites.json (this was a real bug: add(own=True) never granted it).
        assert permissions == ["ADMIN"]
        assert title == "My Site"  # From the "blank" starter's own settings.json
        assert is_signed is True  # A real signature, not a stub
        assert has_index is True
        assert has_editor is True
        assert has_data_settings is True
        assert has_default_settings is True

    def testCreateFavouritesNewSiteOnDashboard(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                admin_address = "1TestSbFavAdminSiteAAAAAAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]
                dashboard_address = "1TestSbFavDashboardSiteAAA1"
                site_manager.add(dashboard_address)

                server = UiServer(
                    sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager,
                    homepage=dashboard_address,
                )
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        reply = await _call(ws, "siteBuilderCreate", {"starter": "blank"})

                new_address = reply["result"]["address"]
                user = next(iter(user_manager.users.values()))
                favourites = user.getSiteData(dashboard_address).get("settings", {}).get("favorite_sites", {})
                return new_address in favourites

        assert compat.run(scenario) is True

    def testCreateWithUnknownStarterFallsBackToBlank(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                admin_address = "1TestSbFallbackAdminSiteAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        reply = await _call(ws, "siteBuilderCreate", {"starter": "does-not-exist"})

                new_address = reply["result"]["address"]
                content = site_manager.sites[new_address].content_manager.contents["content.json"]
                return content["title"]

        assert compat.run(scenario) == "My Site"  # Same as the "blank" starter -- unknown starter falls back to it

    def testCreateRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user_manager.create()
                address = "1TestSbNonAdminSiteAAAAAAAA1"
                site = site_manager.add(address)  # No ADMIN permission

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteBuilderCreate", {"starter": "blank"})

        reply = compat.run(scenario)
        assert "error" in reply
