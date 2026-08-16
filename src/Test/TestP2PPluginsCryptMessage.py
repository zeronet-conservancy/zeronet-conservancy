import base64
import json
import pathlib
import tempfile

import trio_websocket

# Import side effect: registers this plugin's commands into
# P2P.Ui.commands.COMMAND_HANDLERS. No special ordering needed (unlike
# @acceptPlugins-decorated classes) -- see the plugin's own module
# docstring for why.
import P2P.plugins.CryptMessage  # noqa: F401

from Crypt import CryptBitcoin
from P2P.Site import Site
from P2P.User import User
from P2P.UserManager import UserManager
from P2P.Ui.UiServer import UiServer
from P2P.plugins.CryptMessage.UserPlugin import UserPlugin as _CryptMessageUserPlugin
from P2P import compat

# UserPlugin.py's own registerTo("User") only takes effect on a User class
# decorated with @acceptPlugins AFTER this plugin package was imported --
# see P2P.PluginManager's own docstring on that ordering requirement.
# Whether that holds depends on which OTHER test module pytest happened to
# import P2P.User through first in this same process, which is exactly the
# "production bootstrap-ordering wiring, separate follow-up work" gap
# TestP2PPluginsZeroname.py/TestP2PPluginsContentFilter.py's own composed-
# subclass workaround already documents -- but User here is constructed
# deep inside UserManager.create()/load(), with no way to substitute a
# locally-composed subclass the way those tests do. Attaching the two
# methods directly, idempotently, is the equivalent fix for a class this
# test can't intercept construction of: it tests the plugin's own actual
# derivation logic (the real risk), not the import-order wiring.
if not hasattr(User, "getEncryptPublickey"):
    User.getEncryptPrivatekey = _CryptMessageUserPlugin.getEncryptPrivatekey
    User.getEncryptPublickey = _CryptMessageUserPlugin.getEncryptPublickey


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsCryptMessage:
    def testAesEncryptDecryptRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestCryptMsgSiteAAAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        enc = await _call(ws, "aesEncrypt", {"text": "hello world"}, msg_id=1)
                        key, iv, encrypted = enc["result"]
                        dec = await _call(ws, "aesDecrypt", {"iv": iv, "encrypted": encrypted, "key": key}, msg_id=2)
                        return dec

        reply = compat.run(scenario)
        assert reply["result"] == "hello world"

    def testAesDecryptWithWrongKeyReturnsNone(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestCryptMsgSite2AAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        enc = await _call(ws, "aesEncrypt", {"text": "secret"}, msg_id=1)
                        _key, iv, encrypted = enc["result"]
                        wrong = await _call(ws, "aesEncrypt", {}, msg_id=2)
                        wrong_key = wrong["result"][0]
                        return await _call(ws, "aesDecrypt", {"iv": iv, "encrypted": encrypted, "key": wrong_key}, msg_id=3)

        reply = compat.run(scenario)
        assert reply["result"] is None

    def testEcdsaSignAndVerifyRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestCryptMsgSite3AAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        privatekey = CryptBitcoin.newPrivatekey()
                        signer_address = CryptBitcoin.privatekeyToAddress(privatekey)
                        sign_reply = await _call(
                            ws, "ecdsaSign", {"data": "hello", "privatekey": privatekey}, msg_id=1
                        )
                        verify_reply = await _call(
                            ws, "ecdsaVerify",
                            {"data": "hello", "address": signer_address, "signature": sign_reply["result"]},
                            msg_id=2,
                        )
                        return verify_reply

        reply = compat.run(scenario)
        assert reply["result"] is True

    def testEcdsaSignFallsBackToStoredUserPrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()

                address = "1TestCryptMsgSite4AAAAAAAAAA"
                site = Site(address, data_dir / address)
                auth_address = user.getSiteData(address)["auth_address"]

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        sign_reply = await _call(ws, "ecdsaSign", {"data": "hello"}, msg_id=1)  # No privatekey param
                        verify_reply = await _call(
                            ws, "ecdsaVerify",
                            {"data": "hello", "address": auth_address, "signature": sign_reply["result"]},
                            msg_id=2,
                        )
                        return verify_reply

        reply = compat.run(scenario)
        assert reply["result"] is True

    def testEccPrivToPubToAddrRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestCryptMsgSite5AAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                privatekey = CryptBitcoin.newPrivatekey()

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        pub_reply = await _call(ws, "eccPrivToPub", {"privatekey": privatekey}, msg_id=1)
                        addr_reply = await _call(ws, "eccPubToAddr", {"publickey": pub_reply["result"]}, msg_id=2)
                        return pub_reply, addr_reply

        pub_reply, addr_reply = compat.run(scenario)
        assert isinstance(pub_reply["result"], str)
        bytes.fromhex(pub_reply["result"])  # Real hex, doesn't raise
        assert isinstance(addr_reply["result"], str)
        assert addr_reply["result"].startswith("1")  # Bitcoin-style address

    def testUserPublickeyIsRealAndStableAcrossCalls(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                address = "1TestCryptMsgSite6AAAAAAAAAA"
                site = Site(address, data_dir / address)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        first = await _call(ws, "userPublickey", msg_id=1)
                        second = await _call(ws, "userPublickey", msg_id=2)
                        return first, second

        first, second = compat.run(scenario)
        assert first["result"] == second["result"]  # Cached, not re-derived each call
        base64.b64decode(first["result"])  # Real base64, doesn't raise

    def testEciesEncryptDecryptRoundTripWithUsersOwnKeypair(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                address = "1TestCryptMsgSite7AAAAAAAAAA"
                site = Site(address, data_dir / address)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        enc = await _call(ws, "eciesEncrypt", {"text": "a secret message"}, msg_id=1)
                        dec = await _call(ws, "eciesDecrypt", {"param": enc["result"]}, msg_id=2)
                        return enc, dec

        enc, dec = compat.run(scenario)
        assert isinstance(enc["result"], str)
        assert dec["result"] == "a secret message"

    def testEciesEncryptDecryptWithExplicitKeypair(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                address = "1TestCryptMsgSite8AAAAAAAAAA"
                site = Site(address, pathlib.Path(d))
                privatekey = CryptBitcoin.newPrivatekey()

                server = UiServer(sites={address: site})
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        pub_reply = await _call(ws, "eccPrivToPub", {"privatekey": privatekey}, msg_id=1)
                        publickey_b64 = base64.b64encode(bytes.fromhex(pub_reply["result"])).decode("utf8")
                        enc = await _call(
                            ws, "eciesEncrypt", {"text": "explicit key message", "publickey": publickey_b64}, msg_id=2,
                        )
                        dec = await _call(
                            ws, "eciesDecrypt", {"param": enc["result"], "privatekey": privatekey}, msg_id=3,
                        )
                        return dec

        reply = compat.run(scenario)
        assert reply["result"] == "explicit key message"

    def testEciesEncryptReturnAesKeyGivesEncryptedAndKeyPair(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                address = "1TestCryptMsgSite9AAAAAAAAAA"
                site = Site(address, data_dir / address)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(
                            ws, "eciesEncrypt", {"text": "hi", "return_aes_key": True}, msg_id=1,
                        )

        reply = compat.run(scenario)
        assert len(reply["result"]) == 2
        base64.b64decode(reply["result"][0])
        base64.b64decode(reply["result"][1])

    def testEciesDecryptWithWrongPrivatekeyReturnsNone(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                address = "1TestCryptMsgSiteAAAAAAAAAB0"
                site = Site(address, data_dir / address)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        enc = await _call(ws, "eciesEncrypt", {"text": "top secret"}, msg_id=1)
                        wrong_privatekey = CryptBitcoin.newPrivatekey()
                        return await _call(
                            ws, "eciesDecrypt", {"param": enc["result"], "privatekey": wrong_privatekey}, msg_id=2,
                        )

        reply = compat.run(scenario)
        assert reply["result"] is None
