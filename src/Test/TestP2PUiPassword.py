import pathlib
import tempfile

import httpx

from P2P.Ui.UiServer import UiServer
from P2P.Site import Site
from P2P import compat


def _server(root, **kwargs):
    site = Site("1TestUiPasswordSiteAAAAAAAAAA", pathlib.Path(root), permissions=["ADMIN"])
    return UiServer(sites={site.address: site}, homepage=site.address, **kwargs)


class TestP2PUiPassword:
    def testNoPasswordConfiguredLeavesUiUngated(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                server = _server(root)
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        return await client.get("%s/Config" % base_url)

        response = compat.run(scenario)
        assert response.status_code == 200

    def testUnauthenticatedRequestRedirectsToLogin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                server = _server(root, ui_password="correct-horse")
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        return await client.get("%s/Config" % base_url, follow_redirects=False)

        response = compat.run(scenario)
        assert response.status_code == 303
        assert response.headers["location"].startswith("/Login")

    def testLoginPageItselfIsNotGated(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                server = _server(root, ui_password="correct-horse")
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        return await client.get("%s/Login" % base_url)

        response = compat.run(scenario)
        assert response.status_code == 200
        assert "login_form" in response.text

    def testWrongPasswordReshowsLoginWithoutSettingCookie(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                server = _server(root, ui_password="correct-horse")
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        return await client.post("%s/Login" % base_url, data={"password": "wrong"})

        response = compat.run(scenario)
        assert response.status_code == 200
        assert "bad_password" in response.text
        assert "session_id" not in response.cookies

    def testCorrectPasswordGrantsAccessAndLogoutRevokesIt(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                server = _server(root, ui_password="correct-horse")
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        login = await client.post(
                            "%s/Login" % base_url, data={"password": "correct-horse"}, follow_redirects=False,
                        )
                        had_cookie_after_login = "session_id" in client.cookies
                        authed = await client.get("%s/Config" % base_url)

                        await client.get("%s/Logout" % base_url, follow_redirects=False)
                        after_logout = await client.get("%s/Config" % base_url, follow_redirects=False)

                return login.status_code, had_cookie_after_login, authed.status_code, after_logout.status_code

        login_status, had_cookie, authed_status, after_logout_status = compat.run(scenario)
        assert login_status == 303
        assert had_cookie is True
        assert authed_status == 200
        assert after_logout_status == 303  # logged out -- gated again

    def testUimediaStaysReachableWithoutLogin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                server = _server(root, ui_password="correct-horse")
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        return await client.get("%s/uimedia/all.js" % base_url, follow_redirects=False)

        response = compat.run(scenario)
        assert response.status_code != 303
