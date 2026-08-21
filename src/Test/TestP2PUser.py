import json
import pathlib
import tempfile

from Crypt import CryptBitcoin
from P2P.User import User
from P2P.UserManager import UserManager
from P2P import compat


SITE_ADDRESS = "1TestUserSiteAAAAAAAAAAAAAA"


class TestP2PUser:
    def testNewUserGetsFreshSeedAndAddress(self):
        with tempfile.TemporaryDirectory() as d:
            user = User(pathlib.Path(d) / "users.json")
            assert user.master_seed
            assert user.master_address == CryptBitcoin.privatekeyToAddress(user.master_seed)

    def testDeterministicFromMasterSeed(self):
        with tempfile.TemporaryDirectory() as d:
            seed = CryptBitcoin.newSeed()
            user1 = User(pathlib.Path(d) / "users.json", master_seed=seed)
            user2 = User(pathlib.Path(d) / "users.json", master_seed=seed)
            assert user1.master_address == user2.master_address

    def testGetSiteDataGeneratesDeterministicAuthKeyFromSameSeed(self):
        with tempfile.TemporaryDirectory() as d:
            seed = CryptBitcoin.newSeed()
            user1 = User(pathlib.Path(d) / "users.json", master_seed=seed)
            user2 = User(pathlib.Path(d) / "users.json", master_seed=seed)
            data1 = user1.getSiteData(SITE_ADDRESS)
            data2 = user2.getSiteData(SITE_ADDRESS)
            assert data1["auth_address"] == data2["auth_address"]
            assert data1["auth_privatekey"] == data2["auth_privatekey"]

    def testGetSiteDataWithoutCreateReturnsEmpty(self):
        with tempfile.TemporaryDirectory() as d:
            user = User(pathlib.Path(d) / "users.json")
            data = user.getSiteData(SITE_ADDRESS, create=False)
            assert data == {"auth_address": None, "auth_privatekey": None}
            assert SITE_ADDRESS not in user.sites

    def testDeleteSiteDataMarksDirty(self):
        with tempfile.TemporaryDirectory() as d:
            user = User(pathlib.Path(d) / "users.json")
            user.getSiteData(SITE_ADDRESS)
            user._dirty = False
            user.deleteSiteData(SITE_ADDRESS)
            assert SITE_ADDRESS not in user.sites
            assert user._dirty is True

    def testSaveThenReloadRoundTrips(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                users_json = pathlib.Path(d) / "users.json"
                seed = CryptBitcoin.newSeed()
                user = User(users_json, master_seed=seed)
                user.getSiteData(SITE_ADDRESS)
                user.settings["theme"] = "dark"
                await user.save()

                reloaded = User(users_json, master_address=user.master_address, data=json.loads(users_json.read_text())[user.master_address])
                return user, reloaded

        user, reloaded = compat.run(scenario)
        assert reloaded.master_seed == user.master_seed
        assert reloaded.sites[SITE_ADDRESS]["auth_address"] == user.sites[SITE_ADDRESS]["auth_address"]
        assert reloaded.settings["theme"] == "dark"

    def testSaveDoesNotClobberOtherUsersInSameFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                users_json = pathlib.Path(d) / "users.json"
                user_a = User(users_json)
                user_b = User(users_json)
                await user_a.save()
                await user_b.save()
                return json.loads(users_json.read_text()), user_a.master_address, user_b.master_address

        data, addr_a, addr_b = compat.run(scenario)
        assert addr_a in data
        assert addr_b in data

    def testGetNewSiteDataProducesUsablePrivatekey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                user = User(pathlib.Path(d) / "users.json")
                return await user.getNewSiteData()

        address, index, site_data = compat.run(scenario)
        assert CryptBitcoin.privatekeyToAddress(site_data["privatekey"]) == address

    def testAuthAddressFallsBackToCertWhenSet(self):
        with tempfile.TemporaryDirectory() as d:
            user = User(pathlib.Path(d) / "users.json")
            plain_auth_address = user.getAuthAddress(SITE_ADDRESS)

            user.certs["example.bit"] = {
                "auth_address": "1CertAuthAddress",
                "auth_privatekey": "certprivkey",
                "auth_type": "web",
                "auth_user_name": "alice",
                "cert_sign": "sig",
            }
            user.setCert(SITE_ADDRESS, "example.bit")

            assert user.getAuthAddress(SITE_ADDRESS) == "1CertAuthAddress"
            assert user.getAuthAddress(SITE_ADDRESS) != plain_auth_address
            assert user.getCertUserId(SITE_ADDRESS) == "alice@example.bit"

    def testSetCertNoneClearsCert(self):
        with tempfile.TemporaryDirectory() as d:
            user = User(pathlib.Path(d) / "users.json")
            user.certs["example.bit"] = {
                "auth_address": "1X", "auth_privatekey": "k", "auth_type": "web",
                "auth_user_name": "alice", "cert_sign": "sig",
            }
            user.setCert(SITE_ADDRESS, "example.bit")
            assert user.getCert(SITE_ADDRESS) is not None
            user.setCert(SITE_ADDRESS, None)
            assert user.getCert(SITE_ADDRESS) is None

    def testAddCertRejectsUnknownAuthAddress(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                user = User(pathlib.Path(d) / "users.json")
                try:
                    await user.addCert("1NoSuchAuthAddress", "example.bit", "web", "alice", "sig")
                    return "no-error"
                except ValueError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testAddCertAcceptedThenConflictingRejected(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                user = User(pathlib.Path(d) / "users.json")
                site_data = user.getSiteData(SITE_ADDRESS)
                auth_address = site_data["auth_address"]

                first = await user.addCert(auth_address, "example.bit", "web", "alice", "sig-a")
                same = await user.addCert(auth_address, "example.bit", "web", "alice", "sig-a")
                conflict = await user.addCert(auth_address, "example.bit", "web", "bob", "sig-b")
                return first, same, conflict

        first, same, conflict = compat.run(scenario)
        assert first is True
        assert same is None
        assert conflict is False

    def testIssueCertUsesPersistentLocalProviderIdentity(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                user = User(pathlib.Path(d) / "users.json")
                cert = await user.issueCert(SITE_ADDRESS, "zeronet.local", "web", "alice")
                return cert, user.getCertUserId(SITE_ADDRESS), user.settings["local_provider_address"]

        cert, cert_user_id, provider_address = compat.run(scenario)
        assert cert["provider_address"] == provider_address
        assert cert_user_id == "alice@zeronet.local"
        assert CryptBitcoin.verify(
            "%s#web/alice" % cert["auth_address"], cert["provider_address"], cert["cert_sign"]
        ) is True


    def testLocalNamePersistsAcrossReload(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                users_json_path = pathlib.Path(d) / "users.json"
                user = User(users_json_path)
                user.setLocalName("1SomeAuthAddress", "Alice (real one)")
                await user.save()
                reloaded = User(users_json_path, master_address=user.master_address, data=json.load(users_json_path.open())[user.master_address])
                return reloaded.getLocalName("1SomeAuthAddress"), reloaded.listLocalNames()

        name, names = compat.run(scenario)
        assert name == "Alice (real one)"
        assert names == {"1SomeAuthAddress": "Alice (real one)"}

    def testLocalNameIsIndependentOfCertUserId(self):
        """The whole point: an address's local name is keyed by the
        address itself, not whatever auth_user_name a cert (self-issued
        or otherwise) claims -- two different certs claiming the exact
        same username can't collide here, and this user's own label
        survives regardless of what the OTHER side calls themselves."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                user = User(pathlib.Path(d) / "users.json")
                cert = await user.issueCert(SITE_ADDRESS, "zeronet.local", "web", "alice")
                user.setLocalName(cert["auth_address"], "The real Alice, not the impostor")
                return user.getLocalName(cert["auth_address"]), user.getCertUserId(SITE_ADDRESS)

        local_name, cert_user_id = compat.run(scenario)
        assert local_name == "The real Alice, not the impostor"
        assert cert_user_id == "alice@zeronet.local"  # Unaffected -- the cert's own claim is untouched

    def testRemoveLocalNameClearsIt(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                user = User(pathlib.Path(d) / "users.json")
                user.setLocalName("1SomeAuthAddress", "Temp label")
                user.removeLocalName("1SomeAuthAddress")
                return user.getLocalName("1SomeAuthAddress"), user.listLocalNames()

        name, names = compat.run(scenario)
        assert name is None
        assert names == {}


class TestP2PUserManager:
    def testLoadWithNoUsersJsonLeavesEmpty(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                um = UserManager(pathlib.Path(d))
                await um.load()
                return um.users, um.loaded

        users, loaded = compat.run(scenario)
        assert users == {}
        assert loaded is True

    def testCreateThenGetReturnsSameUser(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                um = UserManager(pathlib.Path(d))
                created = um.create()
                fetched = await um.get()
                return created, fetched

        created, fetched = compat.run(scenario)
        assert created is fetched

    def testGetReturnsFirstUserRegardlessOfArgument(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                um = UserManager(pathlib.Path(d))
                first = um.create()
                um.create()  # second user, should never be returned by get()
                return first, await um.get("completely-different-address")

        first, fetched = compat.run(scenario)
        assert fetched is first

    def testLoadReadsPersistedUsers(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                um1 = UserManager(data_dir)
                user = um1.create()
                user.getSiteData(SITE_ADDRESS)
                await user.save()

                um2 = UserManager(data_dir)
                await um2.load()
                return user.master_address, um2.users

        master_address, users = compat.run(scenario)
        assert master_address in users
        assert users[master_address].sites[SITE_ADDRESS]["auth_address"]

    def testLoadCleansUpRemovedUsers(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                um = UserManager(data_dir)
                um.create()
                (data_dir / "users.json").write_text(json.dumps({}))
                await um.load()
                return um.users

        assert compat.run(scenario) == {}
