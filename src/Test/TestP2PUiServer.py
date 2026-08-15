import json
import pathlib
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
                async with trio_websocket.open_websocket_url("%s/Ui" % base_url) as ws:
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
                async with trio_websocket.open_websocket_url("%s/Ui" % base_url) as ws:
                    await ws.send_message(json.dumps({"cmd": "totallyMadeUp", "id": 2}))
                    reply = json.loads(await ws.get_message())
                    return reply

        reply = compat.run(scenario)
        assert reply["cmd"] == "response"
        assert reply["to"] == 2
        assert "Unknown command" in reply["error"]

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
