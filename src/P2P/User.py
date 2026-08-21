"""Trio port of User/User.py -- the BIP32 identity/auth-key/certificate
store behind a site's per-user write access (the same account model
P2P/ContentManager.py's cert-signer chain verifies against on the read
side).

Persistence to private_dir/users.json is passed in explicitly (a Path)
rather than read off a global Config object, matching this whole
package's convention (P2P.SiteManager takes data_dir/private_dir the same
way) instead of depending on process-wide config state.

saveDelayed()'s debounce is NOT ported as a self-scheduling timer: the
original's gevent.spawn_later(5, self.save) fires a background greenlet
from anywhere, no nursery required -- trio has no equivalent (every task
needs an enclosing nursery). Rather than thread a nursery parameter
through every mutator (generateAuthAddress/deleteSiteData/
setSiteSettings/setCert), those now just call markDirty() -- a plain flag
-- and it's the caller's job to persist, either immediately (await
user.save()) or via saveDelayed(nursery) if it already has a nursery
handy (e.g. the app's own long-lived one). getNewSiteData() and addCert()
keep the original's synchronous-save behavior (await self.save()
directly) since both need to confirm the write actually succeeded before
returning key material to the caller.

save() is guarded by a trio.Lock rather than the original's
util.Noparallel(queue=True) decorator -- same intent (concurrent save()
calls don't race and clobber each other's read-modify-write of the
shared users.json), simpler mechanism for a single serialized critical
section.

@acceptPlugins (Phase 8) marks this as pluggable, same treatment as
P2P.SiteManager/P2P.SiteAnnouncer -- e.g. a CryptMessage-equivalent
plugin's registerTo("User") extension (getEncryptPrivatekey/
getEncryptPublickey) could attach here. Safe, no-op change on its own:
see PluginManager.py's own docstring for the ordering requirement.
"""
import json
import logging
import os
import time

import trio

from Crypt import CryptBitcoin

from .PluginManager import acceptPlugins


def _atomicWriteJson(path, data) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(tmp_path, path)


