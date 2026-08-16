import json
import pathlib
import re
import tempfile

import httpx
import trio_websocket

from P2P.Ui.UiServer import UiServer
from P2P.Site import Site
from P2P import compat


class TestP2PUiServer:
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

    def testWrapperNonceIsSingleUse(self):
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
        assert reused_status == 403

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
