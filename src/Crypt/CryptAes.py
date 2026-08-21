import os

import pyaes


IV_LENGTH = 16
KEY_LENGTH = 32


class DecryptError(Exception):
    pass


def newKey():
    """Generate a random 256-bit content key."""
    return os.urandom(KEY_LENGTH)


def encrypt(data, key):
    """AES-256-CBC encrypt. Returns iv + ciphertext. Key must be 32 bytes."""
    if isinstance(data, str):
        data = data.encode("utf8")
    if len(key) != KEY_LENGTH:
        raise ValueError("Expected key to be %s bytes, got %s" % (KEY_LENGTH, len(key)))
    iv = os.urandom(IV_LENGTH)
    cipher = pyaes.AESModeOfOperationCBC(key, iv=iv)
    encrypter = pyaes.Encrypter(cipher)
    ciphertext = encrypter.feed(data)
    ciphertext += encrypter.feed()
    return iv + ciphertext


def decrypt(data, key):
    """AES-256-CBC decrypt. Expects iv + ciphertext. Key must be 32 bytes."""
    if len(key) != KEY_LENGTH:
        raise ValueError("Expected key to be %s bytes, got %s" % (KEY_LENGTH, len(key)))
    if len(data) < IV_LENGTH:
        raise DecryptError("Ciphertext too short")
    iv = data[:IV_LENGTH]
    ciphertext = data[IV_LENGTH:]
    cipher = pyaes.AESModeOfOperationCBC(key, iv=iv)
    decrypter = pyaes.Decrypter(cipher)
    plaintext = decrypter.feed(ciphertext)
    plaintext += decrypter.feed()
    return plaintext
