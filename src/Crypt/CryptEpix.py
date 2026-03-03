import base64
import binascii
import bech32
import logging

from collections.abc import Container
from typing import Optional, Union

from util.Electrum import dbl_format

lib_verify_best = "sslcrypto"

from lib import sslcrypto
sslcurve_native = sslcrypto.ecc.get_curve("secp256k1")
sslcurve_fallback = sslcrypto.fallback.ecc.get_curve("secp256k1")
sslcurve = sslcurve_native

# Epix chain configuration
EPIX_PREFIX = "epix"
EPIX_PUBKEY_PREFIX = "epixpub"

def newPrivatekey():  # Return new private key
    return sslcurve.private_to_wif(sslcurve.new_private_key()).decode()


def newSeed():
    return binascii.hexlify(sslcurve.new_private_key()).decode()


def hdPrivatekey(seed, child):
    # Too large child id could cause problems
    # Convert hex seed string to binary
    if isinstance(seed, str):
        seed_bin = bytes.fromhex(seed)
    else:
        seed_bin = seed
    privatekey_bin = sslcurve.derive_child(seed_bin, child % 100000000)
    return sslcurve.private_to_wif(privatekey_bin).decode()


def privatekeyToAddress(privatekey):  # Return Epix address from private key
    try:
        if len(privatekey) == 64:
            privatekey_bin = bytes.fromhex(privatekey)
        else:
            privatekey_bin = sslcurve.wif_to_private(privatekey.encode())

        # Get public key from private key (uncompressed format)
        public_key = sslcurve.private_to_public(privatekey_bin)

        # Convert to Epix address using bech32 encoding
        return publicKeyToAddress(public_key)
    except Exception as e:  # Invalid privatekey
        logging.debug(f"privatekeyToAddress error: {type(e).__name__}")
        return False


def publicKeyToAddress(public_key):
    """Convert a public key to an Epix bech32 address using Ethereum-style generation"""
    try:
        # Use Keccak256 for Ethereum-compatible address generation
        from Crypto.Hash import keccak

        # Handle different public key formats
        if len(public_key) == 65 and public_key[0] == 0x04:
            # Uncompressed key with 0x04 prefix - remove prefix
            public_key_for_hash = public_key[1:]
        elif len(public_key) == 64:
            # Already in correct format (64 bytes: 32 x + 32 y)
            public_key_for_hash = public_key
        elif len(public_key) == 33 and public_key[0] in (0x02, 0x03):
            # Compressed key - decompress it to 64 bytes for Ethereum-style hashing
            public_key_for_hash = sslcurve.decompress_point(public_key)
            # decompress_point returns a tuple (x, y), convert to bytes
            if isinstance(public_key_for_hash, tuple):
                public_key_for_hash = public_key_for_hash[0] + public_key_for_hash[1]
        else:
            logging.debug(f"publicKeyToAddress: Invalid public key length: {len(public_key)}")
            return False

        # Apply Keccak256 hash to the 64-byte public key
        hash_obj = keccak.new(digest_bits=256)
        hash_obj.update(public_key_for_hash)
        full_hash = hash_obj.digest()

        # Take the last 20 bytes for Ethereum-style address
        address_bytes = full_hash[-20:]

        # Convert to bech32 format with 'epix' prefix
        converted = bech32.convertbits(address_bytes, 8, 5)
        if converted is None:
            logging.debug("publicKeyToAddress: bech32.convertbits returned None")
            return False

        address = bech32.bech32_encode(EPIX_PREFIX, converted)
        return address

    except ImportError as e:
        # pycryptodome is required for correct Ethereum-style address generation
        raise ImportError(
            "pycryptodome is required for Epix address generation. "
            "Install it with: pip install pycryptodome"
        ) from e
    except Exception as e:
        logging.debug(f"publicKeyToAddress error: {type(e).__name__}")
        return False


def sign(data: str, privatekey: str) -> str:
    """Sign data with privatekey, return base64 string signature"""
    # Handle different private key formats (same as privatekeyToAddress)
    try:
        if len(privatekey) == 64:
            privatekey_bin = bytes.fromhex(privatekey)
        else:
            privatekey_bin = sslcurve.wif_to_private(privatekey.encode())
    except Exception:
        return None  # Invalid privatekey format

    return base64.b64encode(sslcurve.sign(
        data.encode(),
        privatekey_bin,
        recoverable=True,
        hash=dbl_format
    )).decode()


