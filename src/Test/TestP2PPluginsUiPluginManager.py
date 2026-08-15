import json
import pathlib
import tempfile

import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.UiPluginManager  # noqa: F401

from P2P.PluginManager import plugin_manager
from P2P.Site import Site
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/Ui?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsUiPluginManager:
    def testPluginListIncludesRealOnDiskPlugins(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestUiPlugMgrSiteAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "pluginList")

        reply = compat.run(scenario)
        names = {plugin["name"] for plugin in reply["result"]["plugins"]}
        assert "UiConfig" in names
        assert "CryptMessage" in names
        assert "UiPluginManager" in names

    def testPluginListRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestUiPlugMgrSite2AAAAAAAAAA"
                site = Site(address, pathlib.Path(d))  # No ADMIN permission

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "pluginList")

        reply = compat.run(scenario)
        assert "error" in reply

    def testPluginConfigSetTogglesEnabledForNextStartup(self):
        original_config = plugin_manager.config["builtin"].get("UiConfig")
        try:
            async def scenario():
                with tempfile.TemporaryDirectory() as d:
                    address = "1TestUiPlugMgrSite3AAAAAAAAAA"
                    site = Site(address, pathlib.Path(d))
                    site.permissions.append("ADMIN")

                    server = UiServer(sites={address: site})
                    async with server.run():
                        async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                            set_reply = await _call(
                                ws, "pluginConfigSet", {"dir_name": "UiConfig", "key": "enabled", "value": False},
                                msg_id=1,
                            )
                            list_reply = await _call(ws, "pluginList", msg_id=2)
                            return set_reply, list_reply

            set_reply, list_reply = compat.run(scenario)
            assert set_reply["result"] == "ok"
            ui_config_entry = next(p for p in list_reply["result"]["plugins"] if p["name"] == "UiConfig")
            assert ui_config_entry["enabled"] is False
        finally:
            if original_config is None:
                plugin_manager.config["builtin"].pop("UiConfig", None)
            else:
                plugin_manager.config["builtin"]["UiConfig"] = original_config

    def testPluginConfigSetRejectsUnknownPlugin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestUiPlugMgrSite4AAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(
                            ws, "pluginConfigSet",
                            {"dir_name": "NotARealPlugin", "key": "enabled", "value": False},
                        )

        reply = compat.run(scenario)
        assert reply["result"] == {"error": "Plugin not found"}
