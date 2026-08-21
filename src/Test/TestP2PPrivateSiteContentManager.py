import base64
import json
import pathlib
import tempfile

from Crypt import CryptAes, CryptBitcoin, CryptEcies
from P2P.SiteStorage import SiteStorage
from P2P.ContentManager import ContentManager, PrivateKeyError, SignError, VerifyError
from P2P import compat


def _recipient(site_address):
    """A recipient's own privatekey + the addRecipientKey()-ready
    (address, signature) pair for approving them on a site."""
    privatekey = CryptBitcoin.newPrivatekey()
    message, signature = CryptEcies.signAccessRequest(site_address, privatekey)
    address = CryptBitcoin.privatekeyToAddress(privatekey)
    return privatekey, address, signature


class TestP2PPrivateSiteContentManagerWrap:
    def testWrapUnwrapRoundtrip(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        recipient_privatekey, recipient_address, signature = _recipient(address)

        cm = ContentManager(storage=None, site_address=address)
        recipients = cm.addRecipientKey({}, recipient_address, signature)

        content_key = CryptAes.newKey()
        content = {"address": address, "modified": 123, "files": {}}
        envelope = cm.wrapContent(content, content_key, privatekey, recipients)

        assert envelope["privatekey"] is True
        assert recipient_address in envelope["keys"]
        assert "keys_sign" in envelope
        assert "body" in envelope

        decrypted = cm.unwrapContent(envelope, content_key)
        assert decrypted == content

    def testUnwrapWithoutKeyRaisesPrivateKeyError(self):
        cm = ContentManager(storage=None, site_address="1Test")
        envelope = {"privatekey": True, "keys": {}, "keys_sign": "x", "body": "eA=="}
        try:
            cm.unwrapContent(envelope, None)
            result = "no-error"
        except PrivateKeyError:
            result = "raised"
        assert result == "raised"

    def testAddRecipientKeyRejectsWrongAddress(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        _, real_address, signature = _recipient(address)
        wrong_address = CryptBitcoin.privatekeyToAddress(CryptBitcoin.newPrivatekey())
        assert wrong_address != real_address

        cm = ContentManager(storage=None, site_address=address)
        try:
            cm.addRecipientKey({}, wrong_address, signature)
            result = "no-error"
        except SignError:
            result = "raised"
        assert result == "raised"

    def testAddAndRemoveRecipientKeyDoNotMutateInput(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        _, recipient_address, signature = _recipient(address)

        cm = ContentManager(storage=None, site_address=address)
        original = {}
        updated = cm.addRecipientKey(original, recipient_address, signature)
        assert original == {}  # input untouched
        assert recipient_address in updated

        removed = cm.removeRecipientKey(updated, recipient_address)
        assert recipient_address in updated  # input untouched
        assert recipient_address not in removed

    def testWrapContentUsesRawStoredPubkeyNotDoubleWrapped(self):
        """recipients values are raw (b64-encoded) pubkeys as produced by
        addRecipientKey() -- wrapContent() must decode+wrap them fresh
        each time, not treat them as already-wrapped."""
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        recipient_privatekey, recipient_address, signature = _recipient(address)

        cm = ContentManager(storage=None, site_address=address)
        recipients = cm.addRecipientKey({}, recipient_address, signature)
        stored_pubkey = base64.b64decode(recipients[recipient_address])
        assert stored_pubkey == CryptEcies.privateToPublic(recipient_privatekey)


class TestP2PPrivateSiteContentManagerVerify:
    def testVerifyContentJsonAcceptsValidEnvelope(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        _, recipient_address, signature = _recipient(address)

        cm = ContentManager(storage=None, site_address=address)
        recipients = cm.addRecipientKey({}, recipient_address, signature)
        content_key = CryptAes.newKey()
        envelope = cm.wrapContent({"modified": 1, "files": {}}, content_key, privatekey, recipients)

        assert cm.verifyContentJson(envelope) is True

    def testVerifyContentJsonRejectsTamperedKeysSign(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        _, recipient_address, signature = _recipient(address)

        cm = ContentManager(storage=None, site_address=address)
        recipients = cm.addRecipientKey({}, recipient_address, signature)
        content_key = CryptAes.newKey()
        envelope = cm.wrapContent({"modified": 1, "files": {}}, content_key, privatekey, recipients)
        envelope["keys_sign"] = "tampered" + envelope["keys_sign"]

        try:
            cm.verifyContentJson(envelope)
            result = "no-error"
        except VerifyError:
            result = "raised"
        assert result == "raised"

    def testVerifyContentJsonRejectsTamperedKeysMap(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        _, recipient_address, signature = _recipient(address)

        cm = ContentManager(storage=None, site_address=address)
        recipients = cm.addRecipientKey({}, recipient_address, signature)
        content_key = CryptAes.newKey()
        envelope = cm.wrapContent({"modified": 1, "files": {}}, content_key, privatekey, recipients)
        # An attacker adds themselves to the key map without a valid keys_sign
        forged_address = CryptBitcoin.privatekeyToAddress(CryptBitcoin.newPrivatekey())
        envelope["keys"][forged_address] = envelope["keys"][recipient_address]

        try:
            cm.verifyContentJson(envelope)
            result = "no-error"
        except VerifyError:
            result = "raised"
        assert result == "raised"

    def testVerifyContentJsonRejectsMissingKeysSign(self):
        cm = ContentManager(storage=None, site_address="1Test")
        try:
            cm.verifyContentJson({"privatekey": True, "keys": {}, "body": "eA=="})
            result = "no-error"
        except VerifyError:
            result = "raised"
        assert result == "raised"


class TestP2PPrivateSiteContentManagerSign:
    def testSignWithRecipientsProducesEnvelopeOnDiskButPlaintextCache(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                _, recipient_address, signature = _recipient(address)

                storage = SiteStorage(pathlib.Path(d))
                await storage.write("index.html", b"<h1>secret</h1>")
                cm = ContentManager(storage, address)
                recipients = cm.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()

                new_content = await cm.sign(privatekey, content_key=content_key, recipients=recipients)
                on_disk = await storage.loadJson("content.json")
                encrypted_file = await storage.read("index.html")
                return new_content, on_disk, cm.contents["content.json"], encrypted_file, content_key

        new_content, on_disk, cached, encrypted_file, content_key = compat.run(scenario)
        # On disk: an envelope, not the plaintext content.
        assert on_disk["privatekey"] is True
        assert "keys" in on_disk and "body" in on_disk
        assert "files" not in on_disk
        # Returned value + in-memory cache: plaintext, per sign()'s own contract.
        assert cached == new_content
        # The recorded hash/size is of the CIPHERTEXT (what's actually on
        # disk / what a peer downloads), not the plaintext -- encryptFiles()
        # runs before hashFiles() on the first transition to private, same
        # ordering the original design used, so verifyFile() on the
        # receiving end checks against the bytes that were really sent.
        assert new_content["files"]["index.html"]["size"] == len(encrypted_file)
        assert new_content["files"]["index.html"]["size"] != len(b"<h1>secret</h1>")

    def testVerifyFileAcceptsCiphertextAtRest(self):
        """Regression test for a real ordering bug caught while building
        this: encryptFiles() must run BEFORE hashFiles() on the first
        transition to private, not after -- otherwise content.json
        records the plaintext's hash/size while the bytes actually on
        disk (and sent to downloaders) are the ciphertext, and every
        download would fail verifyFile()'s hash check. This exercises
        the real downloader-side check, not just the recorded metadata."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                _, recipient_address, signature = _recipient(address)

                storage = SiteStorage(pathlib.Path(d))
                await storage.write("index.html", b"<h1>secret</h1>" * 50)  # >1 AES block
                cm = ContentManager(storage, address)
                recipients = cm.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await cm.sign(privatekey, content_key=content_key, recipients=recipients)

                import io
                encrypted_file = await storage.read("index.html")
                return cm.verifyFile("index.html", io.BytesIO(encrypted_file))

        assert compat.run(scenario) is True

    def testResigningAlreadyPrivateSiteDoesNotDoubleEncrypt(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                _, recipient_address, signature = _recipient(address)

                storage = SiteStorage(pathlib.Path(d))
                await storage.write("index.html", b"<h1>secret</h1>")
                cm = ContentManager(storage, address)
                recipients = cm.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await cm.sign(privatekey, content_key=content_key, recipients=recipients)
                once_encrypted = await storage.read("index.html")

                # Re-sign the same already-private site (self.contents
                # already holds the plaintext cache from the first sign).
                await cm.sign(privatekey, content_key=content_key, recipients=recipients)
                twice_signed = await storage.read("index.html")
                return once_encrypted, twice_signed, content_key

        once_encrypted, twice_signed, content_key = compat.run(scenario)
        assert once_encrypted == twice_signed  # not re-encrypted on top of itself
        assert CryptAes.decrypt(twice_signed, content_key) == b"<h1>secret</h1>"

    def testSignWithoutRecipientsStaysPublic(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, address)
                new_content = await cm.sign(privatekey)
                on_disk = await storage.loadJson("content.json")
                return new_content, on_disk

        new_content, on_disk = compat.run(scenario)
        assert "privatekey" not in new_content
        assert on_disk == new_content

    def testSignWithRecipientsButNoContentKeyRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                _, recipient_address, signature = _recipient(address)
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, address)
                recipients = cm.addRecipientKey({}, recipient_address, signature)
                try:
                    await cm.sign(privatekey, recipients=recipients)
                    return "no-error"
                except SignError:
                    return "raised"

        assert compat.run(scenario) == "raised"


class TestP2PPrivateSiteContentManagerLoadContent:
    def testLoadContentDecryptsWithKey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                _, recipient_address, signature = _recipient(address)
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, address)
                recipients = cm.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await cm.sign(privatekey, content_key=content_key, recipients=recipients)

                # Fresh ContentManager over the same storage -- simulates
                # a different process/node loading what's on disk.
                cm2 = ContentManager(storage, address)
                without_key = await cm2.loadContent(content_key=None)
                with_key = await cm2.loadContent(content_key=content_key)
                return without_key, with_key

        without_key, with_key = compat.run(scenario)
        assert without_key.get("privatekey") is True  # cached the envelope, unusable
        assert "files" in with_key  # cached the decrypted plaintext

    def testLoadContentIgnoresWrongKeyFallsBackToEnvelope(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                _, recipient_address, signature = _recipient(address)
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, address)
                recipients = cm.addRecipientKey({}, recipient_address, signature)
                content_key = CryptAes.newKey()
                await cm.sign(privatekey, content_key=content_key, recipients=recipients)

                cm2 = ContentManager(storage, address)
                wrong_key = CryptAes.newKey()
                return await cm2.loadContent(content_key=wrong_key)

        loaded = compat.run(scenario)
        assert loaded.get("privatekey") is True  # decrypt failed, fell back to the envelope


class TestP2PPrivateSiteContentManagerEncryptFiles:
    def testEncryptFilesSkipsContentJsonDotfilesAndBackups(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.writeJson("content.json", {"files": {}})
                await storage.write("real.txt", b"secret data")
                await storage.write(".hidden", b"skip me")
                await storage.write("data.txt-old", b"skip me too")
                cm = ContentManager(storage, "1Test")

                content_key = CryptAes.newKey()
                await cm.encryptFiles(content_key)

                content_json_bytes = await storage.read("content.json")
                real_bytes = await storage.read("real.txt")
                hidden_bytes = await storage.read(".hidden")
                backup_bytes = await storage.read("data.txt-old")
                return content_json_bytes, real_bytes, hidden_bytes, backup_bytes, content_key

        content_json_bytes, real_bytes, hidden_bytes, backup_bytes, content_key = compat.run(scenario)
        assert json.loads(content_json_bytes) == {"files": {}}  # untouched, still plain JSON
        assert real_bytes != b"secret data"
        assert CryptAes.decrypt(real_bytes, content_key) == b"secret data"
        assert hidden_bytes == b"skip me"
        assert backup_bytes == b"skip me too"
