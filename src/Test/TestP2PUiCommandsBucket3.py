import json
import pathlib
import tempfile

import trio_websocket

from Crypt import CryptBitcoin
from P2P.Ui.UiServer import UiServer
from P2P.Site import Site
from P2P.SiteManager import SiteManager
from P2P.UserManager import UserManager
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/Ui?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PUiCommandsSiteSignPublish:
    def testSiteSignWithExplicitPrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d))
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "siteSign", {"privatekey": privatekey})
                        return reply, site.storage.isFile("content.json")

        reply, has_content = compat.run(scenario)
        assert reply["result"] == "ok"
        assert has_content is True

    def testSiteSignWithoutAdminPermissionErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d))  # No ADMIN permission

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteSign", {"privatekey": privatekey})

        reply = compat.run(scenario)
        assert "permission" in reply["error"]

    def testSiteSignUsesStoredUserPrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()

                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]
                site_data = user.getSiteData(address)
                site_data["privatekey"] = privatekey

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteSign")  # No privatekey param

        reply = compat.run(scenario)
        assert reply["result"] == "ok"

    def testSitePublishSignsAndMarksServing(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d), serving=False)
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        reply = await _call(ws, "sitePublish", {"privatekey": privatekey})
                        return reply, site.isServing()

        reply, serving = compat.run(scenario)
        assert reply["result"] == "ok"
        assert serving is True


class TestP2PUiCommandsCerts:
    def testCertAddThenCertListShowsSelected(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()

                address = "1TestCertSiteAAAAAAAAAAAAAAA"
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]
                site_data = user.getSiteData(address)  # Generates auth_address/auth_privatekey
                auth_address = site_data["auth_address"]

                issuer_privatekey = CryptBitcoin.newPrivatekey()
                cert_sign = CryptBitcoin.sign("%s#web/alice" % auth_address, issuer_privatekey)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        add_reply = await _call(ws, "certAdd", {
                            "auth_address": auth_address, "domain": "example.bit",
                            "auth_type": "web", "auth_user_name": "alice", "cert_sign": cert_sign,
                        }, msg_id=1)
                        set_reply = await _call(ws, "certSet", {"domain": "example.bit"}, msg_id=2)
                        list_reply = await _call(ws, "certList", msg_id=3)
                        return add_reply, set_reply, list_reply

        add_reply, set_reply, list_reply = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert set_reply["result"] == "ok"
        certs = list_reply["result"]
        assert certs[0]["domain"] == "example.bit"
        assert certs[0]["selected"] is True


class TestP2PUiCommandsSiteManagement:
    def testSiteAddDeletePauseResumeAndList(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                admin_address = "1TestAdminSiteAAAAAAAAAAAAA1"
                admin_site = site_manager.add(admin_address)
                admin_site.permissions = ["ADMIN"]

                target_address = "1TestTargetSiteAAAAAAAAAAAA2"

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, admin_site)) as ws:
                        add_reply = await _call(ws, "siteAdd", {"address": target_address}, msg_id=1)
                        pause_reply = await _call(ws, "sitePause", {"address": target_address}, msg_id=2)
                        target_serving_after_pause = site_manager.sites[target_address].isServing()
                        resume_reply = await _call(ws, "siteResume", {"address": target_address}, msg_id=3)
                        target_serving_after_resume = site_manager.sites[target_address].isServing()
                        list_reply = await _call(ws, "siteList", msg_id=4)
                        delete_reply = await _call(ws, "siteDelete", {"address": target_address}, msg_id=5)
                        return (
                            add_reply, pause_reply, target_serving_after_pause,
                            resume_reply, target_serving_after_resume, list_reply, delete_reply,
                            target_address in site_manager.sites,
                        )

        (add_reply, pause_reply, serving_after_pause, resume_reply, serving_after_resume,
         list_reply, delete_reply, still_present) = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert pause_reply["result"] == "Paused"
        assert serving_after_pause is False
        assert resume_reply["result"] == "Resumed"
        assert serving_after_resume is True
        assert len(list_reply["result"]) == 2  # admin site + target site
        assert delete_reply["result"] == "Deleted"
        assert still_present is False

    def testSiteAddWithoutAdminPermissionErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                address = "1TestNonAdminSiteAAAAAAAAAAA"
                site = site_manager.add(address)  # No ADMIN permission

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteAdd", {"address": "1SomeOtherSiteAAAAAAAAAAAAAA"})

        reply = compat.run(scenario)
        assert "permission" in reply["error"]


class TestP2PUiCommandsPermissions:
    def testPermissionAddAndRemove(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestPermSiteAAAAAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        add_reply = await _call(ws, "permissionAdd", {"permission": "NOSANDBOX"}, msg_id=1)
                        after_add = list(site.permissions)
                        remove_reply = await _call(ws, "permissionRemove", {"permission": "NOSANDBOX"}, msg_id=2)
                        after_remove = list(site.permissions)
                        details_reply = await _call(ws, "permissionDetails", {"permission": "ADMIN"}, msg_id=3)
                        return add_reply, after_add, remove_reply, after_remove, details_reply

        add_reply, after_add, remove_reply, after_remove, details_reply = compat.run(scenario)
        assert add_reply["result"] == "ok"
        assert "NOSANDBOX" in after_add
        assert remove_reply["result"] == "ok"
        assert "NOSANDBOX" not in after_remove
        assert "administrate" in details_reply["result"]


class TestP2PUiCommandsUserSettings:
    def testUserSiteAndGlobalSettingsRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()

                address = "1TestUserSettingsSiteAAAAAAA"
                site = Site(address, data_dir / address)
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        site_set = await _call(ws, "userSetSettings", {"settings": {"theme": "dark"}}, msg_id=1)
                        site_get = await _call(ws, "userGetSettings", msg_id=2)
                        global_set = await _call(ws, "userSetGlobalSettings", {"settings": {"lang": "en"}}, msg_id=3)
                        global_get = await _call(ws, "userGetGlobalSettings", msg_id=4)
                        return site_set, site_get, global_set, global_get

        site_set, site_get, global_set, global_get = compat.run(scenario)
        assert site_set["result"] == "ok"
        assert site_get["result"] == {"theme": "dark"}
        assert global_set["result"] == "ok"
        assert global_get["result"] == {"lang": "en"}


class TestP2PUiCommandsDbQuery:
    def testDbQueryReturnsRealRows(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestDbQuerySiteAAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                schema = {
                    "db_name": "Test", "db_file": "site.db", "version": 1,
                    "maps": {"data\\.json$": {"to_keyvalue": ["title"]}},
                }
                await site.storage.writeJson("dbschema.json", schema)
                await site.storage.writeJson("data.json", {"title": "ws db test"})
                # rebuildDb() walks content_manager.contents for the file
                # list -- doesn't need a *verified* content.json, just one
                # naming the files to import.
                site.content_manager.contents["content.json"] = {"files": {"data.json": {}}}
                await site.storage.rebuildDb(site.content_manager, reason="test setup")

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "dbQuery", {"query": "SELECT * FROM keyvalue WHERE key = 'title'"})

        reply = compat.run(scenario)
        assert reply["result"][0]["value"] == "ws db test"

    def testDbQueryWithoutSchemaReturnsError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestDbQueryNoSchemaAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "dbQuery", {"query": "SELECT 1"})

        reply = compat.run(scenario)
        assert "error" in reply["result"]
