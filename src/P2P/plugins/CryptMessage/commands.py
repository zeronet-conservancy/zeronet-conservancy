"""Trio port of a real slice of plugins/CryptMessage/CryptMessagePlugin.py
-- the first plugin ported that ADDS new websocket commands rather than
overriding existing ones (P2P/plugins/Zeroname overrides SiteManager
methods; this one calls @command() directly, same as core commands in
P2P/Ui/commands.py itself). That works with zero extra plumbing: unlike
@acceptPlugins's class-decoration ordering requirement (a plugin must
import before the target class does), P2P.Ui.commands.COMMAND_HANDLERS is
a plain module-level dict mutated at decoration time and read fresh on
every dispatch (UiApp._handleCommand() does `COMMAND_HANDLERS.get(cmd)`,
not a cached snapshot) -- so a plugin registering a new command just
needs to have been imported at some point before that command is called,
not before any particular class is defined.

Ported: aesEncrypt, aesDecrypt, ecdsaSign, ecdsaVerify, eccPrivToPub,
eccPubToAddr -- self-contained crypto operations with no further
dependencies. ecdsaSign optionally falls back to the connected site's own
stored auth privatekey (via session.app.user_manager), matching the
original's own "sign using user's privatekey" default.

userPublickey/eciesEncrypt/eciesDecrypt are ported now too, using the new
User.getEncryptPrivatekey()/getEncryptPublickey() extension this
package's own UserPlugin.py adds (registerTo("User"), landing alongside
this file). Reuses sslcrypto's own curve.encrypt()/curve.decrypt()
directly (the same ECIES primitives plugins/CryptMessage/CryptMessage.py's
own eciesEncrypt/eciesDecrypt wrap, no separate module needed for two
short calls) rather than adding a parallel helper module.

eciesDecrypt here only supports the original's single-item calling
convention (one ciphertext, not the batch list-of-ciphertexts form
eciesDecryptMulti provides) -- same simplification aesDecrypt below
already makes, for the identical reason: real callers of a headless
command handler can call this once per candidate ciphertext themselves.

aesDecrypt here only supports the original's single-item calling
convention (iv/encrypted/key, not the batch iv-encrypted-pairs/keys-list
form) -- the batch form exists in the original for one specific
performance case (try decrypting one payload against several candidate
keys); real callers of a headless command handler can just call this
once per candidate key themselves.
"""
from lib import sslcrypto

# Absolute, not relative -- loadPlugins() imports this plugin as a bare
# top-level module (e.g. "CryptMessage"), not a proper submodule of
# P2P.plugins, since it works by sys.path.append(path_plugins) +
# __import__(dir_name). See P2P/plugins/Zeroname/SiteManagerPlugin.py's
# own comment on the same point.
from P2P.Ui.commands import command

curve = sslcrypto.ecc.get_curve("secp256k1")


def _param(params, key, default=None):
    if isinstance(params, dict):
        return params.get(key, default)
    return default


@command("aesEncrypt")
async def _cmdAesEncrypt(session, params):
    import base64

    text = _param(params, "text")
    key_b64 = _param(params, "key")
    key = base64.b64decode(key_b64) if key_b64 else sslcrypto.aes.new_key()

    if text:
        encrypted, iv = sslcrypto.aes.encrypt(text.encode("utf8"), key)
    else:
        encrypted, iv = b"", b""

    return [base64.b64encode(item).decode("utf8") for item in (key, iv, encrypted)]


@command("aesDecrypt")
async def _cmdAesDecrypt(session, params):
    import base64

    iv = base64.b64decode(_param(params, "iv"))
    encrypted = base64.b64decode(_param(params, "encrypted"))
    key = base64.b64decode(_param(params, "key"))

    try:
        decrypted = sslcrypto.aes.decrypt(encrypted, iv, key)
        return decrypted.decode("utf8")
    except Exception:
        return None


@command("ecdsaSign")
async def _cmdEcdsaSign(session, params):
    from Crypt import CryptBitcoin

    data = _param(params, "data")
    privatekey = _param(params, "privatekey")
    if not privatekey:
        site = session.site
        user_manager = getattr(session.app, "user_manager", None)
        if site is None or user_manager is None:
            raise ValueError("No privatekey given and no site/user available to derive one")
        user = await user_manager.get()
        if user is None:
            raise ValueError("No privatekey given and no user available to derive one")
        privatekey = user.getAuthPrivatekey(site.address)

    return CryptBitcoin.sign(data, privatekey)


@command("ecdsaVerify")
async def _cmdEcdsaVerify(session, params):
    from Crypt import CryptBitcoin

    data = _param(params, "data")
    address = _param(params, "address")
    signature = _param(params, "signature")
    return CryptBitcoin.verify(data, address, signature)


@command("eccPrivToPub")
async def _cmdEccPrivToPub(session, params):
    """Returns hex, not the original's raw bytes -- a websocket response
    gets json.dumps()'d, and bytes aren't JSON-serializable regardless of
    transport; hex is the adaptation, not a data change."""
    privatekey = _param(params, "privatekey")
    pub = curve.private_to_public(curve.wif_to_private(privatekey.encode()))
    return pub.hex()


@command("eccPubToAddr")
async def _cmdEccPubToAddr(session, params):
    publickey = _param(params, "publickey")
    addr = curve.public_to_address(bytes.fromhex(publickey))
    return addr.decode("ascii")


@command("userPublickey")
async def _cmdUserPublickey(session, params):
    """Returns the connected user's per-site ECIES publickey -- unique to
    this site (and, if a cert is selected, to that cert's own auth
    identity), matching the original's own "publickey unique to site"
    docstring."""
    from P2P.Ui.commands import _requireSite, _requireUser

    site = _requireSite(session)
    user = await _requireUser(session)
    index = _param(params, "index", 0)
    return user.getEncryptPublickey(site.address, index)


@command("eciesEncrypt")
async def _cmdEciesEncrypt(session, params):
    import base64

    from P2P.Ui.commands import _requireSite, _requireUser

    text = _param(params, "text")
    publickey = _param(params, "publickey", 0)
    return_aes_key = bool(_param(params, "return_aes_key", False))

    if isinstance(publickey, int):  # Encrypt using the connected user's own per-site publickey
        site = _requireSite(session)
        user = await _requireUser(session)
        publickey = user.getEncryptPublickey(site.address, publickey)

    encrypted, aes_key = curve.encrypt(
        text.encode("utf8"), base64.b64decode(publickey), algo="aes-256-cbc", derivation="sha512", return_aes_key=True,
    )
    if return_aes_key:
        return [base64.b64encode(encrypted).decode("utf8"), base64.b64encode(aes_key).decode("utf8")]
    return base64.b64encode(encrypted).decode("utf8")


@command("eciesDecrypt")
async def _cmdEciesDecrypt(session, params):
    import base64

    from P2P.Ui.commands import _requireSite, _requireUser

    encrypted_b64 = _param(params, "param")
    privatekey = _param(params, "privatekey", 0)

    if isinstance(privatekey, int):  # Decrypt using the connected user's own per-site privatekey
        site = _requireSite(session)
        user = await _requireUser(session)
        privatekey = user.getEncryptPrivatekey(site.address, privatekey)

    try:
        decrypted = curve.decrypt(
            base64.b64decode(encrypted_b64), curve.wif_to_private(privatekey.encode()), derivation="sha512",
        )
        return decrypted.decode("utf8")
    except Exception:
        return None
