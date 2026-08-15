import copy
import io
import json
import pathlib
import tempfile
import time

import pytest

from Crypt import CryptBitcoin, CryptHash
from P2P.SiteStorage import SiteStorage
from P2P.ContentManager import ContentManager, VerifyError
from P2P import compat


def _make_signed_content(privatekey, signer_address, **overrides):
    content = {
        "modified": time.time(),
        "files": {},
    }
    content.update(overrides)
    sign_content = json.dumps(content, sort_keys=True)
    signature = CryptBitcoin.sign(sign_content, privatekey)
    signed = copy.deepcopy(content)
    signed["signs"] = {signer_address: signature}
    return signed


class TestP2PContentManager:
    def testLoadContentParsesAndCaches(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.writeJson("content.json", {"modified": 123, "files": {}})
                cm = ContentManager(storage, "1Test")
                loaded = await cm.loadContent()
                return loaded, cm.contents

        loaded, contents = compat.run(scenario)
        assert loaded == {"modified": 123, "files": {}}
        assert contents["content.json"] == {"modified": 123, "files": {}}

    def testGetFileInfoFindsRegularFile(self):
        cm = ContentManager(storage=None, site_address="1Test")
        cm.contents["content.json"] = {
            "files": {"data.json": {"sha512": "abc", "size": 10}},
        }
        info = cm.getFileInfo("data.json")
        assert info["sha512"] == "abc"
        assert info["optional"] is False
        assert info["content_inner_path"] == "content.json"

    def testGetFileInfoFindsOptionalFile(self):
        cm = ContentManager(storage=None, site_address="1Test")
        cm.contents["content.json"] = {
            "files_optional": {"big.bin": {"sha512": "def", "size": 999}},
        }
        info = cm.getFileInfo("big.bin")
        assert info["optional"] is True

    def testGetFileInfoNestedContentJson(self):
        cm = ContentManager(storage=None, site_address="1Test")
        cm.contents["users/content.json"] = {
            "files": {"data.json": {"sha512": "xyz", "size": 5}},
        }
        info = cm.getFileInfo("users/data.json")
        assert info["content_inner_path"] == "users/content.json"
        assert info["relative_path"] == "data.json"

    def testGetFileInfoNotFound(self):
        cm = ContentManager(storage=None, site_address="1Test")
        cm.contents["content.json"] = {"files": {}}
        assert cm.getFileInfo("missing.json") is False

    def testVerifyFileValidHashAndSize(self):
        cm = ContentManager(storage=None, site_address="1Test")
        content = b"hello world"
        cm.contents["content.json"] = {
            "files": {"data.txt": {"sha512": CryptHash.sha512sum(io.BytesIO(content)), "size": len(content)}},
        }
        # sha512sum() reads from the current position to EOF, and verifyFile
        # checks file.tell() *after* that read for the size -- so the file
        # object passed in starts at 0, not pre-seeked to the end.
        assert cm.verifyFile("data.txt", io.BytesIO(content)) is True

    def testVerifyFileWrongHashRaises(self):
        cm = ContentManager(storage=None, site_address="1Test")
        content = b"hello world"
        cm.contents["content.json"] = {
            "files": {"data.txt": {"sha512": "0" * 128, "size": len(content)}},
        }
        with pytest.raises(VerifyError, match="Invalid hash"):
            cm.verifyFile("data.txt", io.BytesIO(content))

    def testVerifyFileNotInContentJsonRaises(self):
        cm = ContentManager(storage=None, site_address="1Test")
        cm.contents["content.json"] = {"files": {}}
        with pytest.raises(VerifyError, match="not in content.json"):
            cm.verifyFile("nope.txt", io.BytesIO(b"x"))

    def testVerifyFileContentJsonItselfIsNotImplemented(self):
        cm = ContentManager(storage=None, site_address="1Test")
        with pytest.raises(NotImplementedError):
            cm.verifyFile("content.json", io.BytesIO(b"{}"))

    def testListModifiedFiltersAfterAndBefore(self):
        cm = ContentManager(storage=None, site_address="1Test")
        cm.contents = {
            "a/content.json": {"modified": 100},
            "b/content.json": {"modified": 200},
            "c/content.json": {"modified": 300},
        }
        assert cm.listModified(after=100) == {"b/content.json": 200, "c/content.json": 300}
        assert cm.listModified(before=300) == {"a/content.json": 100, "b/content.json": 200}
        assert cm.listModified(after=100, before=300) == {"b/content.json": 200}


class TestP2PContentManagerSignatures:
    """The security-critical path: real CryptBitcoin keys signing and
    verifying, not mocked -- this is the actual trust boundary a site's
    content.json update goes through."""

    def testValidSignatureAccepted(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)

        content = _make_signed_content(privatekey, address)
        assert cm.verifyContentJson(content) is True

    def testWrongAddressSignatureRejected(self):
        privatekey = CryptBitcoin.newPrivatekey()
        signer_address = CryptBitcoin.privatekeyToAddress(privatekey)
        # Site address is DIFFERENT from the key that signed it
        other_privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(other_privatekey)

        cm = ContentManager(storage=None, site_address=site_address)
        content = _make_signed_content(privatekey, signer_address)
        with pytest.raises(VerifyError, match="Valid signs"):
            cm.verifyContentJson(content)

    def testTamperedContentAfterSigningRejected(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)

        content = _make_signed_content(privatekey, address, files={"a.txt": {"size": 1}})
        # Attacker modifies the signed payload after the fact (e.g. adds a
        # bogus extra file) without re-signing.
        content["files"]["evil.txt"] = {"size": 999999}
        with pytest.raises(VerifyError, match="Valid signs"):
            cm.verifyContentJson(content)

    def testUnsignedContentRejected(self):
        cm = ContentManager(storage=None, site_address="1Test")
        with pytest.raises(VerifyError, match="Not signed"):
            cm.verifyContentJson({"modified": time.time(), "files": {}})

    def testOldStyleSignRejected(self):
        cm = ContentManager(storage=None, site_address="1Test")
        with pytest.raises(VerifyError, match="old-style"):
            cm.verifyContentJson({"modified": time.time(), "files": {}, "sign": "deadbeef"})

    def testWrongSiteAddressFieldRejected(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)

        content = _make_signed_content(privatekey, address, address="1SomeOtherAddress")
        with pytest.raises(VerifyError, match="Wrong site address"):
            cm.verifyContentJson(content)

    def testRollbackToOlderModifiedRejected(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)
        cm.contents["content.json"] = {"modified": 500}

        old_content = _make_signed_content(privatekey, address, modified=100)
        with pytest.raises(VerifyError, match="We have newer"):
            cm.verifyContentJson(old_content)

    def testSameModifiedReturnsFalseNotError(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)
        cm.contents["content.json"] = {"modified": 500}

        same_content = _make_signed_content(privatekey, address, modified=500)
        assert cm.verifyContentJson(same_content) is False

    def testFarFutureModifiedRejected(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)

        content = _make_signed_content(privatekey, address, modified=time.time() + 60 * 60 * 24 * 30)
        with pytest.raises(VerifyError, match="far future"):
            cm.verifyContentJson(content)

    def testInvalidRelativePathRejected(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)

        content = _make_signed_content(privatekey, address, files={"../../etc/passwd": {"size": 1}})
        with pytest.raises(VerifyError, match="Invalid relative path"):
            cm.verifyContentJson(content)

    def testSizeLimitEnforced(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        cm = ContentManager(storage=None, site_address=address)

        content = _make_signed_content(privatekey, address)
        with pytest.raises(VerifyError, match="too large"):
            cm.verifyContentJson(content, size_limit_bytes=10)

    def testExtraSignerRequiresValidSignersSign(self):
        # valid_signers for verification comes from the OLD, already-trusted
        # content.json -- not the new update's own claims -- otherwise a new
        # content.json could just self-authorize extra signers. So the
        # "we trust extra_address too" fact has to already be in cm.contents
        # before verifying an update signed by that extra signer.
        owner_privatekey = CryptBitcoin.newPrivatekey()
        owner_address = CryptBitcoin.privatekeyToAddress(owner_privatekey)
        extra_privatekey = CryptBitcoin.newPrivatekey()
        extra_address = CryptBitcoin.privatekeyToAddress(extra_privatekey)

        cm = ContentManager(storage=None, site_address=owner_address)
        cm.contents["content.json"] = {"modified": 1, "signers": [extra_address]}

        # Signed by the extra signer (valid per the old content's signers
        # list), but this update is missing signers_sign, which should be
        # required whenever valid_signers has more than one entry.
        content = _make_signed_content(extra_privatekey, extra_address, modified=time.time())
        with pytest.raises(VerifyError, match="Missing signers_sign"):
            cm.verifyContentJson(content)

    def testExtraSignerWithValidSignersSignAccepted(self):
        owner_privatekey = CryptBitcoin.newPrivatekey()
        owner_address = CryptBitcoin.privatekeyToAddress(owner_privatekey)
        extra_privatekey = CryptBitcoin.newPrivatekey()
        extra_address = CryptBitcoin.privatekeyToAddress(extra_privatekey)

        cm = ContentManager(storage=None, site_address=owner_address)
        cm.contents["content.json"] = {"modified": 1, "signers": [extra_address]}

        content = {"modified": time.time(), "files": {}}
        # signers_sign has to be set BEFORE computing the content's own
        # signature: only "sign"/"signs" get stripped before hashing, so
        # signers_sign itself is covered by (and must be present for) the
        # content signature -- matching the original's actual field order.
        # valid_signers = [extra_address] (from old content's "signers") + [owner_address] (always appended)
        signers_data = "1:%s,%s" % (extra_address, owner_address)
        content["signers_sign"] = CryptBitcoin.sign(signers_data, owner_privatekey)

        sign_content = json.dumps(content, sort_keys=True)
        content["signs"] = {extra_address: CryptBitcoin.sign(sign_content, extra_privatekey)}

        assert cm.verifyContentJson(content) is True

    def testNonRootPathRaisesNotImplemented(self):
        cm = ContentManager(storage=None, site_address="1Test")
        with pytest.raises(NotImplementedError):
            cm.getValidSigners("users/somebody/content.json")
