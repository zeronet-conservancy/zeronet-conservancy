import json
import pathlib
import re
import tempfile

import httpx
import trio_websocket

from P2P.Ui.UiServer import UiServer
from P2P.Ui.commands import formatSiteInfo
from P2P.Site import Site
from P2P.SiteManager import SiteManager
from P2P.UserManager import UserManager
from P2P.plugins.Sidebar.render import renderSidebarHtml
from P2P import compat


class TestP2PUiServer:
    def testSidebarAndSiteInfoHaveDefinedLegacyFields(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                data_dir = pathlib.Path(root)
                site_manager = SiteManager(data_dir)
                site = site_manager.add("1TestSidebarFieldsSiteAAAAAAAA1")
                site.permissions = ["ADMIN"]
                server = UiServer(
                    sites=site_manager.sites, site_manager=site_manager,
                    user_manager=UserManager(data_dir), homepage=site.address,
                )
                async with server.run():
                    base_url = server.bound_addresses[0].replace("http://", "ws://")
                    async with trio_websocket.open_websocket_url(
                        base_url + "/ZeroNet-Internal/Websocket?wrapper_key=%s" % site.wrapper_key
                    ) as ws:
                        async def call(cmd, msg_id):
                            await ws.send_message(json.dumps({"cmd": cmd, "params": {}, "id": msg_id}))
                            return json.loads(await ws.get_message())

                        site_info = await call("siteInfo", 1)
                        return site_info, renderSidebarHtml(
                            site, formatSiteInfo(site, site_manager), False, True
                        )

        site_info, sidebar = compat.run(scenario)
        assert site_info["result"]["settings"]["own"] is False
        assert "undefined" not in sidebar
        assert "None" not in sidebar

    def testCertificateSelectorPushesNativeAccountDialog(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                data_dir = pathlib.Path(root)
                site_manager = SiteManager(data_dir)
                site = site_manager.add("1TestCertSelectorSiteAAAAAAAAAA1")
                site.permissions = ["ADMIN"]
                site.content_manager.contents["data/users/content.json"] = {
                    "user_contents": {"cert_signers": {"zeroid.bit": ["1ProviderSite"]}}
                }
                server = UiServer(
                    sites=site_manager.sites, site_manager=site_manager,
                    user_manager=UserManager(data_dir), homepage=site.address,
                )
                async with server.run():
                    base_url = server.bound_addresses[0].replace("http://", "ws://")
                    async with trio_websocket.open_websocket_url(
                        base_url + "/ZeroNet-Internal/Websocket?wrapper_key=%s" % site.wrapper_key
                    ) as ws:
                        await ws.send_message(json.dumps({
                            "cmd": "certSelect",
                            "params": {"accepted_domains": ["zeroid.bit"]},
                            "id": 1,
                        }))
                        messages = [json.loads(await ws.get_message()) for _ in range(3)]
                        return messages

        messages = compat.run(scenario)
        by_cmd = {message["cmd"]: message for message in messages}
        assert "Use local identity" in by_cmd["notification"]["params"][1]
        assert "Register zeroid.bit" in by_cmd["notification"]["params"][1]
        assert "1ProviderSite" in by_cmd["notification"]["params"][1]
        assert "certSet" in by_cmd["injectScript"]["params"]
        assert by_cmd["response"]["result"][0]["selected"] is True

    def testNativeDashboardMenuCommands(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                data_dir = pathlib.Path(root)
                site_manager = SiteManager(data_dir)
                admin = site_manager.add("1TestMenuAdminSiteAAAAAAAAAAAA1")
                admin.permissions = ["ADMIN"]
                shutdown_requested = []
                server = UiServer(
                    sites=site_manager.sites, site_manager=site_manager,
                    user_manager=UserManager(data_dir), data_dir=data_dir,
                    homepage=admin.address,
                    shutdown_callback=lambda: shutdown_requested.append(True),
                )
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with trio_websocket.open_websocket_url(
                        base_url.replace("http://", "ws://") +
                        "/ZeroNet-Internal/Websocket?wrapper_key=%s" % admin.wrapper_key
                    ) as ws:
                        async def call(cmd, params, msg_id):
                            await ws.send_message(json.dumps({"cmd": cmd, "params": params, "id": msg_id}))
                            return json.loads(await ws.get_message())

                        created = await call("siteCreate", {"use_master_seed": False}, 1)
                        favourite = await call("siteFavourite", {"address": created["result"]["address"]}, 2)
                        unfavourite = await call("siteUnfavourite", {"address": created["result"]["address"]}, 3)
                        directory = await call("serverShowdirectory", {"directory": "backup"}, 4)
                        shutdown = await call("serverShutdown", {}, 5)
                        return created, favourite, unfavourite, directory, shutdown, shutdown_requested, data_dir

        created, favourite, unfavourite, directory, shutdown, shutdown_requested, data_dir = compat.run(scenario)
        assert "address" in created["result"]
        assert favourite["result"] == "Added to favourites"
        assert unfavourite["result"] == "Removed from favourites"
        assert pathlib.Path(directory["result"]["path"]) == data_dir.resolve()
        assert shutdown["result"] == "ok"
        assert shutdown_requested == [True]

    def testDashboardPagesExposeNativeWebsocketBootstrap(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestDashboardSite", pathlib.Path(root), permissions=["ADMIN"])
                server = UiServer(
                    sites={site.address: site},
                    homepage=site.address,
                )
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        config = await client.get("%s/Config" % base_url)
                        plugins = await client.get("%s/Plugins" % base_url)
                        return config.status_code, config.text, plugins.status_code, plugins.text

        config_status, config_body, plugins_status, plugins_body = compat.run(scenario)
        assert config_status == 200
        assert "Configuration" in config_body
        assert '"config"' in config_body
        assert "configList" in config_body
        assert plugins_status == 200
        assert "Plugins" in plugins_body
        assert '"plugins"' in plugins_body
        assert "pluginList" in plugins_body

    def testFileManagerAndConsolePagesExposeNativeBootstrap(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestToolsSite", pathlib.Path(root), permissions=["ADMIN"])
                await site.storage.write("data/example.txt", b"example")
                server = UiServer(sites={site.address: site}, homepage=site.address)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        files = await client.get("%s/list/%s/data" % (base_url, site.address))
                        console = await client.get("%s/Console" % base_url)
                        return files.status_code, files.text, console.status_code, console.text

        files_status, files_body, console_status, console_body = compat.run(scenario)
        assert files_status == 200
        assert "fileList" not in files_body  # directory page uses the narrower dirList API
        assert "dirList" in files_body
        assert console_status == 200
        assert "consoleLogRead" in console_body
        assert "consoleLogStream" in console_body

    def testServesRealSiteFileOverHttp(self):
        content = b'{"hello": "from a real site file served via Hypercorn"}'

        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestUiSite", pathlib.Path(root))
                await site.storage.write("content.json", content)

                server = UiServer(sites={"1TestUiSite": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/1TestUiSite/content.json" % base_url)
                        return response.status_code, response.content, response.headers.get("content-type")

        status, body, content_type = compat.run(scenario)
        assert status == 200
        assert body == content
        assert content_type == "application/json"

    def testUnknownSiteReturns404(self):
        async def scenario():
            server = UiServer(sites={})
            async with server.run():
                base_url = server.bound_addresses[0]
                async with httpx.AsyncClient() as client:
                    response = await client.get("%s/1NoSuchSite/content.json" % base_url)
                    return response.status_code

        assert compat.run(scenario) == 404

    def testResolvedDomainServesNativeSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                from P2P.plugins.Zeroname.SiteManagerPlugin import BIT_RESOLVER, SiteManagerPlugin
                from P2P.SiteManager import SiteManager

                class DomainSiteManager(SiteManagerPlugin, SiteManager):
                    pass

                data_dir = pathlib.Path(root)
                manager = DomainSiteManager(data_dir)
                resolver = manager.add(BIT_RESOLVER)
                target = manager.add("1ResolvedDomainSiteAAAAAAAAAAA")
                await resolver.storage.write("data/names.json", b'{"example.bit": "1ResolvedDomainSiteAAAAAAAAAAA"}')
                await resolver.storage.write("content.json", b'{"modified": 1}')
                await target.storage.write("index.html", b"<h1>resolved domain</h1>")

                server = UiServer(sites=manager.sites, site_manager=manager)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            "%s/example.bit/index.html?wrapper=0" % base_url
                        )
                        return response.status_code, response.text

        status, body = compat.run(scenario)
        assert status == 200
        assert body == "<h1>resolved domain</h1>"

    def testMissingFileReturns404(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestUiSite2", pathlib.Path(root))
                server = UiServer(sites={"1TestUiSite2": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/1TestUiSite2/nope.json" % base_url)
                        return response.status_code

        assert compat.run(scenario) == 404

    def testPathTraversalReturns403(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestUiSite3", pathlib.Path(root))
                server = UiServer(sites={"1TestUiSite3": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/1TestUiSite3/../../etc/passwd" % base_url)
                        return response.status_code

        # httpx normalizes ".." in the URL itself before sending; still a
        # legitimate check that whatever reaches the server is handled safely.
        assert compat.run(scenario) in (403, 404)

    def testWebsocketPingRoundTrip(self):
        async def scenario():
            server = UiServer(sites={})
            async with server.run():
                base_url = server.bound_addresses[0].replace("http://", "ws://")
                async with trio_websocket.open_websocket_url("%s/ZeroNet-Internal/Websocket" % base_url) as ws:
                    await ws.send_message(json.dumps({"cmd": "ping", "id": 1}))
                    reply = json.loads(await ws.get_message())
                    return reply

        reply = compat.run(scenario)
        assert reply == {"cmd": "response", "to": 1, "result": "pong"}

    def testWebsocketUnknownCommandReturnsError(self):
        async def scenario():
            server = UiServer(sites={})
            async with server.run():
                base_url = server.bound_addresses[0].replace("http://", "ws://")
                async with trio_websocket.open_websocket_url("%s/ZeroNet-Internal/Websocket" % base_url) as ws:
                    await ws.send_message(json.dumps({"cmd": "totallyMadeUp", "id": 2}))
                    reply = json.loads(await ws.get_message())
                    return reply

        reply = compat.run(scenario)
        assert reply["cmd"] == "response"
        assert reply["to"] == 2
        assert "Unknown command" in reply["error"]

    def testWebsocketOriginMustMatchHost(self):
        async def scenario():
            server = UiServer(sites={})
            async with server.run():
                base_url = server.bound_addresses[0].replace("http://", "ws://")
                try:
                    async with trio_websocket.open_websocket_url(
                        "%s/ZeroNet-Internal/Websocket" % base_url,
                        extra_headers={"Origin": "http://evil.example.com"},
                    ):
                        return "connected"
                except Exception as err:
                    return type(err).__name__

        assert compat.run(scenario) != "connected"

    def testHtmlPageServedWrapped(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestWrapSite", pathlib.Path(root))
                await site.storage.write("index.html", b"<h1>real site content</h1>")

                server = UiServer(sites={"1TestWrapSite": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/1TestWrapSite/index.html" % base_url)
                        return response.status_code, response.text, response.headers.get("content-type")

        status, body, content_type = compat.run(scenario)
        assert status == 200
        assert content_type.startswith("text/html")
        # This is the *wrapper* HTML, not the site's own raw content --
        # the real page loads inside its iframe, not inlined here.
        assert "<!DOCTYPE html>" in body
        assert 'address = "1TestWrapSite"' in body
        assert "<h1>real site content</h1>" not in body

    def testWrapperOptOutServesRawFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestNoWrapSite", pathlib.Path(root))
                await site.storage.write("index.html", b"<h1>raw content</h1>")

                server = UiServer(sites={"1TestNoWrapSite": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/1TestNoWrapSite/index.html?wrapper=0" % base_url)
                        return response.status_code, response.text

        status, body = compat.run(scenario)
        assert status == 200
        assert body == "<h1>raw content</h1>"

    def testWrapperNonceAllowsBrowserHistoryReplay(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestNonceSite", pathlib.Path(root))
                await site.storage.write("index.html", b"<h1>raw content</h1>")

                server = UiServer(sites={"1TestNonceSite": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        wrapper = await client.get("%s/1TestNonceSite/index.html" % base_url)
                        nonce = re.search(r"wrapper_nonce=([A-Za-z0-9]+)", wrapper.text).group(1)
                        first = await client.get(
                            "%s/1TestNonceSite/index.html?wrapper=0&wrapper_nonce=%s" % (base_url, nonce)
                        )
                        second = await client.get(
                            "%s/1TestNonceSite/index.html?wrapper=0&wrapper_nonce=%s" % (base_url, nonce)
                        )
                        return first.status_code, first.text, second.status_code

        status, body, reused_status = compat.run(scenario)
        assert status == 200
        assert body == "<h1>raw content</h1>"
        assert reused_status == 200

    def testInvalidWrapperNonceRejected(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestBadNonceSite", pathlib.Path(root))
                await site.storage.write("index.html", b"<h1>raw content</h1>")

                server = UiServer(sites={"1TestBadNonceSite": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get(
                            "%s/1TestBadNonceSite/index.html?wrapper=0&wrapper_nonce=not-issued" % base_url
                        )
                        return response.status_code

        assert compat.run(scenario) == 403

    def testSiteRootServesWrapped(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestRootSite", pathlib.Path(root))
                server = UiServer(sites={"1TestRootSite": site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/1TestRootSite" % base_url)
                        return response.status_code, response.text

        status, body = compat.run(scenario)
        assert status == 200
        assert "<!DOCTYPE html>" in body

    def testStaticUiMediaServedFromRealAssets(self):
        async def scenario():
            server = UiServer(sites={})
            async with server.run():
                base_url = server.bound_addresses[0]
                async with httpx.AsyncClient() as client:
                    response = await client.get("%s/uimedia/all.css" % base_url)
                    return response.status_code, len(response.content)

        status, size = compat.run(scenario)
        assert status == 200
        assert size > 0  # served the real file from src/Ui/media/, not a stub

    def testUntrustedHostRejected(self):
        async def scenario():
            server = UiServer(sites={})  # default allowed_hosts: 127.0.0.1/localhost only
            async with server.run():
                port = server.bound_addresses[0].rsplit(":", 1)[1]
                async with httpx.AsyncClient() as client:
                    response = await client.get(
                        "http://127.0.0.1:%s/" % port,
                        headers={"Host": "evil-attacker.example.com"},
                    )
                    return response.status_code

        assert compat.run(scenario) == 400

    def testHomepageRedirectsToConfiguredAddress(self):
        async def scenario():
            server = UiServer(sites={}, homepage="1TestHomepageSiteAAAAAAAAAAAA")
            async with server.run():
                base_url = server.bound_addresses[0]
                async with httpx.AsyncClient() as client:
                    response = await client.get("%s/" % base_url, follow_redirects=False)
                    return response.status_code, response.headers.get("location")

        status, location = compat.run(scenario)
        assert status in (302, 307)
        assert location == "/1TestHomepageSiteAAAAAAAAAAAA/"

    def testHomepageMissingReturns404(self):
        async def scenario():
            server = UiServer(sites={})  # No homepage configured
            async with server.run():
                base_url = server.bound_addresses[0]
                async with httpx.AsyncClient() as client:
                    response = await client.get("%s/" % base_url)
                    return response.status_code

        assert compat.run(scenario) == 404

    def testUnknownAddressAutoAddsThenReturns503WithoutPeers(self):
        """A brand new, valid-looking address with no file_server
        configured to actually try downloading from: auto-adds (via
        on_missing_site) but can't fetch content.json, so the response
        is a real 503 rather than the plain 404 an unrecognized address
        gets -- proving the site really was added (SiteManager.sites
        now has it) even though nothing could be downloaded."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.SiteManager import SiteManager
                site_manager = SiteManager(pathlib.Path(d))

                def on_missing_site(address):
                    return site_manager.add(address)

                server = UiServer(
                    sites=site_manager.sites, site_manager=site_manager,
                    on_missing_site=on_missing_site, auto_download_timeout=0.2,
                )
                address = "1TestAutoAddSiteAAAAAAAAAAAA"
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient(timeout=5) as client:
                        response = await client.get("%s/%s/" % (base_url, address))
                        return response.status_code, address in site_manager.sites

        status, was_added = compat.run(scenario)
        assert status == 503
        assert was_added is True

    def testInvalidAddressStillReturns404(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                from P2P.SiteManager import SiteManager
                site_manager = SiteManager(pathlib.Path(d))

                server = UiServer(
                    sites=site_manager.sites, site_manager=site_manager,
                    on_missing_site=site_manager.add,
                )
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/not-a-real-address/" % base_url)
                        return response.status_code

        assert compat.run(scenario) == 404
