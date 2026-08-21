import json
import pathlib
import tempfile

import httpx
import trio_websocket

from P2P.Ui.UiServer import UiServer, MULTIUSER_COOKIE
from P2P.Site import Site
from P2P.UserManager import UserManager
from P2P import compat


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    while True:
        response = json.loads(await ws.get_message())
        if response.get("cmd") == "response" and response.get("to") == msg_id:
            return response


class TestP2PUiMultiuser:
    def testWrapperPageIssuesAndReusesMasterAddressCookie(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestMultiuserCookieSiteAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                server = UiServer(
                    sites={site.address: site}, homepage=site.address,
                    user_manager=UserManager(pathlib.Path(root), multiuser=True),
                )
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        first = await client.get("%s/%s/" % (base_url, site.address))
                        first_cookie = client.cookies.get(MULTIUSER_COOKIE)
                        second = await client.get("%s/%s/" % (base_url, site.address))
                        second_cookie = client.cookies.get(MULTIUSER_COOKIE)
                return first.status_code, first_cookie, second_cookie

        status, first_cookie, second_cookie = compat.run(scenario)
        assert status == 200
        assert first_cookie  # A real account was minted on first visit
        assert second_cookie == first_cookie  # Same browser, same account -- no new one created

    def testDifferentBrowsersGetDifferentIsolatedAccounts(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestMultiuserIsolationSiteAA1", pathlib.Path(root), permissions=["ADMIN"])
                server = UiServer(
                    sites={site.address: site}, homepage=site.address,
                    user_manager=UserManager(pathlib.Path(root), multiuser=True),
                )
                async with server.run():
                    base_url = server.bound_addresses[0]
                    ws_base = base_url.replace("http://", "ws://")

                    async with httpx.AsyncClient() as browser_a, httpx.AsyncClient() as browser_b:
                        await browser_a.get("%s/%s/" % (base_url, site.address))
                        await browser_b.get("%s/%s/" % (base_url, site.address))
                        cookie_a = browser_a.cookies.get(MULTIUSER_COOKIE)
                        cookie_b = browser_b.cookies.get(MULTIUSER_COOKIE)

                    assert cookie_a != cookie_b

                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (ws_base, site.wrapper_key)
                    header_a = [(b"cookie", ("%s=%s" % (MULTIUSER_COOKIE, cookie_a)).encode())]
                    header_b = [(b"cookie", ("%s=%s" % (MULTIUSER_COOKIE, cookie_b)).encode())]

                    async with trio_websocket.open_websocket_url(ws_url, extra_headers=header_a) as ws_a:
                        await _call(ws_a, "userSetGlobalSettings", {"settings": {"theme": "dark"}}, msg_id=1)
                        settings_a = await _call(ws_a, "userGetGlobalSettings", msg_id=2)

                    async with trio_websocket.open_websocket_url(ws_url, extra_headers=header_b) as ws_b:
                        settings_b = await _call(ws_b, "userGetGlobalSettings", msg_id=1)

                return settings_a["result"], settings_b["result"]

        settings_a, settings_b = compat.run(scenario)
        assert settings_a == {"theme": "dark"}
        assert settings_b != {"theme": "dark"}  # Browser B never saw browser A's setting

    def testSingleUserModeStaysCookielessByDefault(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestSingleUserNoCookieSiteA1", pathlib.Path(root), permissions=["ADMIN"])
                server = UiServer(
                    sites={site.address: site}, homepage=site.address,
                    user_manager=UserManager(pathlib.Path(root)),  # multiuser=False (default)
                )
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        response = await client.get("%s/%s/" % (base_url, site.address))
                        cookie = client.cookies.get(MULTIUSER_COOKIE)
                return response.status_code, cookie

        status, cookie = compat.run(scenario)
        assert status == 200
        assert cookie is None

    def testUserShowMasterSeedPushesRealSeed(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestShowSeedSiteAAAAAAAAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                user_manager = UserManager(pathlib.Path(root))
                user = user_manager.create()
                server = UiServer(sites={site.address: site}, homepage=site.address, user_manager=user_manager)
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    async with trio_websocket.open_websocket_url(ws_url) as ws:
                        await ws.send_message(json.dumps({"cmd": "userShowMasterSeed", "params": {}, "id": 1}))
                        messages = [json.loads(await ws.get_message()) for _ in range(2)]
                return messages, user.master_seed

        messages, master_seed = compat.run(scenario)
        push = next(m for m in messages if m.get("cmd") == "notification")
        assert master_seed in push["params"][1]

    def testUserLoginCreatesAccountAndSetsCookie(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestUserLoginSiteAAAAAAAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                user_manager = UserManager(pathlib.Path(root), multiuser=True)
                server = UiServer(sites={site.address: site}, homepage=site.address, user_manager=user_manager)
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    from Crypt import CryptBitcoin
                    seed = CryptBitcoin.newSeed()
                    address = CryptBitcoin.privatekeyToAddress(seed)
                    async with trio_websocket.open_websocket_url(ws_url) as ws:
                        await ws.send_message(json.dumps({"cmd": "userLogin", "params": {"master_seed": seed}, "id": 1}))
                        messages = [json.loads(await ws.get_message()) for _ in range(3)]
                return messages, address, list(user_manager.users.keys())

        messages, address, known_addresses = compat.run(scenario)
        inject = next(m for m in messages if m.get("cmd") == "injectScript")
        assert address in inject["params"]
        assert address in known_addresses  # A real account, actually persisted to the manager

    def testUserLoginRejectsInvalidSeed(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestBadSeedLoginSiteAAAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                server = UiServer(
                    sites={site.address: site}, homepage=site.address,
                    user_manager=UserManager(pathlib.Path(root), multiuser=True),
                )
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    async with trio_websocket.open_websocket_url(ws_url) as ws:
                        return await _call(ws, "userLogin", {"master_seed": ""})

        response = compat.run(scenario)
        assert "error" in response

    def testUserSetSwitchesToKnownAccount(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestUserSetSiteAAAAAAAAAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                user_manager = UserManager(pathlib.Path(root), multiuser=True)
                first = user_manager.create()
                other = user_manager.create()
                server = UiServer(sites={site.address: site}, homepage=site.address, user_manager=user_manager)
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    header = [(b"cookie", ("%s=%s" % (MULTIUSER_COOKIE, first.master_address)).encode())]
                    async with trio_websocket.open_websocket_url(ws_url, extra_headers=header) as ws:
                        await ws.send_message(json.dumps(
                            {"cmd": "userSet", "params": {"master_address": other.master_address}, "id": 1}
                        ))
                        messages = [json.loads(await ws.get_message()) for _ in range(3)]
                return messages, other.master_address

        messages, other_address = compat.run(scenario)
        inject = next(m for m in messages if m.get("cmd") == "injectScript")
        assert other_address in inject["params"]

    def testUserSetRejectsUnknownAccount(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestUserSetUnknownSiteAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                server = UiServer(
                    sites={site.address: site}, homepage=site.address,
                    user_manager=UserManager(pathlib.Path(root), multiuser=True),
                )
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    async with trio_websocket.open_websocket_url(ws_url) as ws:
                        return await _call(ws, "userSet", {"master_address": "1NoSuchAccount"})

        response = compat.run(scenario)
        assert "error" in response

    def testUserSelectFormListsKnownAccountsInMultiuserMode(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestSelectFormSiteAAAAAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                user_manager = UserManager(pathlib.Path(root), multiuser=True)
                first = user_manager.create()
                first.sites["1DummySiteA"] = {}
                first.sites["1DummySiteB"] = {}
                server = UiServer(sites={site.address: site}, homepage=site.address, user_manager=user_manager)
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    header = [(b"cookie", ("%s=%s" % (MULTIUSER_COOKIE, first.master_address)).encode())]
                    async with trio_websocket.open_websocket_url(ws_url, extra_headers=header) as ws:
                        await ws.send_message(json.dumps({"cmd": "userSelectForm", "params": {}, "id": 1}))
                        messages = [json.loads(await ws.get_message()) for _ in range(3)]
                return messages, first.master_address

        messages, master_address = compat.run(scenario)
        push = next(m for m in messages if m.get("cmd") == "notification")
        assert master_address in push["params"][1]

    def testUserSelectFormRejectedInSingleUserMode(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestSelectFormSingleSiteAA1", pathlib.Path(root), permissions=["ADMIN"])
                server = UiServer(
                    sites={site.address: site}, homepage=site.address,
                    user_manager=UserManager(pathlib.Path(root)),  # multiuser=False
                )
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    async with trio_websocket.open_websocket_url(ws_url) as ws:
                        return await _call(ws, "userSelectForm")

        response = compat.run(scenario)
        assert "error" in response

    def testUserLogoutRemovesUserInMultiuserMode(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestUserLogoutSiteAAAAAAAA1", pathlib.Path(root), permissions=["ADMIN"])
                user_manager = UserManager(pathlib.Path(root), multiuser=True)
                user = user_manager.create()
                server = UiServer(sites={site.address: site}, homepage=site.address, user_manager=user_manager)
                async with server.run():
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        server.bound_addresses[0].replace("http://", "ws://"), site.wrapper_key
                    )
                    header = [(b"cookie", ("%s=%s" % (MULTIUSER_COOKIE, user.master_address)).encode())]
                    async with trio_websocket.open_websocket_url(ws_url, extra_headers=header) as ws:
                        await _call(ws, "userLogout")
                return user.master_address in user_manager.users

        still_present = compat.run(scenario)
        assert still_present is False

    def testServerInfoExposesMultiuserFields(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                site = Site("1TestServerInfoMultiuserSA1", pathlib.Path(root), permissions=["ADMIN"])
                user_manager = UserManager(pathlib.Path(root), multiuser=True)
                server = UiServer(sites={site.address: site}, homepage=site.address, user_manager=user_manager)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        await client.get("%s/%s/" % (base_url, site.address))
                        cookie = client.cookies.get(MULTIUSER_COOKIE)
                    ws_url = "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
                        base_url.replace("http://", "ws://"), site.wrapper_key
                    )
                    header = [(b"cookie", ("%s=%s" % (MULTIUSER_COOKIE, cookie)).encode())]
                    async with trio_websocket.open_websocket_url(ws_url, extra_headers=header) as ws:
                        return await _call(ws, "serverInfo")

        response = compat.run(scenario)
        assert response["result"]["multiuser"] is True
        assert "master_address" in response["result"]  # ADMIN-connected session sees its own address
