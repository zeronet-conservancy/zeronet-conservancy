import json
import pathlib
import tempfile

import trio_websocket

from P2P.Ui.UiServer import UiServer
from P2P.Site import Site
from P2P import compat


def _wsUrl(server, site=None):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    if site is None:
        return "%s/ZeroNet-Internal/Websocket" % base_url
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PUiCommands:
    def testSiteScopedCommandWithoutWrapperKeyReturnsError(self):
        async def scenario():
            server = UiServer(sites={})
            async with server.run():
                async with trio_websocket.open_websocket_url(_wsUrl(server)) as ws:
                    return await _call(ws, "siteInfo")

        reply = compat.run(scenario)
        assert reply["error"] == "No site for this connection"

    def testSiteInfoResolvedByWrapperKey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestCmdSite", pathlib.Path(root))
                await site.storage.write("content.json", b'{"files": {"a": {}}, "modified": 123}')
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites={"1TestCmdSite": site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteInfo"), site

        reply, site = compat.run(scenario)
        result = reply["result"]
        assert result["address"] == "1TestCmdSite"
        assert result["address_hash"] == site.address_sha1.hex()
        assert result["content"]["files"] == 1
        assert "sign" not in result["content"]

    def testChannelJoinTracksChannelsPerSession(self):
        async def scenario():
            server = UiServer(sites={})
            async with server.run():
                async with trio_websocket.open_websocket_url(_wsUrl(server)) as ws:
                    return await _call(ws, "channelJoin", {"channels": ["siteChanged"]})

        reply = compat.run(scenario)
        assert reply["result"] == "ok"

    def testFileGetReturnsRealFileContent(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestCmdSite2", pathlib.Path(root))
                await site.storage.write("data.txt", b"hello from real storage")

                server = UiServer(sites={"1TestCmdSite2": site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "fileGet", {"inner_path": "data.txt"})

        reply = compat.run(scenario)
        assert reply["result"] == "hello from real storage"

    def testFileGetMissingFileReturnsNone(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestCmdSite3", pathlib.Path(root))
                server = UiServer(sites={"1TestCmdSite3": site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "fileGet", {"inner_path": "nope.txt"})

        reply = compat.run(scenario)
        assert reply["result"] is None

    def testFileListAndDirListSeeRealFiles(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestCmdSite4", pathlib.Path(root))
                await site.storage.write("a.txt", b"a")
                await site.storage.write("sub/b.txt", b"b")

                server = UiServer(sites={"1TestCmdSite4": site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        file_list = await _call(ws, "fileList", {"inner_path": ""}, msg_id=1)
                        dir_list = await _call(ws, "dirList", {"inner_path": ""}, msg_id=2)
                        dir_stats = await _call(ws, "dirList", {"inner_path": "", "stats": True}, msg_id=3)
                        return file_list, dir_list, dir_stats

        file_list, dir_list, dir_stats = compat.run(scenario)
        assert sorted(file_list["result"]) == ["a.txt", "sub/b.txt"]
        assert sorted(dir_list["result"]) == ["a.txt", "sub"]
        stats_by_name = {entry["name"]: entry for entry in dir_stats["result"]}
        assert stats_by_name["a.txt"]["size"] == 1
        assert stats_by_name["a.txt"]["is_dir"] is False
        assert stats_by_name["sub"]["is_dir"] is True

    def testFileWriteRequiresAdminPermission(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestCmdSite5", pathlib.Path(root))
                server = UiServer(sites={"1TestCmdSite5": site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        import base64
                        params = {"inner_path": "new.txt", "content_base64": base64.b64encode(b"hi").decode()}
                        return await _call(ws, "fileWrite", params), site

        reply, site = compat.run(scenario)
        assert "permission" in reply["error"]
        assert not site.storage.isFile("new.txt")

    def testFileWriteAndFileDeleteWithAdminPermission(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestCmdSite6", pathlib.Path(root))
                site.permissions = ["ADMIN"]
                server = UiServer(sites={"1TestCmdSite6": site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        import base64
                        write_params = {"inner_path": "new.txt", "content_base64": base64.b64encode(b"hi").decode()}
                        write_reply = await _call(ws, "fileWrite", write_params, msg_id=1)
                        exists_after_write = site.storage.isFile("new.txt")
                        delete_reply = await _call(ws, "fileDelete", {"inner_path": "new.txt"}, msg_id=2)
                        exists_after_delete = site.storage.isFile("new.txt")
                        return write_reply, exists_after_write, delete_reply, exists_after_delete

        write_reply, exists_after_write, delete_reply, exists_after_delete = compat.run(scenario)
        assert write_reply["result"] == "ok"
        assert exists_after_write is True
        assert delete_reply["result"] == "ok"
        assert exists_after_delete is False

    def testUnknownWrapperKeyLeavesSessionUnscoped(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestCmdSite7", pathlib.Path(root))
                server = UiServer(sites={"1TestCmdSite7": site})
                async with server.run():
                    base_url = server.bound_addresses[0].replace("http://", "ws://")
                    async with trio_websocket.open_websocket_url("%s/ZeroNet-Internal/Websocket?wrapper_key=wrong" % base_url) as ws:
                        return await _call(ws, "siteInfo")

        reply = compat.run(scenario)
        assert reply["error"] == "No site for this connection"
