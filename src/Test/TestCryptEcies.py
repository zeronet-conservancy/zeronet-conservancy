from Crypt import CryptBitcoin, CryptAes, CryptEcies


class TestCryptEcies:
    def testWrapUnwrapKeyRoundtrip(self):
        privatekey = CryptBitcoin.newPrivatekey()
        publickey = CryptEcies.privateToPublic(privatekey)
        content_key = CryptAes.newKey()

        wrapped = CryptEcies.wrapKey(content_key, publickey)
        assert wrapped != content_key
        assert CryptEcies.unwrapKey(wrapped, privatekey) == content_key

    def testUnwrapWithWrongPrivatekeyFails(self):
        privatekey = CryptBitcoin.newPrivatekey()
        other_privatekey = CryptBitcoin.newPrivatekey()
        publickey = CryptEcies.privateToPublic(privatekey)
        content_key = CryptAes.newKey()

        wrapped = CryptEcies.wrapKey(content_key, publickey)
        try:
            result = CryptEcies.unwrapKey(wrapped, other_privatekey)
        except Exception:
            result = None
        assert result != content_key

    def testPublicToAddressMatchesPrivatekeyToAddress(self):
        privatekey = CryptBitcoin.newPrivatekey()
        publickey = CryptEcies.privateToPublic(privatekey)
        assert CryptEcies.publicToAddress(publickey) == CryptBitcoin.privatekeyToAddress(privatekey)

    def testSignAccessRequestAndRecoverPublicKey(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        site_address = "1TestSiteAddressAAAAAAAAAAAA"

        message, signature = CryptEcies.signAccessRequest(site_address, privatekey)
        assert message == CryptEcies.ACCESS_REQUEST_MESSAGE % site_address

        recovered_publickey = CryptEcies.recoverPublicKey(signature, message)
        assert CryptEcies.publicToAddress(recovered_publickey) == address

    def testRecoverPublicKeyRejectsWrongMessage(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        site_address = "1TestSiteAddressAAAAAAAAAAAA"

        message, signature = CryptEcies.signAccessRequest(site_address, privatekey)
        recovered_publickey = CryptEcies.recoverPublicKey(signature, message + "tampered")
        assert CryptEcies.publicToAddress(recovered_publickey) != address

    def testEndToEndAccessRequestToWrappedKey(self):
        """The full recipient-approval flow: a visitor signs an access
        request, the site owner recovers+verifies their public key from
        it, then wraps the site's content key for that recipient -- and
        only the recipient's own privatekey can unwrap it back."""
        recipient_privatekey = CryptBitcoin.newPrivatekey()
        recipient_address = CryptBitcoin.privatekeyToAddress(recipient_privatekey)
        site_address = "1TestSiteAddressAAAAAAAAAAAA"
        content_key = CryptAes.newKey()

        message, signature = CryptEcies.signAccessRequest(site_address, recipient_privatekey)

        recovered_publickey = CryptEcies.recoverPublicKey(signature, message)
        assert CryptEcies.publicToAddress(recovered_publickey) == recipient_address

        wrapped = CryptEcies.wrapKey(content_key, recovered_publickey)
        assert CryptEcies.unwrapKey(wrapped, recipient_privatekey) == content_key
