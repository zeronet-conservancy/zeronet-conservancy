import base64
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

    def testCreateZeromailStarterVendorsRealAppAndTrustsLocalProvider(self):
        """zeromail's own app/ tree bypasses the shared page-builder
        template entirely (see UiSiteBuilder.commands's own module
        docstring) -- this asserts the real ZeroMail app files land
        as-is, AND that data/users/content.json's cert_signers got the
        creating user's own local_provider_address substituted in under
        a domain unique to THIS site (not the starter's static "local" --
        see _cmdSiteBuilderCreate's own docstring on why two zeromail
        sites can't share one domain name)."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                admin_address = "1TestSbZeromailAdminSiteAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        reply = await _call(ws, "siteBuilderCreate", {"starter": "zeromail"})

                new_address = reply["result"]["address"]
                site = site_manager.sites[new_address]
                content = site.content_manager.contents["content.json"]
                user_contents = site.content_manager.contents["data/users/content.json"]
                cert_signers = user_contents["user_contents"]["cert_signers"]
                index_html = await site.storage.read("index.html", mode="r")
                return (
                    content["title"],
                    "signs" in content and new_address in content["signs"],
                    site.storage.isFile("index.html"),
                    site.storage.isFile("js/all.js"),
                    site.storage.isFile("dbschema.json"),
                    cert_signers,
                    index_html,
                    user.settings.get("local_provider_address"),
                )

        (
            title, is_signed, has_index, has_js, has_dbschema,
            cert_signers, index_html, provider_address,
        ) = compat.run(scenario)
        assert title == "ZeroMail (local identity)"  # From the starter's own settings.json
        assert is_signed is True
        assert has_index is True
        assert has_js is True
        assert has_dbschema is True
        assert provider_address  # A real address got generated, not left blank
        assert len(cert_signers) == 1
        domain, trusted_address = next(iter(cert_signers.items()))
        assert domain.startswith("local-") and domain != "local"
        assert trusted_address == provider_address
        assert "__LOCAL_DOMAIN__" not in index_html
        assert ("ZEROMAIL_LOCAL_DOMAIN = \"%s\"" % domain) in index_html

    def testZeromailStarterEndToEndComposeAndSign(self):
        """The actual point of this starter: a contributor who only has a
        self-issued cert (no zeroid.bit registration) can compose and
        publish a real message, using the same fileWrite+contentSign
        path P2P.Ui.commands added alongside ContentManager.signUserContent().
        Also proves two zeromail sites don't collide on cert domain
        (see testCreateZeromailStarterVendorsRealAppAndTrustsLocalProvider's
        own docstring) by creating a second one in the same session."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                admin_address = "1TestSbZeromailE2eAdminAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        created = await _call(ws, "siteBuilderCreate", {"starter": "zeromail"}, msg_id=1)
                        new_address = created["result"]["address"]
                        site = site_manager.sites[new_address]
                        domain = next(iter(
                            site.content_manager.contents["data/users/content.json"]["user_contents"]["cert_signers"]
                        ))

                        # A second zeromail site for the same user -- this is
                        # exactly the scenario that used to raise "Certificate
                        # already exists with different data for local" (both
                        # sites' own domains, issued for below, differ now).
                        created2 = await _call(ws, "siteBuilderCreate", {"starter": "zeromail"}, msg_id=2)
                        second_address = created2["result"]["address"]
                        second_site = site_manager.sites[second_address]
                        second_domain = next(iter(
                            second_site.content_manager.contents["data/users/content.json"]["user_contents"]["cert_signers"]
                        ))

                        cert = await user.issueCert(new_address, domain, "web", "alice")
                        second_cert = await user.issueCert(second_address, second_domain, "web", "bob")
                        auth_address = cert["auth_address"]

                        async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws2:
                            write_reply = await _call(ws2, "fileWrite", {
                                "inner_path": "data/users/%s/data.json" % auth_address,
                                "content_base64": base64.b64encode(b'{"message":{}}').decode(),
                            }, msg_id=1)
                            sign_reply = await _call(ws2, "contentSign", {
                                "inner_path": "data/users/%s/content.json" % auth_address,
                            }, msg_id=2)
                return write_reply, sign_reply, site.storage.isFile("data/users/%s/content.json" % auth_address), domain, second_cert

        write_reply, sign_reply, on_disk, domain, second_cert = compat.run(scenario)
        assert write_reply["result"] == "ok"
        result = sign_reply["result"]
        assert result["cert_user_id"] == "alice@%s" % domain
        assert "data.json" in result["files"]
        assert on_disk is True
        assert second_cert["auth_user_name"] == "bob"  # Second site's own self-issue also succeeded

    def testCreateZerotalkStarterVendorsRealAppAndTrustsLocalProvider(self):
        """zerotalk's own app/ tree, same "full app" starter mechanism as
        zeromail (see UiSiteBuilder.commands's own module docstring) --
        a real, patched copy of ZeroTalk's actual client code, not more
        page-builder content."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                admin_address = "1TestSbZerotalkAdminSiteAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        reply = await _call(ws, "siteBuilderCreate", {"starter": "zerotalk"})

                new_address = reply["result"]["address"]
                site = site_manager.sites[new_address]
                content = site.content_manager.contents["content.json"]
                user_contents = site.content_manager.contents["data/users/content.json"]
                cert_signers = user_contents["user_contents"]["cert_signers"]
                index_html = await site.storage.read("index.html", mode="r")
                return (
                    content["title"],
                    "signs" in content and new_address in content["signs"],
                    site.storage.isFile("index.html"),
                    site.storage.isFile("js/all.js"),
                    site.storage.isFile("dbschema.json"),
                    cert_signers,
                    index_html,
                    user.settings.get("local_provider_address"),
                )

        (
            title, is_signed, has_index, has_js, has_dbschema,
            cert_signers, index_html, provider_address,
        ) = compat.run(scenario)
        assert title == "ZeroTalk (local identity)"  # From the starter's own settings.json
        assert is_signed is True
        assert has_index is True
        assert has_js is True
        assert has_dbschema is True
        assert provider_address
        assert len(cert_signers) == 1
        domain, trusted_address = next(iter(cert_signers.items()))
        assert domain.startswith("local-") and domain != "local"
        assert trusted_address == provider_address
        assert "__LOCAL_DOMAIN__" not in index_html
        assert ("ZEROTALK_LOCAL_DOMAIN = \"%s\"" % domain) in index_html

    def testZerotalkStarterEndToEndComposeAndSign(self):
        """Same real compose->sign path as zeromail's own end-to-end test
        (fileWrite + the new contentSign command), proving ZeroTalk's
        writePublish() patch point (a single shared choke point for
        topics/comments/votes, unlike zeromail's own saveData()) needed
        no per-caller duplication."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                admin_address = "1TestSbZerotalkE2eAdminAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        created = await _call(ws, "siteBuilderCreate", {"starter": "zerotalk"}, msg_id=1)
                        new_address = created["result"]["address"]
                        site = site_manager.sites[new_address]
                        domain = next(iter(
                            site.content_manager.contents["data/users/content.json"]["user_contents"]["cert_signers"]
                        ))

                        cert = await user.issueCert(new_address, domain, "web", "carol")
                        auth_address = cert["auth_address"]

                        async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws2:
                            write_reply = await _call(ws2, "fileWrite", {
                                "inner_path": "data/users/%s/data.json" % auth_address,
                                "content_base64": base64.b64encode(b'{"next_topic_id":1,"topic":[]}').decode(),
                            }, msg_id=1)
                            sign_reply = await _call(ws2, "contentSign", {
                                "inner_path": "data/users/%s/content.json" % auth_address,
                            }, msg_id=2)
                return write_reply, sign_reply, site.storage.isFile("data/users/%s/content.json" % auth_address), domain

        write_reply, sign_reply, on_disk, domain = compat.run(scenario)
        assert write_reply["result"] == "ok"
        result = sign_reply["result"]
        assert result["cert_user_id"] == "carol@%s" % domain
        assert "data.json" in result["files"]
        assert on_disk is True

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
