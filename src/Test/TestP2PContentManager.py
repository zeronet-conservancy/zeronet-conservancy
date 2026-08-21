import copy
import io
import json
import pathlib
import tempfile
import time

import pytest

from Crypt import CryptBitcoin, CryptHash
from P2P.SiteStorage import SiteStorage
from P2P.ContentManager import ContentManager, VerifyError, SignError
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

    def testNonRootPathWithNoLoadedParentFallsBackToSiteAddress(self):
        # No "users/content.json" (or any other covering content.json) has
        # been loaded, so getRules() can't find any rules for this path --
        # matches the original's own behavior here (it doesn't raise; the
        # site address is always a valid signer regardless).
        cm = ContentManager(storage=None, site_address="1Test")
        assert cm.getValidSigners("users/somebody/content.json") == ["1Test"]


class TestP2PContentManagerIncludes:
    """The "includes" half of the non-root cert-signer chain -- a
    subdirectory content.json whose valid signers are just an explicit
    list in the parent's "includes" entry, no cert involved."""

    def testIncludesRuleAllowsListedSigner(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        cm = ContentManager(storage=None, site_address="1Site")
        cm.contents["content.json"] = {"includes": {"sub/content.json": {"signers": [address]}}}

        content = {"modified": time.time(), "files": {}}
        sign_content = json.dumps(content, sort_keys=True)
        content["signs"] = {address: CryptBitcoin.sign(sign_content, privatekey)}

        assert cm.verifyContentJson(content, inner_path="sub/content.json") is True

    def testIncludesRuleRejectsUnlistedSigner(self):
        allowed_privatekey = CryptBitcoin.newPrivatekey()
        allowed_address = CryptBitcoin.privatekeyToAddress(allowed_privatekey)
        outsider_privatekey = CryptBitcoin.newPrivatekey()
        outsider_address = CryptBitcoin.privatekeyToAddress(outsider_privatekey)

        cm = ContentManager(storage=None, site_address="1Site")
        cm.contents["content.json"] = {"includes": {"sub/content.json": {"signers": [allowed_address]}}}

        content = {"modified": time.time(), "files": {}}
        sign_content = json.dumps(content, sort_keys=True)
        content["signs"] = {outsider_address: CryptBitcoin.sign(sign_content, outsider_privatekey)}

        with pytest.raises(VerifyError, match="Valid signs"):
            cm.verifyContentJson(content, inner_path="sub/content.json")

    def testIncludesMaxSizeEnforced(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        cm = ContentManager(storage=None, site_address="1Site")
        cm.contents["content.json"] = {"includes": {"sub/content.json": {"signers": [address], "max_size": 10}}}

        content = {"modified": time.time(), "files": {}, "title": "this pushes the dumped content past 10 bytes"}
        sign_content = json.dumps(content, sort_keys=True)
        content["signs"] = {address: CryptBitcoin.sign(sign_content, privatekey)}

        with pytest.raises(VerifyError, match="Include too large"):
            cm.verifyContentJson(content, inner_path="sub/content.json")


class TestP2PContentManagerCertChain:
    """The "user_contents" half -- write access to a per-user subdirectory
    gated by a certificate the user got from a domain-specific issuer,
    matching ZeroNet's ZeroID-style multi-user sites."""

    def _cert(self, user_address, auth_type, name, issuer_privatekey):
        cert_subject = "%s#%s/%s" % (user_address, auth_type, name)
        return CryptBitcoin.sign(cert_subject, issuer_privatekey)

    def _userContent(self, user_address, user_privatekey, cert_sign, auth_type="web", cert_user_id="alice@example.bit"):
        content = {
            "modified": time.time(),
            "files": {},
            "cert_auth_type": auth_type,
            "cert_user_id": cert_user_id,
            "cert_sign": cert_sign,
        }
        sign_content = json.dumps(content, sort_keys=True)
        content["signs"] = {user_address: CryptBitcoin.sign(sign_content, user_privatekey)}
        return content

    def testUserContentAcceptedWithValidCert(self):
        issuer_privatekey = CryptBitcoin.newPrivatekey()
        issuer_address = CryptBitcoin.privatekeyToAddress(issuer_privatekey)
        user_privatekey = CryptBitcoin.newPrivatekey()
        user_address = CryptBitcoin.privatekeyToAddress(user_privatekey)

        cm = ContentManager(storage=None, site_address="1Site")
        cm.contents["data/users/content.json"] = {
            "user_contents": {"permissions": {}, "cert_signers": {"example.bit": issuer_address}}
        }

        cert_sign = self._cert(user_address, "web", "alice", issuer_privatekey)
        content = self._userContent(user_address, user_privatekey, cert_sign)
        inner_path = "data/users/%s/content.json" % user_address

        assert cm.verifyContentJson(content, inner_path=inner_path) is True

    def testUserContentRejectedWithCertSignedByWrongIssuer(self):
        issuer_privatekey = CryptBitcoin.newPrivatekey()
        issuer_address = CryptBitcoin.privatekeyToAddress(issuer_privatekey)
        impostor_privatekey = CryptBitcoin.newPrivatekey()  # Not the registered issuer
        user_privatekey = CryptBitcoin.newPrivatekey()
        user_address = CryptBitcoin.privatekeyToAddress(user_privatekey)

        cm = ContentManager(storage=None, site_address="1Site")
        cm.contents["data/users/content.json"] = {
            "user_contents": {"permissions": {}, "cert_signers": {"example.bit": issuer_address}}
        }

        cert_sign = self._cert(user_address, "web", "alice", impostor_privatekey)
        content = self._userContent(user_address, user_privatekey, cert_sign)
        inner_path = "data/users/%s/content.json" % user_address

        with pytest.raises(VerifyError, match="Invalid cert"):
            cm.verifyContentJson(content, inner_path=inner_path)

    def testUserContentRejectedForUnknownCertDomain(self):
        issuer_privatekey = CryptBitcoin.newPrivatekey()
        user_privatekey = CryptBitcoin.newPrivatekey()
        user_address = CryptBitcoin.privatekeyToAddress(user_privatekey)

        cm = ContentManager(storage=None, site_address="1Site")
        cm.contents["data/users/content.json"] = {
            "user_contents": {"permissions": {}, "cert_signers": {"other-domain.bit": "1SomeIssuer"}}
        }

        cert_sign = self._cert(user_address, "web", "alice", issuer_privatekey)
        content = self._userContent(user_address, user_privatekey, cert_sign, cert_user_id="alice@example.bit")
        inner_path = "data/users/%s/content.json" % user_address

        with pytest.raises(VerifyError, match="Invalid cert"):
            cm.verifyContentJson(content, inner_path=inner_path)

    def testPermissionRulePatternSkippedForCompromisedCertUnlessLax(self):
        issuer_privatekey = CryptBitcoin.newPrivatekey()
        issuer_address = CryptBitcoin.privatekeyToAddress(issuer_privatekey)
        user_address = "1SomeUserAddress"

        parent_content = {
            "user_contents": {
                "permissions": {},
                "cert_signers": {"example.bit": issuer_address},
                "permission_rules": {".*": {"max_size": 999}},
            }
        }
        # The mechanism for reporting a compromised issuer: proving you hold
        # (or found leaked) the issuer's own privatekey by signing the
        # literal string "compromised" with it -- get_sign_address_64()
        # recovers the issuer's address back out of that signature.
        bad_sign = CryptBitcoin.sign("compromised", issuer_privatekey)
        cert_content = {"cert_auth_type": "web", "cert_user_id": "alice@example.bit"}
        inner_path = "data/users/%s/content.json" % user_address

        cm_strict = ContentManager(storage=None, site_address="1Site")  # lax_cert_check=False default
        cm_strict.addBadCert(bad_sign)
        rules_strict = cm_strict.getUserContentRules(parent_content, inner_path, cert_content)
        assert "max_size" not in rules_strict

        cm_lax = ContentManager(storage=None, site_address="1Site", lax_cert_check=True)
        cm_lax.addBadCert(bad_sign)
        rules_lax = cm_lax.getUserContentRules(parent_content, inner_path, cert_content)
        assert rules_lax["max_size"] == 999

    def testGetUserContentRulesRequiresContent(self):
        cm = ContentManager(storage=None, site_address="1Site")
        parent_content = {"user_contents": {"permissions": {}}}
        with pytest.raises(ValueError):
            cm.getUserContentRules(parent_content, "data/users/1Someone/content.json", None)


class TestP2PContentManagerSign:
    def testSignCreatesVerifiableContentJson(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("index.html", b"<h1>hello</h1>")
                cm = ContentManager(storage, address)

                new_content = await cm.sign(privatekey)
                on_disk = await storage.loadJson("content.json")
                return new_content, on_disk, cm

        new_content, on_disk, cm = compat.run(scenario)
        assert on_disk == new_content
        assert "index.html" in new_content["files"]
        assert new_content["files"]["index.html"]["size"] == len(b"<h1>hello</h1>")
        assert new_content["address"] == cm.site_address
        # Fresh ContentManager, re-verifying what got written -- proves
        # sign() and verifyContentJson() actually agree with each other.
        cm2 = ContentManager(storage=None, site_address=cm.site_address)
        assert cm2.verifyContentJson(new_content) is True

    def testSignSkipsContentJsonDotfilesAndBackups(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("real.txt", b"keep me")
                await storage.write(".hidden", b"skip me")
                await storage.write("data.txt-old", b"skip me too")
                cm = ContentManager(storage, address)
                return await cm.sign(privatekey)

        new_content = compat.run(scenario)
        assert set(new_content["files"].keys()) == {"real.txt"}

    def testSignWithWrongPrivatekeyRaisesSignError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                owner_privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(owner_privatekey)
                wrong_privatekey = CryptBitcoin.newPrivatekey()
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, address)
                try:
                    await cm.sign(wrong_privatekey)
                    return "no-error"
                except SignError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testSignExtendMergesNewFieldsWithoutOverwritingExisting(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, address)
                first = await cm.sign(privatekey, extend={"description": "original"})
                second = await cm.sign(privatekey, extend={"description": "ignored", "postmessage_nonce_security": True})
                return first, second

        first, second = compat.run(scenario)
        assert first["description"] == "original"
        # extend() only fills in missing keys -- an existing value survives re-signing
        assert second["description"] == "original"
        assert second["postmessage_nonce_security"] is True

    def testSignIgnoresStrayPrivateRecipientsField(self):
        """private-site status is driven by sign()'s own content_key/
        recipients params now (see TestP2PPrivateSiteContentManager.py
        for the real private-site coverage) -- a leftover
        "private_recipients" key sitting in an on-disk content.json from
        somewhere else doesn't make plain sign() (no recipients passed)
        refuse or do anything special with it; it's just an ordinary
        extra field that rides along."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                storage = SiteStorage(pathlib.Path(d))
                await storage.writeJson("content.json", {"files": {}, "signs": {}, "private_recipients": ["someone"]})
                cm = ContentManager(storage, address)
                await cm.loadContent()
                return await cm.sign(privatekey)

        new_content = compat.run(scenario)
        assert "privatekey" not in new_content
        assert new_content.get("private_recipients") == ["someone"]

    def testSignWithFilewriteFalseDoesNotTouchDisk(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                privatekey = CryptBitcoin.newPrivatekey()
                address = CryptBitcoin.privatekeyToAddress(privatekey)
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, address)
                new_content = await cm.sign(privatekey, filewrite=False)
                return new_content, storage.isFile("content.json"), "content.json" in cm.contents

        new_content, file_exists, in_contents = compat.run(scenario)
        assert new_content["signs"]
        assert file_exists is False
        assert in_contents is False


class TestP2PContentManagerSignUserContent:
    """signUserContent()'s own docstring explains why these round-trip
    through the real verify side rather than just asserting on the
    signed dict's shape: there's no legacy implementation left in this
    repo to translate from, so agreement with verifyContentJson()/
    verifyCert()/getUserContentRules() (already covered by
    TestP2PContentManagerCertChain above) IS the spec."""

    async def _setup(self, d):
        site_privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(site_privatekey)
        issuer_privatekey = CryptBitcoin.newPrivatekey()
        issuer_address = CryptBitcoin.privatekeyToAddress(issuer_privatekey)
        user_privatekey = CryptBitcoin.newPrivatekey()
        user_address = CryptBitcoin.privatekeyToAddress(user_privatekey)

        storage = SiteStorage(pathlib.Path(d))
        cm = ContentManager(storage, site_address)
        cm.contents["data/users/content.json"] = {
            "inner_path": "data/users/content.json",
            "user_contents": {"permissions": {}, "cert_signers": {"example.bit": issuer_address}},
        }
        cert_sign = CryptBitcoin.sign("%s#web/alice" % user_address, issuer_privatekey)
        inner_path = "data/users/%s/content.json" % user_address
        return cm, storage, inner_path, user_privatekey, user_address, cert_sign, issuer_privatekey

    def testSignUserContentRoundTripsThroughVerify(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                cm, storage, inner_path, user_privatekey, user_address, cert_sign, _ = await self._setup(d)
                await storage.write("data/users/%s/message.txt" % user_address, b"hello world")

                new_content = await cm.signUserContent(
                    inner_path, user_privatekey, "web", "alice@example.bit", cert_sign,
                )
                on_disk = await storage.loadJson(inner_path)
                return new_content, on_disk, cm, inner_path

        new_content, on_disk, cm, inner_path = compat.run(scenario)
        assert on_disk == new_content
        assert "message.txt" in new_content["files"]
        assert new_content["cert_user_id"] == "alice@example.bit"
        # Fresh ContentManager, re-verifying from scratch (only the parent
        # policy pre-loaded, same precondition as any other getRules()
        # caller) -- proves signUserContent() and verifyContentJson()
        # actually agree with each other, not just with themselves.
        cm2 = ContentManager(storage=None, site_address=cm.site_address)
        cm2.contents["data/users/content.json"] = cm.contents["data/users/content.json"]
        assert cm2.verifyContentJson(new_content, inner_path=inner_path) is True

    def testSignUserContentDoesNotLeakSiblingUsersFiles(self):
        """hashFiles()'s base_path scoping -- a user's own content.json
        must only ever list files inside their own directory, never a
        different user's, even though both live under the same parent
        data/users/ tree."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                cm, storage, inner_path, user_privatekey, user_address, cert_sign, _ = await self._setup(d)
                await storage.write("data/users/%s/message.txt" % user_address, b"mine")
                await storage.write("data/users/1SomeoneElseEntirely/message.txt", b"not mine")

                return await cm.signUserContent(inner_path, user_privatekey, "web", "alice@example.bit", cert_sign)

        new_content = compat.run(scenario)
        assert set(new_content["files"].keys()) == {"message.txt"}

    def testSignUserContentWithWrongPrivatekeyRaisesSignError(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                cm, storage, inner_path, _user_privatekey, _user_address, cert_sign, _ = await self._setup(d)
                wrong_privatekey = CryptBitcoin.newPrivatekey()  # Not this directory's own address
                try:
                    await cm.signUserContent(inner_path, wrong_privatekey, "web", "alice@example.bit", cert_sign)
                    return "no-error"
                except SignError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testSignUserContentWithUntrustedCertRaisesVerifyError(self):
        """A cert signed by an address the parent's cert_signers policy
        doesn't name for that domain must fail self-verification and
        never reach disk -- signUserContent() must not silently publish
        something every peer would then reject."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                cm, storage, inner_path, user_privatekey, user_address, _cert_sign, _issuer_privatekey = await self._setup(d)
                impostor_privatekey = CryptBitcoin.newPrivatekey()
                bad_cert_sign = CryptBitcoin.sign("%s#web/alice" % user_address, impostor_privatekey)
                try:
                    await cm.signUserContent(inner_path, user_privatekey, "web", "alice@example.bit", bad_cert_sign)
                    return "no-error", storage.isFile(inner_path)
                except VerifyError:
                    return "raised", storage.isFile(inner_path)

        result, file_exists = compat.run(scenario)
        assert result == "raised"
        assert file_exists is False
