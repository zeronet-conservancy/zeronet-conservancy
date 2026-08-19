"""ECIES key-wrap and access-request signing for private sites.

Thin wrapper around CryptBitcoin's own secp256k1 curve object
(lib.sslcrypto, already vendored and loaded by CryptBitcoin.py for
ECDSA sign/verify) -- no new crypto dependency. Re-added here because
private-site support (ContentManager.wrapContent/unwrapContent, see
that module) needs to ECIES-wrap a site's AES content key for each
approved recipient's public key, and recover a visitor's public key
from a signed access request.

recoverPublicKey() uses the same dbl_format (double-sha256) hash
CryptBitcoin.sign() signs with, since signAccessRequest() below signs
through CryptBitcoin.sign() -- recovery must use the identical hash or
it silently recovers the wrong public key.
"""
import base64

from util.Electrum import dbl_format
from Crypt import CryptBitcoin

sslcurve = CryptBitcoin.sslcurve

ACCESS_REQUEST_MESSAGE = "zeronet-conservancy private site access request for %s"


def privateToPublic(privatekey: str) -> bytes:
    return sslcurve.private_to_public(sslcurve.wif_to_private(privatekey.encode()))


def publicToAddress(publickey: bytes) -> str:
    return sslcurve.public_to_address(publickey).decode()


def wrapKey(key: bytes, publickey: bytes) -> bytes:
    """ECIES-encrypt key (e.g. a site's AES content key) so only the
    holder of publickey's matching privatekey can unwrapKey() it."""
    return sslcurve.encrypt(key, publickey)


def unwrapKey(wrapped: bytes, privatekey: str) -> bytes:
    return sslcurve.decrypt(wrapped, sslcurve.wif_to_private(privatekey.encode()))


def recoverPublicKey(signature: str, message: str) -> bytes:
    """Recover the public key that produced signature over message --
    signature must be base64, as returned by signAccessRequest()/
    CryptBitcoin.sign()."""
    return sslcurve.recover(base64.b64decode(signature), message.encode(), hash=dbl_format)


def signAccessRequest(site_address: str, privatekey: str) -> tuple[str, str]:
    """Sign a request for access to site_address's private content with
    privatekey (the requester's own auth privatekey). Returns
    (message, base64_signature); the caller relays both to the site
    owner, who verifies via recoverPublicKey()+publicToAddress() before
    calling ContentManager.addRecipientKey()."""
    message = ACCESS_REQUEST_MESSAGE % site_address
    return message, CryptBitcoin.sign(message, privatekey)
