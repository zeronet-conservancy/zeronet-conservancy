import base64

from Crypt import CryptBitcoin
from util import Electrum


ACCESS_REQUEST_MESSAGE = "zeronet-conservancy private site access request for %s"


def getCurve():
    return CryptBitcoin.sslcurve


def privateToPublic(privatekey):
    """Return the compressed/uncompressed secp256k1 public key bytes for a WIF private key."""
    curve = CryptBitcoin.sslcurve
    return curve.private_to_public(curve.wif_to_private(privatekey.encode()))


def publicToAddress(publickey):
    """Return the Bitcoin address for a public key (bytes)."""
    return CryptBitcoin.sslcurve.public_to_address(publickey).decode()


def wrapKey(key, publickey):
    """Encrypt a content key for a recipient public key using ECIES."""
    return CryptBitcoin.sslcurve.encrypt(key, publickey)


def unwrapKey(wrapped, privatekey):
    """Decrypt a content key using the recipient's WIF private key."""
    curve = CryptBitcoin.sslcurve
    return curve.decrypt(wrapped, curve.wif_to_private(privatekey.encode()))


def recoverPublicKey(signature, message):
    """Recover a public key (bytes) from a base64 signature over a message."""
    return CryptBitcoin.sslcurve.recover(base64.b64decode(signature), message.encode(), hash=Electrum.dbl_format)


def signAccessRequest(site_address, privatekey):
    """Sign an access request for a private site, returning (message, base64 signature)."""
    message = ACCESS_REQUEST_MESSAGE % site_address
    return message, CryptBitcoin.sign(message, privatekey)
