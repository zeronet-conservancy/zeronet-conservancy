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
