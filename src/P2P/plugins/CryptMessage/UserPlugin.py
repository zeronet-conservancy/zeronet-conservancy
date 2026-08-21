"""Trio port of plugins/CryptMessage/CryptMessagePlugin.py's own
registerTo("User") extension -- getEncryptPrivatekey()/
getEncryptPublickey(), the per-site ECIES keypair derivation this
package's own commands.py needed before it could port eciesEncrypt/
eciesDecrypt/userPublickey (see that module's own docstring on why they
were held back). P2P.User was marked @acceptPlugins specifically for
this to attach to -- see that class's own module docstring.

Pure bip32 derivation over data P2P.User already has everywhere else it
derives a per-site key (getAddressAuthIndex(), master_seed,
CryptBitcoin.hdPrivatekey()) -- no new infrastructure, same "narrow but
real" shape as Sidebar's own privatekey-recovery commands. The one new
primitive is the actual EC point derivation (private_to_public), which
comes from src/lib/sslcrypto -- already vendored in this repo (zero
gevent dependency, pure Python/OpenSSL bindings) and already imported by
this package's own commands.py for aesEncrypt/eccPrivToPub/etc.

Caching matches the original exactly: the derived key is written straight
into user.getSiteData(address) (the same per-site dict privatekey/
auth_address/cert already live in) so repeated calls for the same
address/param_index/cert don't re-derive, and markDirty() is called so
the caller's own save() (same "caller decides when to persist" contract
every other P2P.User mutator uses) actually writes it out."""
import base64

from lib import sslcrypto

from Crypt import CryptBitcoin
from P2P.PluginManager import registerTo

curve = sslcrypto.ecc.get_curve("secp256k1")


@registerTo("User")
class UserPlugin:
    def getEncryptPrivatekey(self, address: str, param_index: int = 0) -> str:
        if param_index < 0 or param_index > 1000:
            raise ValueError("param_index out of range")

        site_data = self.getSiteData(address)
        if site_data.get("cert"):
            index = param_index + self.getAddressAuthIndex(site_data["cert"])
        else:
            index = param_index

        key = "encrypt_privatekey_%s" % index
        if key not in site_data:
            address_index = self.getAddressAuthIndex(address)
            crypt_index = address_index + 1000 + index
            site_data[key] = CryptBitcoin.hdPrivatekey(self.master_seed, crypt_index)
            self.markDirty()
        return site_data[key]

    def getEncryptPublickey(self, address: str, param_index: int = 0) -> str:
        if param_index < 0 or param_index > 1000:
            raise ValueError("param_index out of range")

        site_data = self.getSiteData(address)
        if site_data.get("cert"):
            index = param_index + self.getAddressAuthIndex(site_data["cert"])
        else:
            index = param_index

        key = "encrypt_publickey_%s" % index
        if key not in site_data:
            privatekey = self.getEncryptPrivatekey(address, param_index).encode()
            publickey = curve.private_to_public(curve.wif_to_private(privatekey) + b"\x01")
            site_data[key] = base64.b64encode(publickey).decode("utf8")
            self.markDirty()
        return site_data[key]
