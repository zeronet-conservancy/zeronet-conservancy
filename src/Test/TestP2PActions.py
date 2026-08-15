import json
import pathlib
import tempfile

from Crypt import CryptBitcoin
from P2P.actions import Actions, ActionError
from P2P import compat


class TestP2PActionsSite:
    def testSiteCreateWithMasterSeedProducesSignedSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                result = await actions.siteCreate()
                site = actions.site_manager.get(result["address"])
                content = await site.storage.loadJson("content.json")
                return result, site.storage.isFile("index.html"), content

        result, has_index, content = compat.run(scenario)
        assert CryptBitcoin.privatekeyToAddress(result["privatekey"]) == result["address"]
        assert has_index is True
        assert "index.html" in content["files"]
        assert content["postmessage_nonce_security"] is True

    def testSiteCreateStoresPrivatekeyInUsersJson(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                result = await actions.siteCreate()
                user = await actions.user_manager.get()
                return result, user

        result, user = compat.run(scenario)
        assert user.sites[result["address"]]["privatekey"] == result["privatekey"]

    def testSiteCreateWithoutMasterSeedSkipsUserManager(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                result = await actions.siteCreate(use_master_seed=False)
                user = await actions.user_manager.get()
                return result, user

        result, user = compat.run(scenario)
        assert CryptBitcoin.privatekeyToAddress(result["privatekey"]) == result["address"]
        assert user is None

    def testSiteSignWithExplicitPrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                actions.site_manager.add(address)

                succ = await actions.siteSign(address, privatekey=privatekey)
                site = actions.site_manager.get(address)
                return succ, site.storage.isFile("content.json")

        succ, has_content = compat.run(scenario)
        assert succ is True
        assert has_content is True

    def testSiteSignUsesStoredPrivatekeyFromUser(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                created = await actions.siteCreate()
                # Re-sign without passing privatekey -- must recover it from users.json
                succ = await actions.siteSign(created["address"])
                return succ

        assert compat.run(scenario) is True

    def testSiteSignWithoutPrivatekeyRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                actions.site_manager.add(address)
                try:
                    await actions.siteSign(address)
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testSiteSignUnknownSiteRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                try:
                    await actions.siteSign("1NoSuchSiteAAAAAAAAAAAAAAAA")
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testSiteVerifyAllGoodAfterCreate(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                created = await actions.siteCreate()
                return await actions.siteVerify(created["address"])

        result = compat.run(scenario)
        assert result["bad_files"] == []

    def testSiteVerifyDetectsTamperedFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                created = await actions.siteCreate()
                site = actions.site_manager.get(created["address"])
                # Tamper with the file's content on disk after signing --
                # hash in content.json no longer matches.
                await site.storage.write("index.html", b"tampered content")
                return await actions.siteVerify(created["address"])

        result = compat.run(scenario)
        assert "index.html" in result["bad_files"]

    def testDbRebuildAndDbQueryRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                await actions.site_manager.load()
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = actions.site_manager.add(address, own=True)

                schema = {
                    "db_name": "Test", "db_file": "site.db", "version": 1,
                    "maps": {"data\\.json$": {"to_keyvalue": ["title"]}},
                }
                await site.storage.writeJson("dbschema.json", schema)
                await site.storage.writeJson("data.json", {"title": "cli db test"})
                await site.content_manager.sign(privatekey)

                applied = await actions.dbRebuild(address)
                rows = await actions.dbQuery(address, "SELECT * FROM keyvalue WHERE key = 'title'")
                return applied, rows

        applied, rows = compat.run(scenario)
        assert applied is True
        assert rows[0]["value"] == "cli db test"

    def testDbQueryUnknownSiteRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                actions = Actions(pathlib.Path(d))
                try:
                    await actions.dbQuery("1NoSuchSiteAAAAAAAAAAAAAAAA", "SELECT 1")
                    return "no-error"
                except ActionError:
                    return "raised"

        assert compat.run(scenario) == "raised"


class TestP2PActionsCrypto:
    def testCryptPrivatekeyToAddress(self):
        actions = Actions(pathlib.Path("/tmp"))
        privatekey = CryptBitcoin.newPrivatekey()
        assert actions.cryptPrivatekeyToAddress(privatekey) == CryptBitcoin.privatekeyToAddress(privatekey)

    def testCryptSignAndVerifyRoundTrip(self):
        actions = Actions(pathlib.Path("/tmp"))
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        sign = actions.cryptSign("hello world", privatekey)
        assert actions.cryptVerify("hello world", sign, address) is True
        assert actions.cryptVerify("tampered", sign, address) is False

    def testCryptGetPrivatekeyDeterministic(self):
        actions = Actions(pathlib.Path("/tmp"))
        master_seed = CryptBitcoin.newSeed()
        key1 = actions.cryptGetPrivatekey(master_seed, 0)
        key2 = actions.cryptGetPrivatekey(master_seed, 0)
        key3 = actions.cryptGetPrivatekey(master_seed, 1)
        assert key1 == key2
        assert key1 != key3

    def testCryptGetPrivatekeyRejectsShortSeed(self):
        actions = Actions(pathlib.Path("/tmp"))
        try:
            actions.cryptGetPrivatekey("tooshort")
            assert False, "expected ActionError"
        except ActionError:
            pass
