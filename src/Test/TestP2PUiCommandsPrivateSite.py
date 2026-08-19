import base64
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
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    while True:
        response = json.loads(await ws.get_message())
        if response.get("cmd") == "response" and response.get("to") == msg_id:
            return response


class TestP2PUiCommandsPrivateSite:
    """Websocket-command-level coverage of the private-site UI flow --
    siteRequestAccess -> siteAddRecipient -> siteSign -> fileGet/
    fileWrite, matching this file's own TestP2PUiCommandsSiteSignPublish
    conventions. The recipient's Site object shares the owner's on-disk
    directory (simulating "already downloaded", the same shortcut
    TestP2PSitePrivate.py uses) rather than going over a real network
    connection -- that path is already covered end-to-end by
    TestP2PPrivateSitePropagation.py."""

    def testFileGetOnPrivateSiteBeforeApprovalReturnsNoAccess(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as owner_users_dir, \
                    tempfile.TemporaryDirectory() as stranger_users_dir:
                data_dir = pathlib.Path(d)
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                site_owner = Site(address, data_dir)
                site_owner.permissions = ["ADMIN"]
                await site_owner.storage.write("index.html", b"<h1>secret</h1>")

                owner_site_manager = SiteManager(pathlib.Path(owner_users_dir))
                server_owner = UiServer(sites={address: site_owner}, site_manager=owner_site_manager)

                # A recipient the owner approved, so the site really is private.
                approved_privatekey = CryptBitcoin.newPrivatekey()
                approved_user_manager = UserManager(pathlib.Path(owner_users_dir) / "approved")
                approved_user = approved_user_manager.create()

                async with server_owner.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server_owner, site_owner)) as ws:
                        from Crypt import CryptEcies
                        auth_privatekey = approved_user.getAuthPrivatekey(address)
                        _, signature = CryptEcies.signAccessRequest(address, auth_privatekey)
                        await _call(ws, "siteAddRecipient", {
                            "address": approved_user.getAuthAddress(address), "signature": signature,
                        })
                        await _call(ws, "siteSign", {"privatekey": privatekey}, msg_id=2)

                # A stranger who was never approved, on a fresh view of the same disk.
                site_stranger = Site(address, data_dir, allow_create=False)
                stranger_user_manager = UserManager(pathlib.Path(stranger_users_dir))
                server_stranger = UiServer(sites={address: site_stranger}, user_manager=stranger_user_manager)

                async with server_stranger.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server_stranger, site_stranger)) as ws:
                        return await _call(ws, "fileGet", {"inner_path": "index.html"})

        reply = compat.run(scenario)
        assert reply["result"]["error"] == "private_site_no_access"
        assert "auth_address" in reply["result"]

    def testFullFlowRequestAccessAddSignThenFileGetDecrypts(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as owner_users_dir, \
                    tempfile.TemporaryDirectory() as recipient_users_dir:
                data_dir = pathlib.Path(d)
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                site_owner = Site(address, data_dir)
                site_owner.permissions = ["ADMIN"]
                await site_owner.storage.write("index.html", b"<h1>secret</h1>")

                owner_site_manager = SiteManager(pathlib.Path(owner_users_dir))
                server_owner = UiServer(sites={address: site_owner}, site_manager=owner_site_manager)

                site_recipient = Site(address, data_dir, allow_create=False)
                recipient_user_manager = UserManager(pathlib.Path(recipient_users_dir))
                server_recipient = UiServer(sites={address: site_recipient}, user_manager=recipient_user_manager)

                async with server_owner.run(), server_recipient.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server_recipient, site_recipient)) as ws:
                        access = await _call(ws, "siteRequestAccess")

                    async with trio_websocket.open_websocket_url(_wsUrl(server_owner, site_owner)) as ws:
                        add_reply = await _call(ws, "siteAddRecipient", {
                            "address": access["result"]["auth_address"],
                            "signature": access["result"]["signature"],
                        })
                        sign_reply = await _call(ws, "siteSign", {"privatekey": privatekey}, msg_id=2)

                    async with trio_websocket.open_websocket_url(_wsUrl(server_recipient, site_recipient)) as ws:
                        file_reply = await _call(ws, "fileGet", {"inner_path": "index.html"})

                return access, add_reply, sign_reply, file_reply

        access, add_reply, sign_reply, file_reply = compat.run(scenario)
        assert "auth_address" in access["result"]
        assert add_reply["result"] == "ok"
        assert sign_reply["result"] == "ok"
        assert file_reply["result"] == "<h1>secret</h1>"

    def testFileWriteOnPrivateSiteEncryptsAtRest(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as owner_users_dir:
                data_dir = pathlib.Path(d)
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                site_owner = Site(address, data_dir)
                site_owner.permissions = ["ADMIN"]

                # Approve one recipient so the site is genuinely private.
                from Crypt import CryptEcies
                recipient_user_manager = UserManager(pathlib.Path(owner_users_dir) / "recipient")
                recipient_user = recipient_user_manager.create()
                auth_privatekey = recipient_user.getAuthPrivatekey(address)
                _, signature = CryptEcies.signAccessRequest(address, auth_privatekey)

                owner_site_manager = SiteManager(pathlib.Path(owner_users_dir))
                server_owner = UiServer(sites={address: site_owner}, site_manager=owner_site_manager)

                async with server_owner.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server_owner, site_owner)) as ws:
                        await _call(ws, "siteAddRecipient", {
                            "address": recipient_user.getAuthAddress(address), "signature": signature,
                        })
                        await _call(ws, "siteSign", {"privatekey": privatekey}, msg_id=2)

                        new_content_b64 = base64.b64encode(b"<h1>brand new secret</h1>").decode()
                        write_reply = await _call(
                            ws, "fileWrite", {"inner_path": "new.html", "content_base64": new_content_b64}, msg_id=3,
                        )

                on_disk = await site_owner.storage.read("new.html")
                return write_reply, on_disk, site_owner.private_key

        write_reply, on_disk, content_key = compat.run(scenario)
        assert write_reply["result"] == "ok"
        assert on_disk != b"<h1>brand new secret</h1>"  # encrypted at rest
        from Crypt import CryptAes
        assert CryptAes.decrypt(on_disk, content_key) == b"<h1>brand new secret</h1>"

    def testRevocationRemovesFileGetAccess(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as owner_users_dir, \
                    tempfile.TemporaryDirectory() as recipient_users_dir:
                data_dir = pathlib.Path(d)
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)

                site_owner = Site(address, data_dir)
                site_owner.permissions = ["ADMIN"]
                await site_owner.storage.write("index.html", b"<h1>secret</h1>")

                owner_site_manager = SiteManager(pathlib.Path(owner_users_dir))
                server_owner = UiServer(sites={address: site_owner}, site_manager=owner_site_manager)

                site_recipient = Site(address, data_dir, allow_create=False)
                recipient_user_manager = UserManager(pathlib.Path(recipient_users_dir))
                server_recipient = UiServer(sites={address: site_recipient}, user_manager=recipient_user_manager)

                async with server_owner.run(), server_recipient.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server_recipient, site_recipient)) as ws:
                        access = await _call(ws, "siteRequestAccess")

                    async with trio_websocket.open_websocket_url(_wsUrl(server_owner, site_owner)) as ws:
                        await _call(ws, "siteAddRecipient", {
                            "address": access["result"]["auth_address"],
                            "signature": access["result"]["signature"],
                        })
                        await _call(ws, "siteSign", {"privatekey": privatekey}, msg_id=2)

                    async with trio_websocket.open_websocket_url(_wsUrl(server_recipient, site_recipient)) as ws:
                        before = await _call(ws, "fileGet", {"inner_path": "index.html"})

                    async with trio_websocket.open_websocket_url(_wsUrl(server_owner, site_owner)) as ws:
                        await _call(ws, "siteRemoveRecipient", {"address": access["result"]["auth_address"]})
                        await _call(ws, "siteSign", {"privatekey": privatekey}, msg_id=2)

                    # A fresh recipient Site instance -- the old one already
                    # cached the decrypted content and its own unlocked key,
                    # same as a real client would after its first successful
                    # access; revocation takes effect for anyone re-deriving
                    # access from what's on disk now.
                    site_recipient_after = Site(address, data_dir, allow_create=False)
                    server_recipient_after = UiServer(
                        sites={address: site_recipient_after}, user_manager=recipient_user_manager,
                    )
                    async with server_recipient_after.run():
                        async with trio_websocket.open_websocket_url(
                            _wsUrl(server_recipient_after, site_recipient_after)
                        ) as ws:
                            after = await _call(ws, "fileGet", {"inner_path": "index.html"})

                return before, after

        before, after = compat.run(scenario)
        assert before["result"] == "<h1>secret</h1>"
        assert after["result"]["error"] == "private_site_no_access"

    def testSiteRequestAccessReturnsRealVerifiableSignature(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                address = "1TestPrivateSiteAddrAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                site.permissions = []
                user_manager = UserManager(pathlib.Path(users_dir))
                server = UiServer(sites={address: site}, user_manager=user_manager)

                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "siteRequestAccess")

        reply = compat.run(scenario)
        from Crypt import CryptEcies
        result = reply["result"]
        recovered = CryptEcies.recoverPublicKey(result["signature"], result["message"])
        assert CryptEcies.publicToAddress(recovered) == result["auth_address"]
