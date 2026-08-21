import json
import pathlib
import tempfile

from Crypt import CryptBitcoin
from P2P.Site import Site
from P2P.protocols import gossip_update, update
from P2P import compat


async def _signedSite(site_root, address, privatekey):
    site = Site(address, site_root)
    await site.content_manager.sign(privatekey)
    return site


class TestP2PGossipUpdateValidator:
    """make_validator() is set as a gossipsub topic validator -- accept/
    reject only, must never write. It shares verifyContentJson() with
    update.py's unicast handler (via applyContentUpdate below), so these
    mirror TestP2PUpdate.py's own accept/reject cases for the RPC path."""

    def testAcceptsValidSignedContent(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as site_dir:
                site = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                body = json.dumps(site.content_manager.contents["content.json"]).encode("utf8")
                validator = gossip_update.make_validator(site)
                return validator(None, _fakeMessage(body))

        assert compat.run(scenario) is True

    def testAcceptsSameContentAlreadyHeld(self):
        """The benign "nothing changed" case (verifyContentJson() returns
        False, not an error) must still be accepted -- rejecting it would
        treat an honestly-stale re-gossip as spam, when it's just a
        message someone else in the mesh might not have seen yet."""
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as site_dir:
                site = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                # Same content the site already has loaded -- "modified" unchanged.
                body = json.dumps(site.content_manager.contents["content.json"]).encode("utf8")
                validator = gossip_update.make_validator(site)
                return validator(None, _fakeMessage(body))

        assert compat.run(scenario) is True

    def testRejectsTamperedSignature(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as site_dir:
                site = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                forged = dict(site.content_manager.contents["content.json"])
                forged["modified"] += 1000
                forged["title"] = "forged"
                # No re-sign -- signature no longer matches the tampered content.
                body = json.dumps(forged).encode("utf8")
                validator = gossip_update.make_validator(site)
                return validator(None, _fakeMessage(body))

        assert compat.run(scenario) is False

    def testRejectsInvalidJson(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as site_dir:
                site = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                validator = gossip_update.make_validator(site)
                return validator(None, _fakeMessage(b"not json"))

        assert compat.run(scenario) is False


class TestP2PApplyContentUpdate:
    """applyContentUpdate() is the shared verify+write+notify core both
    update.py's unicast handler and gossip_update.consume() call -- tested
    directly here so both transports are covered by one set of cases."""

    def testAppliesNewerValidContentAndNotifies(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        notified = []

        async def scenario():
            with tempfile.TemporaryDirectory() as site_a_dir, tempfile.TemporaryDirectory() as site_b_dir:
                site_a = await _signedSite(pathlib.Path(site_a_dir), address, privatekey)
                site_b = Site(address, pathlib.Path(site_b_dir))

                body = json.dumps(site_a.content_manager.contents["content.json"]).encode("utf8")
                applied = await update.applyContentUpdate(
                    site_b, "content.json", body, on_applied=lambda s, p: notified.append((s, p)),
                )
                on_disk = await site_b.storage.loadJson("content.json")
                return applied, on_disk, site_b.content_manager.contents.get("content.json")

        applied, on_disk, cached = compat.run(scenario)
        assert applied is True
        assert on_disk["address"] == address
        assert cached == on_disk
        assert len(notified) == 1

    def testReturnsFalseAndSkipsNotifyForSameContent(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        notified = []

        async def scenario():
            with tempfile.TemporaryDirectory() as site_dir:
                site = await _signedSite(pathlib.Path(site_dir), address, privatekey)
                body = json.dumps(site.content_manager.contents["content.json"]).encode("utf8")
                applied = await update.applyContentUpdate(
                    site, "content.json", body, on_applied=lambda s, p: notified.append((s, p)),
                )
                return applied

        assert compat.run(scenario) is False
        assert notified == []

    def testRaisesContentUpdateErrorForTamperedSignatureAndDoesNotWrite(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as site_a_dir, tempfile.TemporaryDirectory() as site_b_dir:
                site_a = await _signedSite(pathlib.Path(site_a_dir), address, privatekey)
                site_b = Site(address, pathlib.Path(site_b_dir))

                forged = dict(site_a.content_manager.contents["content.json"])
                forged["modified"] += 1000
                forged["title"] = "forged"
                body = json.dumps(forged).encode("utf8")

                raised = False
                try:
                    await update.applyContentUpdate(site_b, "content.json", body)
                except update.ContentUpdateError:
                    raised = True
                return raised, site_b.storage.isFile("content.json"), "content.json" in site_b.content_manager.contents

        raised, wrote_file, cached = compat.run(scenario)
        assert raised is True
        assert wrote_file is False
        assert cached is False

    def testRaisesContentUpdateErrorForInvalidJson(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as site_dir:
                site = Site(address, pathlib.Path(site_dir))
                raised = False
                try:
                    await update.applyContentUpdate(site, "content.json", b"not json")
                except update.ContentUpdateError:
                    raised = True
                return raised

        assert compat.run(scenario) is True


def _fakeMessage(data: bytes):
    class _Msg:
        pass
    msg = _Msg()
    msg.data = data
    return msg