@acceptPlugins
class User:
    def __init__(self, users_json_path, master_address: str | None = None, master_seed: str | None = None, data: dict | None = None):
        data = data or {}
        if master_seed:
            self.master_seed = master_seed
            self.master_address = CryptBitcoin.privatekeyToAddress(self.master_seed)
        elif master_address:
            self.master_address = master_address
            self.master_seed = data.get("master_seed")
        else:
            self.master_seed = CryptBitcoin.newSeed()
            self.master_address = CryptBitcoin.privatekeyToAddress(self.master_seed)

        self.users_json_path = users_json_path
        self.sites: dict = data.get("sites", {})
        self.certs: dict = data.get("certs", {})
        self.settings: dict = data.get("settings", {})
        self.local_names: dict = data.get("local_names", {})
        self._dirty = False
        self._save_lock = trio.Lock()

        self.log = logging.getLogger("User:%s" % self.master_address)

    def markDirty(self) -> None:
        self._dirty = True

    async def save(self) -> None:
        async with self._save_lock:
            def _readModifyWrite():
                try:
                    with self.users_json_path.open() as f:
                        users = json.load(f)
                except FileNotFoundError:
                    users = {}
                user_data = users.setdefault(self.master_address, {})
                if self.master_seed:
                    user_data["master_seed"] = self.master_seed
                user_data["sites"] = self.sites
                user_data["certs"] = self.certs
                user_data["settings"] = self.settings
                user_data["local_names"] = self.local_names
                _atomicWriteJson(self.users_json_path, users)

            s = time.time()
            await trio.to_thread.run_sync(_readModifyWrite)
            self._dirty = False
            self.log.debug("Saved in %.3fs", time.time() - s)

    def saveDelayed(self, nursery) -> None:
        """Schedules a save ~5s from now in the given nursery, unless one's
        already pending -- see module docstring for why a nursery has to
        be supplied explicitly."""
        if self._dirty:
            return
        self.markDirty()
        nursery.start_soon(self._delayedSave)

    async def _delayedSave(self) -> None:
        await trio.sleep(5)
        if self._dirty:
            await self.save()

    def getAddressAuthIndex(self, address: str) -> int:
        return int(address.encode().hex(), 16)

    def generateAuthAddress(self, address: str) -> dict:
        s = time.time()
        address_id = self.getAddressAuthIndex(address)
        auth_privatekey = CryptBitcoin.hdPrivatekey(self.master_seed, address_id)
        self.sites[address] = {
            "auth_address": CryptBitcoin.privatekeyToAddress(auth_privatekey),
            "auth_privatekey": auth_privatekey,
        }
        self.markDirty()
        self.log.debug("Added new site: %s in %.3fs", address, time.time() - s)
        return self.sites[address]

    def getSiteData(self, address: str, create: bool = True) -> dict:
        if address not in self.sites:
            if not create:
                return {"auth_address": None, "auth_privatekey": None}
            self.generateAuthAddress(address)
        return self.sites[address]

    def deleteSiteData(self, address: str) -> None:
        if address in self.sites:
            del self.sites[address]
            self.markDirty()
            self.log.debug("Deleted site: %s", address)

    def setSiteSettings(self, address: str, settings: dict) -> dict:
        site_data = self.getSiteData(address)
        site_data["settings"] = settings
        self.markDirty()
        return site_data

    async def getNewSiteData(self):
        import random
        bip32_index = random.randrange(2 ** 256) % 100000000
        site_privatekey = CryptBitcoin.hdPrivatekey(self.master_seed, bip32_index)
        site_address = CryptBitcoin.privatekeyToAddress(site_privatekey)
        if site_address in self.sites:
            raise Exception("Random error: site exist!")
        self.getSiteData(site_address)
        self.sites[site_address]["privatekey"] = site_privatekey
        await self.save()
        return site_address, bip32_index, self.sites[site_address]

    def getAuthAddress(self, address: str, create: bool = True):
        cert = self.getCert(address)
        if cert:
            return cert["auth_address"]
        return self.getSiteData(address, create)["auth_address"]

    def getAuthPrivatekey(self, address: str, create: bool = True):
        cert = self.getCert(address)
        if cert:
            return cert["auth_privatekey"]
        return self.getSiteData(address, create)["auth_privatekey"]

    async def addCert(self, auth_address: str, domain: str, auth_type: str, auth_user_name: str, cert_sign: str):
        matches = [site["auth_privatekey"] for site in self.sites.values() if site["auth_address"] == auth_address]
        if not matches:
            raise ValueError("No site uses auth_address %s" % auth_address)
        auth_privatekey = matches[0]
        cert_node = {
            "auth_address": auth_address,
            "auth_privatekey": auth_privatekey,
            "auth_type": auth_type,
            "auth_user_name": auth_user_name,
            "cert_sign": cert_sign,
        }
        if self.certs.get(domain) and self.certs[domain] != cert_node:
            return False
        elif self.certs.get(domain) == cert_node:
            return None
        else:
            self.certs[domain] = cert_node
            await self.save()
            return True

    async def issueCert(self, address: str, domain: str, auth_type: str, auth_user_name: str) -> dict:
        """Issue and install a certificate signed by this local identity.

        A separate provider key is persisted in user settings. Sites must
        still explicitly trust ``provider_address`` in their cert_signers rules;
        this method only creates a valid ZeroNet certificate and does not
        broaden any site's trust policy.
        """
        auth_address = self.getAuthAddress(address)
        cert = await self.issueCertForAuth(auth_address, domain, auth_type, auth_user_name)
        result = await self.addCert(auth_address, domain, auth_type, auth_user_name, cert["cert_sign"])
        if result is False:
            raise ValueError("Certificate already exists with different data for %s" % domain)
        self.setCert(address, domain)
        await self.save()
        return cert

    async def issueCertForAuth(self, auth_address: str, domain: str, auth_type: str, auth_user_name: str) -> dict:
        """Sign a certificate for a requester without importing its private key."""
        provider_privatekey = self.settings.get("local_provider_privatekey")
        provider_address = self.settings.get("local_provider_address")
        if not provider_privatekey or not provider_address:
            provider_privatekey = CryptBitcoin.newPrivatekey()
            provider_address = CryptBitcoin.privatekeyToAddress(provider_privatekey)
            self.settings["local_provider_privatekey"] = provider_privatekey
            self.settings["local_provider_address"] = provider_address
            self.markDirty()

        cert_subject = "%s#%s/%s" % (auth_address, auth_type, auth_user_name)
        cert_sign = CryptBitcoin.sign(cert_subject, provider_privatekey)
        await self.save()
        return {
            "auth_address": auth_address,
            "auth_type": auth_type,
            "auth_user_name": auth_user_name,
            "cert_sign": cert_sign,
            "domain": domain,
            "provider_address": provider_address,
        }

    def deleteCert(self, domain: str) -> None:
        del self.certs[domain]

    def setCert(self, address: str, domain: str | None) -> dict:
        site_data = self.getSiteData(address)
        if domain:
            site_data["cert"] = domain
        else:
            site_data.pop("cert", None)
        self.markDirty()
        return site_data

    def getCert(self, address: str):
        site_data = self.getSiteData(address, create=False)
        if not site_data or "cert" not in site_data:
            return None
        return self.certs.get(site_data["cert"])

    def getCertUserId(self, address: str):
        site_data = self.getSiteData(address, create=False)
        if not site_data or "cert" not in site_data:
            return None
        cert = self.certs.get(site_data["cert"])
        if cert:
            return "%s@%s" % (cert["auth_user_name"], site_data["cert"])
        return None

    def getCertFields(self, address: str):
        """Bundle the three fields a non-root content.json needs to embed
        for verifyCert() -- cert_auth_type/cert_user_id/cert_sign -- for
        whatever cert is currently selected for address. None if no cert
        is selected (the "use local identity" case has no cert at all).
        De-duplicates the assembly Ui/commands.py's fileRules originally
        inlined; ContentManager.signUserContent()'s caller needs the same
        three fields."""
        cert = self.getCert(address)
        if not cert:
            return None
        return {
            "cert_auth_type": cert["auth_type"],
            "cert_user_id": self.getCertUserId(address),
            "cert_sign": cert["cert_sign"],
        }

    def setLocalName(self, auth_address: str, name: str) -> None:
        """A purely local override: this user's own name for auth_address,
        independent of whatever auth_user_name/cert_user_id that identity
        claims for itself. Never published, never synced -- the whole
        point is that it can't be spoofed by someone else picking a
        colliding username (see certIssueLocal's own docstring on why
        self-issued usernames aren't globally unique at all), because
        it's keyed by the one thing that IS unique: the address itself."""
        self.local_names[auth_address] = name
        self.markDirty()

    def getLocalName(self, auth_address: str):
        return self.local_names.get(auth_address)

    def removeLocalName(self, auth_address: str) -> None:
        if auth_address in self.local_names:
            del self.local_names[auth_address]
            self.markDirty()

    def listLocalNames(self) -> dict:
        return dict(self.local_names)