def sign_keccak(data: str, privatekey: str) -> str:
    """Sign data with privatekey using keccak256 hash, return base64 string signature.

    Used for chain-compatible signatures where the verifier needs to recover
    the signer's address and check it on-chain.
    """
    try:
        if len(privatekey) == 64:
            privatekey_bin = bytes.fromhex(privatekey)
        else:
            privatekey_bin = sslcurve.wif_to_private(privatekey.encode())
    except Exception:
        return None

    return base64.b64encode(sslcurve.sign(
        data.encode(),
        privatekey_bin,
        recoverable=True,
        hash=keccak_format
    )).decode()


def get_sign_address_64(data: str, sign: str, lib_verify=None) -> Optional[str]:
    """Returns pubkey/address of signer if any"""
    if not lib_verify:
        lib_verify = lib_verify_best

    if not sign:
        return None

    try:
        publickey = sslcurve.recover(base64.b64decode(sign), data.encode(), hash=dbl_format)
        sign_address = publicKeyToAddress(publickey)
        return sign_address
    except Exception:
        return None


def get_sign_address_keccak(data: str, sign: str) -> Optional[str]:
    """Returns the epix bech32 address of the signer using keccak256 hash recovery."""
    if not sign:
        return None

    try:
        publickey = sslcurve.recover(base64.b64decode(sign), data.encode(), hash=keccak_format)
        sign_address = publicKeyToAddress(publickey)
        return sign_address
    except Exception:
        return None


def keccak_format(data):
    """Hash data with keccak256 for Ethereum-compatible signature verification"""
    from Crypto.Hash import keccak
    hash_obj = keccak.new(digest_bits=256)
    hash_obj.update(data)
    return hash_obj.digest()


def verify_keccak(data: str, addresses: Union[str, Container[str]], sign: str) -> bool:
    """Verify signature using keccak256 hash (for chain/ethsecp256k1 signatures)"""
    if not sign:
        return False
    try:
        publickey = sslcurve.recover(base64.b64decode(sign), data.encode(), hash=keccak_format)
        sign_address = publicKeyToAddress(publickey)
    except Exception:
        return False

    if isinstance(addresses, str):
        return sign_address == addresses
    else:
        return sign_address in addresses


def verify(*args, **kwargs):
    """Default verify, see verify64"""
    return verify64(*args, **kwargs)


def verify64(data: str, addresses: Union[str, Container[str]], sign: str, lib_verify=None) -> bool:
    """Verify that sign is a valid signature for data by one of addresses

    Expecting signature to be in base64
    """
    sign_address = get_sign_address_64(data, sign, lib_verify)

    if isinstance(addresses, str):
        return sign_address == addresses
    else:
        return sign_address in addresses


def isValidAddress(addr):
    """Check if provided address is valid Epix bech32 address"""
    try:
        if not addr.startswith(EPIX_PREFIX):
            return False
        
        # Decode bech32 address
        hrp, data = bech32.bech32_decode(addr)
        if hrp != EPIX_PREFIX or data is None:
            return False
            
        # Convert back to check validity
        converted = bech32.convertbits(data, 5, 8, False)
        if converted is None or len(converted) != 20:
            return False
            
        return True
    except Exception:
        return False


def addressToHash160(addr):
    """Convert Epix bech32 address to hash160"""
    try:
        if not isValidAddress(addr):
            return None
            
        hrp, data = bech32.bech32_decode(addr)
        if hrp != EPIX_PREFIX or data is None:
            return None
            
        converted = bech32.convertbits(data, 5, 8, False)
        if converted is None or len(converted) != 20:
            return None
            
        return bytes(converted)
    except Exception:
        return None


def hash160ToAddress(hash160_bytes):
    """Convert hash160 bytes to Epix bech32 address"""
    try:
        if len(hash160_bytes) != 20:
            return None
            
        converted = bech32.convertbits(hash160_bytes, 8, 5)
        if converted is None:
            return None
            
        address = bech32.bech32_encode(EPIX_PREFIX, converted)
        return address
    except Exception:
        return None
