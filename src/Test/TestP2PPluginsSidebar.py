import json
import pathlib
import tempfile

import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.Sidebar  # noqa: F401

from Config import config
from P2P.Site import Site
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/Ui?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsSidebar:
    def testConsoleLogReadReturnsRecentLines(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                log_dir = pathlib.Path(d)
                (log_dir / "debug.log").write_text(
                    "[2026-08-15 00:00:00] INFO   Test one\n"
                    "[2026-08-15 00:00:01] INFO   Test two\n"
                    "[2026-08-15 00:00:02] ERROR  Test three\n"
                )
                original_log_dir = config.log_dir
                config.log_dir = log_dir
                try:
                    address = "1TestSidebarSiteAAAAAAAAAAAAA"
                    site = Site(address, log_dir / address)
                    site.permissions.append("ADMIN")

                    server = UiServer(sites={address: site})
                    async with server.run():
                        async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                            return await _call(ws, "consoleLogRead")
                finally:
                    config.log_dir = original_log_dir

        reply = compat.run(scenario)
        assert reply["result"]["num_found"] == 3
        assert any("Test three" in line for line in reply["result"]["lines"])

    def testConsoleLogReadFiltersByPattern(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                log_dir = pathlib.Path(d)
                (log_dir / "debug.log").write_text(
                    "[2026-08-15 00:00:00] INFO   Keep me\n"
                    "[2026-08-15 00:00:01] INFO   Drop me\n"
                )
                original_log_dir = config.log_dir
                config.log_dir = log_dir
                try:
                    address = "1TestSidebarSite2AAAAAAAAAAAA"
                    site = Site(address, log_dir / address)
                    site.permissions.append("ADMIN")

                    server = UiServer(sites={address: site})
                    async with server.run():
                        async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                            return await _call(ws, "consoleLogRead", {"filter": "Keep"})
                finally:
                    config.log_dir = original_log_dir

        reply = compat.run(scenario)
        assert reply["result"]["num_found"] == 1
        assert "Keep me" in reply["result"]["lines"][0]

    def testConsoleLogReadRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                log_dir = pathlib.Path(d)
                (log_dir / "debug.log").write_text("[2026-08-15 00:00:00] INFO   Hi\n")
                original_log_dir = config.log_dir
                config.log_dir = log_dir
                try:
                    address = "1TestSidebarSite3AAAAAAAAAAAA"
                    site = Site(address, log_dir / address)  # No ADMIN permission

                    server = UiServer(sites={address: site})
                    async with server.run():
                        async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                            return await _call(ws, "consoleLogRead")
                finally:
                    config.log_dir = original_log_dir

        reply = compat.run(scenario)
        assert "error" in reply
