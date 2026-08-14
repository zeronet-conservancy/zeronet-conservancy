import pytest

from Crypt import CryptBitcoin
from Crypt import CryptAes
from Crypt import CryptEcies


class TestCryptEcies:
    privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"

    def testPrivateToPublic(self):
        publickey = CryptEcies.privateToPublic(self.privatekey)
        assert CryptEcies.publicToAddress(publickey) == CryptBitcoin.privatekeyToAddress(self.privatekey)

    def testWrapUnwrap(self):
        content_key = CryptAes.newKey()
        publickey = CryptEcies.privateToPublic(self.privatekey)
        wrapped = CryptEcies.wrapKey(content_key, publickey)
        assert CryptEcies.unwrapKey(wrapped, self.privatekey) == content_key

    def testWrapUnwrapWrongKey(self):
        content_key = CryptAes.newKey()
        publickey = CryptEcies.privateToPublic(self.privatekey)
        wrapped = CryptEcies.wrapKey(content_key, publickey)
        other_privatekey = CryptBitcoin.newPrivatekey()
        with pytest.raises(Exception):
            CryptEcies.unwrapKey(wrapped, other_privatekey)

    def testRecoverPublicKey(self):
        message = "hello world"
        signature = CryptBitcoin.sign(message, self.privatekey)
        publickey = CryptEcies.recoverPublicKey(signature, message)
        assert CryptEcies.publicToAddress(publickey) == CryptBitcoin.privatekeyToAddress(self.privatekey)

    def testAccessRequest(self):
        message, signature = CryptEcies.signAccessRequest("1TeSTvb4w2PWE81S2rEELgmX2GCCExQGT", self.privatekey)
        assert message == CryptEcies.ACCESS_REQUEST_MESSAGE % "1TeSTvb4w2PWE81S2rEELgmX2GCCExQGT"
        publickey = CryptEcies.recoverPublicKey(signature, message)
        assert CryptEcies.publicToAddress(publickey) == CryptBitcoin.privatekeyToAddress(self.privatekey)
