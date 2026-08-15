import json
import pathlib
import tempfile

import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.UiConfig  # noqa: F401

from P2P.Site import Site
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/Ui?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsUiConfig:
    def testConfigListReturnsApiAllowedKeysOnly(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestUiConfigSiteAAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "configList")

        reply = compat.run(scenario)
        result = reply["result"]
        assert "log_level" in result  # A key_api_change_allowed entry
        assert "value" in result["log_level"]
        assert "default" in result["log_level"]
        assert "pending" in result["log_level"]
        assert result["log_level"]["pending"] is False
        assert "start_dir" not in result  # Not in keys_api_change_allowed

    def testConfigListRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestUiConfigSite2AAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))  # No ADMIN permission

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "configList")

        reply = compat.run(scenario)
        assert "error" in reply

    def testConfigListReflectsPendingChange(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestUiConfigSite3AAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")

                from Config import config
                config.pending_changes["log_level"] = "DEBUG"
                try:
                    server = UiServer(sites={address: site})
                    async with server.run():
                        async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                            return await _call(ws, "configList")
                finally:
                    del config.pending_changes["log_level"]

        reply = compat.run(scenario)
        assert reply["result"]["log_level"]["value"] == "DEBUG"
        assert reply["result"]["log_level"]["pending"] is True
