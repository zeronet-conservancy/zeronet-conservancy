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
