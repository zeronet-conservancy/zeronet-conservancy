import json
import logging
import pathlib
import tempfile
import uuid

import trio
import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.Sidebar  # noqa: F401

from Config import config
from P2P.Site import Site
from P2P.UserManager import UserManager
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


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

    def testConsoleLogStreamPushesMatchingLines(self):
        marker = uuid.uuid4().hex

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestSidebarSite4AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        stream_reply = await _call(ws, "consoleLogStream", {"filter": marker}, msg_id=1)
                        stream_id = stream_reply["result"]["stream_id"]

                        logging.getLogger("Test.Sidebar").info("hello %s", marker)

                        push = json.loads(await ws.get_message())
                        return stream_id, push

        stream_id, push = compat.run(scenario)
        assert push["cmd"] == "logLineAdd"
        assert push["params"]["stream_id"] == stream_id
        assert marker in push["params"]["lines"][0]

    def testConsoleLogStreamDropsNonMatchingLines(self):
        marker = uuid.uuid4().hex

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestSidebarSite5AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        await _call(ws, "consoleLogStream", {"filter": marker}, msg_id=1)

                        logging.getLogger("Test.Sidebar").info("unrelated line, no marker here")

                        with trio.move_on_after(0.3) as cancel_scope:
                            await ws.get_message()
                        return cancel_scope.cancelled_caught

        timed_out = compat.run(scenario)
        assert timed_out is True  # No push arrived -- the filter correctly dropped it

    def testConsoleLogStreamRemoveStopsFurtherPushes(self):
        marker = uuid.uuid4().hex

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestSidebarSite6AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        stream_reply = await _call(ws, "consoleLogStream", {"filter": marker}, msg_id=1)
                        stream_id = stream_reply["result"]["stream_id"]

                        remove_reply = await _call(ws, "consoleLogStreamRemove", {"stream_id": stream_id}, msg_id=2)

                        logging.getLogger("Test.Sidebar").info("hello %s", marker)

                        with trio.move_on_after(0.3) as cancel_scope:
                            await ws.get_message()
                        return remove_reply, cancel_scope.cancelled_caught

        remove_reply, timed_out = compat.run(scenario)
        assert remove_reply["result"] == "ok"
        assert timed_out is True  # Removed before the log call -- no push should arrive

    def testConsoleLogStreamRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestSidebarSite7AAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))  # No ADMIN permission

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "consoleLogStream")

        reply = compat.run(scenario)
        assert "error" in reply

    def testSidebarGetHtmlTagWithRealDbReturnsHtml(self):
        """Found live: dragging open the sidebar on ZeroMe/ZeroTalk (both
        real sqlite-backed sites) rendered the literal text "[object
        Object]" instead of the sidebar -- sidebarGetHtmlTag() was
        throwing (str db_path passed where getInnerPath() needs a Path),
        so the command handler's generic error-result dict got
        string-concatenated client-side. No existing test opened a real
        db before calling this command, which is why it went unnoticed."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestSidebarDbSiteAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions.append("ADMIN")
                await site.storage.writeJson("dbschema.json", {
                    "db_name": "TestSite",
                    "db_file": "site.db",
                    "version": 1,
                    "maps": {},
                })
                await site.storage.getDb()

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "sidebarGetHtmlTag")

        reply = compat.run(scenario)
        assert "error" not in reply
        assert isinstance(reply["result"], str)
        assert "<label>Database" in reply["result"]

    def testSiteRecoverPrivatekeyDerivesRealKeyFromMasterSeed(self):
        """Simulates the real scenario this command exists for: a fresh
        data_dir with only users.json (the master seed) restored, not the
        per-site privatekey cache getNewSiteData() also writes -- the
        privatekey must be re-derivable from the seed + content.json's
        own address_index alone."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                address, address_index, site_data = await user.getNewSiteData()
                original_privatekey = site_data["privatekey"]
                del user.sites[address]["privatekey"]  # Simulate the cache being lost

                site = Site(address, data_dir / address)
                site.permissions.append("ADMIN")
                await site.storage.writeJson("content.json", {"address_index": address_index})
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "siteRecoverPrivatekey")
                return reply, user.sites[address].get("privatekey"), original_privatekey

        reply, recovered_privatekey, original_privatekey = compat.run(scenario)
        assert reply["result"] == "ok"
        assert recovered_privatekey == original_privatekey

    def testSiteRecoverPrivatekeyRefusesWhenAlreadyStored(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                address, address_index, site_data = await user.getNewSiteData()  # Keeps its own privatekey

                site = Site(address, data_dir / address)
                site.permissions.append("ADMIN")
                await site.storage.writeJson("content.json", {"address_index": address_index})
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteRecoverPrivatekey")

        reply = compat.run(scenario)
        assert "already has saved" in reply["result"]["error"]

    def testSiteRecoverPrivatekeyRefusesWithoutAddressIndex(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                address = "1TestSidebarNoIndexSiteAAAAA1"

                site = Site(address, data_dir / address)
                site.permissions.append("ADMIN")
                await site.storage.writeJson("content.json", {})
                await site.content_manager.loadContent("content.json")

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteRecoverPrivatekey")

        reply = compat.run(scenario)
        assert "No address_index" in reply["result"]["error"]

    def testSiteRecoverPrivatekeyRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                address = "1TestSidebarNonAdminRecoverA1"
                site = Site(address, data_dir / address)  # No ADMIN permission

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteRecoverPrivatekey")

        reply = compat.run(scenario)
        assert "error" in reply

    def testUserSetSitePrivatekeyStoresGivenKey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()
                address = "1TestSidebarSetPrivatekeyAAA1"
                site = Site(address, data_dir / address)
                site.permissions.append("ADMIN")

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "userSetSitePrivatekey", {"privatekey": "some-privatekey-value"})
                return reply, user.sites.get(address, {}).get("privatekey")

        reply, stored = compat.run(scenario)
        assert reply["result"] == "ok"
        assert stored == "some-privatekey-value"
