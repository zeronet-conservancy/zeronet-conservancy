import json

import pytest

from Config import config
from Crypt import CryptAes
from Crypt import CryptBitcoin
from Crypt import CryptEcies
from Content.ContentManager import SignError
from util import helper


@pytest.mark.usefixtures("resetSettings")
class TestPrivateSite:
    privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"

    @pytest.fixture(autouse=True)
    def reset_private_state(self, site):
        site.settings.pop("private_key", None)
        site.settings.pop("private_recipients", None)
        site.content_manager.private = None
        yield
        # Don't leak private settings into other tests via the shared sites.json
        site.settings.pop("private_key", None)
        site.settings.pop("private_recipients", None)
        sites_path = config.private_dir / "sites.json"
        try:
            data = json.load(open(sites_path))
        except Exception:
            data = {}
        if site.address in data:
            data[site.address].pop("private_key", None)
            data[site.address].pop("private_recipients", None)
            if not data[site.address]:
                del data[site.address]
            helper.atomicWrite(sites_path, helper.jsonDumps(data).encode("utf8"))

    def testPrivateSiteFlow(self, site, user):
        auth_address = user.getAuthAddress(site.address)
        auth_privatekey = user.getAuthPrivatekey(site.address)
        assert not site.content_manager.isPrivate()

        # Recipient requests access
        message, signature = CryptEcies.signAccessRequest(site.address, auth_privatekey)

        # Wrong signature address should be rejected
        wrong_address = CryptBitcoin.privatekeyToAddress(CryptBitcoin.newPrivatekey())
        with pytest.raises(SignError):
            site.content_manager.addRecipient(wrong_address, signature)

        # Owner approves the recipient
        assert site.content_manager.addRecipient(auth_address, signature) is True
        assert auth_address in site.content_manager.getRecipients()

        # Owner signs -> site becomes private
        site.content_manager.sign("content.json", privatekey=self.privatekey)
        assert site.content_manager.isPrivate()

        # content.json on disk is the private envelope
        envelope = site.storage.loadJson("content.json")
        assert envelope.get("privatekey") is True
        assert "keys" in envelope and "body" in envelope

        # Owner can decrypt files (content key from local settings)
        assert site.getPrivatekey() is not None
        encrypted = site.storage.read("index.html", "rb")
        assert b"html" in CryptAes.decrypt(encrypted, site.getPrivatekey()).lower()

        # Reload content: envelope is unwrapped back into inner content
        site.content_manager.loadContent("content.json", force=True)
        assert "title" in site.content_manager.contents["content.json"]
        assert len(site.content_manager.contents["content.json"]["files"]) > 0

        # Recipient path: drop owner key, unlock using own auth key
        site.private_key = None
        del site.settings["private_key"]
        assert site.unlockPrivate() is True
        assert site.getPrivatekey() is not None

        # Non-approved user cannot unlock
        site.content_manager.removeRecipient(auth_address)
        site.content_manager.sign("content.json", privatekey=self.privatekey)
        site.private_key = None
        site.settings.pop("private_key", None)
        assert site.unlockPrivate() is False

    def testSignWithoutRecipientsStaysPublic(self, site):
        # No recipients -> normal public sign, no envelope
        site.content_manager.sign("content.json", privatekey=self.privatekey)
        assert not site.content_manager.isPrivate()
        content = site.storage.loadJson("content.json")
        assert "privatekey" not in content

    def testKeysSignTamperRejected(self, site, user):
        auth_address = user.getAuthAddress(site.address)
        auth_privatekey = user.getAuthPrivatekey(site.address)
        message, signature = CryptEcies.signAccessRequest(site.address, auth_privatekey)
        site.content_manager.addRecipient(auth_address, signature)
        site.content_manager.sign("content.json", privatekey=self.privatekey)

        # Drop owner key so we exercise the viewer path
        site.private_key = None
        site.settings.pop("private_key", None)

        # A tampered keys map (stripped signature) must be rejected
        envelope = site.storage.loadJson("content.json")
        del envelope["keys_sign"]
        site.storage.writeJson("content.json", envelope)
        assert site.unlockPrivate() is False
