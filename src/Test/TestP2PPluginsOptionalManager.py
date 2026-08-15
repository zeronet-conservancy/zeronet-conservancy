import json
import pathlib
import tempfile

import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.OptionalManager  # noqa: F401

from P2P.Site import Site
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/Ui?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


async def _declareOptionalFile(site, inner_path, size, content=b""):
    site.content_manager.contents["content.json"] = {
        "files_optional": {inner_path: {"size": size}}
    }
    if content:
        await site.storage.write(inner_path, content)


class TestP2PPluginsOptionalManager:
    def testOptionalFileListShowsOnlyDownloadedByDefault(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestOptManSiteAAAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.content_manager.contents["content.json"] = {
                    "files_optional": {
                        "not_downloaded.bin": {"size": 100},
                        "downloaded.bin": {"size": 5},
                    }
                }
                await site.storage.write("downloaded.bin", b"hello")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "optionalFileList")

        reply = compat.run(scenario)
        inner_paths = [row["inner_path"] for row in reply["result"]]
        assert inner_paths == ["downloaded.bin"]
        assert reply["result"][0]["is_downloaded"] is True
        assert reply["result"][0]["time_downloaded"] is not None

    def testOptionalFileInfoReturnsNoneForUnknownFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestOptManSite2AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "optionalFileInfo", {"inner_path": "nope.bin"})

        reply = compat.run(scenario)
        assert reply["result"] is None

    def testPinKeepsFileListedEvenWithoutDownloadedFilter(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestOptManSite3AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.content_manager.contents["content.json"] = {
                    "files_optional": {"never_downloaded.bin": {"size": 42}}
                }

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        before = await _call(ws, "optionalFileList", msg_id=1)
                        pin_reply = await _call(
                            ws, "optionalFilePin", {"inner_path": "never_downloaded.bin"}, msg_id=2
                        )
                        after = await _call(ws, "optionalFileList", msg_id=3)
                        return before, pin_reply, after

        before, pin_reply, after = compat.run(scenario)
        assert before["result"] == []  # Not downloaded and not pinned yet
        assert pin_reply["result"] == "ok"
        assert len(after["result"]) == 1
        assert after["result"][0]["is_pinned"] is True

    def testUnpinRemovesFileFromDefaultFilterOnceNotDownloaded(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestOptManSite4AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.content_manager.contents["content.json"] = {
                    "files_optional": {"maybe.bin": {"size": 7}}
                }

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        await _call(ws, "optionalFilePin", {"inner_path": "maybe.bin"}, msg_id=1)
                        await _call(ws, "optionalFileUnpin", {"inner_path": "maybe.bin"}, msg_id=2)
                        return await _call(ws, "optionalFileList", msg_id=3)

        reply = compat.run(scenario)
        assert reply["result"] == []

    def testOptionalFileDeleteRemovesRealFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestOptManSite5AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                await _declareOptionalFile(site, "delete_me.bin", 5, content=b"hello")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        exists_before = site.storage.isFile("delete_me.bin")
                        delete_reply = await _call(ws, "optionalFileDelete", {"inner_path": "delete_me.bin"})
                        exists_after = site.storage.isFile("delete_me.bin")
                        return exists_before, delete_reply, exists_after

        exists_before, delete_reply, exists_after = compat.run(scenario)
        assert exists_before is True
        assert delete_reply["result"] == "ok"
        assert exists_after is False

    def testOptionalLimitSetAndStats(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestOptManSite6AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions = ["ADMIN"]
                await _declareOptionalFile(site, "counted.bin", 3, content=b"abc")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        set_reply = await _call(ws, "optionalLimitSet", {"limit": "1000"}, msg_id=1)
                        stats_reply = await _call(ws, "optionalLimitStats", msg_id=2)
                        return set_reply, stats_reply

        set_reply, stats_reply = compat.run(scenario)
        assert set_reply["result"] == "ok"
        assert stats_reply["result"]["limit"] == "1000"
        assert stats_reply["result"]["used"] == 3
        assert stats_reply["result"]["free"] > 0

    def testOptionalLimitStatsRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestOptManSite7AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))  # No ADMIN permission

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "optionalLimitStats")

        reply = compat.run(scenario)
        assert "error" in reply
