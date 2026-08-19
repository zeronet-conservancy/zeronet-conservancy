import base64
import pathlib
import tempfile

from Crypt import CryptAes, CryptBitcoin, CryptEcies
from P2P.Site import Site
from P2P.User import User
from P2P import compat


def _recipient_access_request(site_address, users_json_path):
    """A real recipient User + the addRecipientKey()-ready (address,
    signature) pair for approving them on site_address."""
    user = User(users_json_path)
    auth_address = user.getAuthAddress(site_address)
    auth_privatekey = user.getAuthPrivatekey(site_address)
    _, signature = CryptEcies.signAccessRequest(site_address, auth_privatekey)
    return user, auth_address, signature


class TestP2PSitePrivate:
    def testOwnerUnlocksImmediatelyWithContentKey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                users_json_path = pathlib.Path(users_dir) / "users.json"
                recipient_user, recipient_address, signature = _recipient_access_request(address, users_json_path)

                site = Site(address, pathlib.Path(d))
                recipients = site.content_manager.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await site.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)

                owner_user = User(users_json_path)  # unused on the owner path, but getPrivatekey() needs one
                content_key_b64 = base64.b64encode(content_key).decode("ascii")
                unlocked = await site.getPrivatekey(owner_user, content_key_b64=content_key_b64)
                return unlocked, content_key, site.private_key

        unlocked, content_key, cached = compat.run(scenario)
        assert unlocked == content_key
        assert cached == content_key

    def testRecipientUnlocksViaAuthKey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                users_json_path = pathlib.Path(users_dir) / "users.json"
                recipient_user, recipient_address, signature = _recipient_access_request(address, users_json_path)

                site = Site(address, pathlib.Path(d))
                recipients = site.content_manager.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await site.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)

                # Fresh Site over the same storage -- simulates a
                # different process/node reading what's on disk, same as
                # TestP2PPrivateSiteContentManager.py's loadContent() tests.
                site2 = Site(address, pathlib.Path(d), allow_create=False)
                unlocked = await site2.getPrivatekey(recipient_user)
                return unlocked, content_key

        unlocked, content_key = compat.run(scenario)
        assert unlocked == content_key

    def testNonRecipientGetsNoAccess(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                users_json_path = pathlib.Path(users_dir) / "users.json"
                _, recipient_address, signature = _recipient_access_request(address, users_json_path)

                site = Site(address, pathlib.Path(d))
                recipients = site.content_manager.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await site.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)

                stranger = User(pathlib.Path(users_dir) / "stranger.json")
                site2 = Site(address, pathlib.Path(d), allow_create=False)
                return await site2.getPrivatekey(stranger)

        assert compat.run(scenario) is None

    def testRevocationRemovesAccessAfterResign(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                users_json_path = pathlib.Path(users_dir) / "users.json"
                recipient_user, recipient_address, signature = _recipient_access_request(address, users_json_path)

                site = Site(address, pathlib.Path(d))
                recipients = site.content_manager.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await site.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)

                site_before = Site(address, pathlib.Path(d), allow_create=False)
                before = await site_before.getPrivatekey(recipient_user)

                recipients_revoked = site.content_manager.removeRecipientKey(recipients, recipient_address)
                await site.content_manager.sign(privatekey, content_key=content_key, recipients=recipients_revoked)

                site_after = Site(address, pathlib.Path(d), allow_create=False)
                after = await site_after.getPrivatekey(recipient_user)
                return before, after

        before, after = compat.run(scenario)
        assert before is not None
        assert after is None

    def testLockPrivateForcesReUnlock(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                users_json_path = pathlib.Path(users_dir) / "users.json"
                recipient_user, recipient_address, signature = _recipient_access_request(address, users_json_path)

                site = Site(address, pathlib.Path(d))
                recipients = site.content_manager.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await site.content_manager.sign(privatekey, content_key=content_key, recipients=recipients)

                site2 = Site(address, pathlib.Path(d), allow_create=False)
                first = await site2.getPrivatekey(recipient_user)
                site2.lockPrivate()
                after_lock = site2.private_key
                second = await site2.getPrivatekey(recipient_user)
                return first, after_lock, second

        first, after_lock, second = compat.run(scenario)
        assert first is not None
        assert after_lock is None
        assert second == first  # re-unlocked the same key

    def testUnlockPrivateOnPublicSiteReturnsNone(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                site = Site(address, pathlib.Path(d))
                await site.content_manager.sign(privatekey)  # plain, public site

                user = User(pathlib.Path(users_dir) / "users.json")
                return await site.getPrivatekey(user)

        assert compat.run(scenario) is None

    def testUnlockPrivateOnUnsignedSiteReturnsNone(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as users_dir:
                site = Site("1TestUnsignedSiteAAAAAAAAAAA", pathlib.Path(d))
                user = User(pathlib.Path(users_dir) / "users.json")
                return await site.getPrivatekey(user)

        assert compat.run(scenario) is None
