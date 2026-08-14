import pytest

from Crypt import CryptAes


class TestCryptAes:
    def testRoundtrip(self):
        key = CryptAes.newKey()
        assert len(key) == 32
        data = b"hello world" * 100
        ciphertext = CryptAes.encrypt(data, key)
        assert ciphertext != data
        assert CryptAes.decrypt(ciphertext, key) == data

    def testRoundtripString(self):
        key = CryptAes.newKey()
        data = "hello ünïcode"
        assert CryptAes.decrypt(CryptAes.encrypt(data, key), key).decode("utf8") == data

    def testWrongKey(self):
        key = CryptAes.newKey()
        other = CryptAes.newKey()
        ciphertext = CryptAes.encrypt(b"secret", key)
        # Wrong key yields either garbage plaintext or a padding error, never the original
        try:
            result = CryptAes.decrypt(ciphertext, other)
        except Exception:
            result = None
        assert result != b"secret"

    def testKeyLengthValidation(self):
        with pytest.raises(ValueError):
            CryptAes.encrypt(b"data", b"short")
        with pytest.raises(ValueError):
            CryptAes.decrypt(b"data", b"short")

    def testDecryptTooShort(self):
        with pytest.raises(CryptAes.DecryptError):
            CryptAes.decrypt(b"tooshort", CryptAes.newKey())
