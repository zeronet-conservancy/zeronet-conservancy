import json
import pathlib
import tempfile

import trio_websocket

from P2P.Ui.UiServer import UiServer
from P2P.SiteManager import SiteManager
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    while True:
        response = json.loads(await ws.get_message())
        if response.get("cmd") == "response" and response.get("to") == msg_id:
            return response


class TestP2PUiCommandsCors:
    def testCorsPathWithoutPermissionIsDenied(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                requester = site_manager.add("1TestCorsRequesterSiteAAAAA1")
                target = site_manager.add("1TestCorsTargetSiteAAAAAAA1")
                await target.storage.write("shared.txt", b"top secret")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, requester)) as ws:
                        return await _call(ws, "fileGet", {"inner_path": "cors-%s/shared.txt" % target.address})

        reply = compat.run(scenario)
        assert "error" in reply
        assert "permission" in reply["error"]

    def testCorsPermissionThenFileGetFileListDirListReadTargetSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                requester = site_manager.add("1TestCorsReaderSiteAAAAAAA1")
                target = site_manager.add("1TestCorsSharedSiteAAAAAA1")
                await target.storage.write("shared.txt", b"hello from target site")
                await target.storage.write("sub/nested.txt", b"nested")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, requester)) as ws:
                        grant = await _call(ws, "corsPermission", {"address": [target.address]}, msg_id=1)
                        get_reply = await _call(
                            ws, "fileGet", {"inner_path": "cors-%s/shared.txt" % target.address}, msg_id=2
                        )
                        list_reply = await _call(
                            ws, "fileList", {"inner_path": "cors-%s/" % target.address}, msg_id=3
                        )
                        dir_reply = await _call(
                            ws, "dirList", {"inner_path": "cors-%s/" % target.address}, msg_id=4
                        )
                return grant, get_reply, list_reply, dir_reply, list(requester.permissions)

        grant, get_reply, list_reply, dir_reply, permissions = compat.run(scenario)
        assert grant["result"] == "ok"
        assert "Cors:1TestCorsSharedSiteAAAAAA1" in permissions
        assert get_reply["result"] == "hello from target site"
        assert sorted(list_reply["result"]) == ["shared.txt", "sub/nested.txt"]
        assert "sub" in dir_reply["result"]

    def testAdminSiteReadsCorsPathWithoutExplicitGrant(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                admin_site = site_manager.add("1TestCorsAdminSiteAAAAAAAA1")
                admin_site.permissions = ["ADMIN"]
                target = site_manager.add("1TestCorsAdminTargetSiteA1")
                await target.storage.write("data.txt", b"admin can read this")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        return await _call(ws, "fileGet", {"inner_path": "cors-%s/data.txt" % target.address})

        reply = compat.run(scenario)
        assert reply["result"] == "admin can read this"

    def testCorsPathToUnknownSiteErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                requester = site_manager.add("1TestCorsUnknownReqSiteAA1")
                requester.permissions = ["ADMIN"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, requester)) as ws:
                        return await _call(
                            ws, "fileGet", {"inner_path": "cors-1UnknownSiteNeverAddedXXXX/data.txt"}
                        )

        reply = compat.run(scenario)
        assert "error" in reply
        assert "No site found" in reply["error"]
