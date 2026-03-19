import logging
import json
import time
import binascii

import gevent

import util
from Crypt import CryptEpix
from Plugin import PluginManager
from Config import config
from util import helper
from Debug import Debug


@PluginManager.acceptPlugins
class User(object):
    def __init__(self, master_address=None, master_seed=None, data={}):
        if master_seed:
            self.master_seed = master_seed
            self.master_address = CryptEpix.privatekeyToAddress(self.master_seed)
            if not self.master_address or self.master_address is False:
                raise Exception("Failed to generate valid master address from seed")
        elif master_address:
            self.master_address = master_address
            self.master_seed = data.get("master_seed")
        else:
            self.master_seed = CryptEpix.newSeed()
            self.master_address = CryptEpix.privatekeyToAddress(self.master_seed)
            if not self.master_address or self.master_address is False:
                raise Exception("Failed to generate valid master address from new seed")
        self.sites = data.get("sites", {})
        self.certs = data.get("certs", {})
        self.settings = data.get("settings", {})
        self.delayed_save_thread = None

        self.log = logging.getLogger("User:%s" % self.master_address)

    # Save to data/users.json
    @util.Noparallel(queue=True, ignore_class=True)
    def save(self):
        users_json = config.private_dir / 'users.json'
        s = time.time()
        users = json.load(open(users_json))
        if self.master_address not in users:
            users[self.master_address] = {}  # Create if not exist
        user_data = users[self.master_address]
        if self.master_seed:
            user_data["master_seed"] = self.master_seed
        user_data["sites"] = self.sites
        user_data["certs"] = self.certs
        user_data["settings"] = self.settings
        helper.atomicWrite(users_json, helper.jsonDumps(users).encode("utf8"))
        self.log.debug("Saved in %.3fs" % (time.time() - s))
        self.delayed_save_thread = None

    def saveDelayed(self):
        if not self.delayed_save_thread:
            self.delayed_save_thread = gevent.spawn_later(5, self.save)

    def getAddressAuthIndex(self, address):
        if not isinstance(address, str):
            raise TypeError(f"Address must be a string, got {type(address).__name__}: {address}")
        return int(binascii.hexlify(address.encode()), 16)

    @util.Noparallel()
    def generateAuthAddress(self, address):
        s = time.time()
        address_id = self.getAddressAuthIndex(address)  # Convert site address to int
        auth_privatekey = CryptEpix.hdPrivatekey(self.master_seed, address_id)
        auth_address = CryptEpix.privatekeyToAddress(auth_privatekey)
        if not auth_address or auth_address is False:
            raise Exception(f"Failed to generate valid auth address for site {address}")
        self.sites[address] = {
            "auth_address": auth_address,
            "auth_privatekey": auth_privatekey
        }
        self.saveDelayed()
        self.log.debug("Added new site: %s in %.3fs" % (address, time.time() - s))
        return self.sites[address]

    # Get user site data
    # Return: {"auth_address": "xxx", "auth_privatekey": "xxx"}
    def getSiteData(self, address, create=True):
        if address not in self.sites:  # Generate new BIP32 child key based on site address
            if not create:
                return {"auth_address": None, "auth_privatekey": None}  # Dont create user yet
            self.generateAuthAddress(address)
            # Auto-activate global cert on new site (portable cert)
            active_cert = self.getActiveCertDomain()
            if active_cert:
                self.sites[address]["cert"] = active_cert
        return self.sites[address]

    def deleteSiteData(self, address):
        if address in self.sites:
            del(self.sites[address])
            self.saveDelayed()
            self.log.debug("Deleted site: %s" % address)

    def setSiteSettings(self, address, settings):
        site_data = self.getSiteData(address)
        site_data["settings"] = settings
        self.saveDelayed()
        return site_data

    # Get data for a new, unique site
    # Return: [site_address, bip32_index, {"auth_address": "xxx", "auth_privatekey": "xxx", "privatekey": "xxx"}]
    def getNewSiteData(self):
        import random
        bip32_index = random.randrange(2 ** 256) % 100000000
        site_privatekey = CryptEpix.hdPrivatekey(self.master_seed, bip32_index)
        site_address = CryptEpix.privatekeyToAddress(site_privatekey)
        if not site_address or site_address is False:
            raise Exception("Failed to generate valid site address from privatekey")
        if site_address in self.sites:
            raise Exception("Random error: site exist!")
        # Save to sites
        self.getSiteData(site_address)
        self.sites[site_address]["privatekey"] = site_privatekey
        self.save()
        return site_address, bip32_index, self.sites[site_address]

    def generateNewIdentityAddress(self):
        """Generate a new BIP32-derived identity address using a sequential index.

        Uses a dedicated index range (starting at 100000001) separate from
        site-derived keys. The address is stored in self.sites so its private
        key can be found later for cert creation.

        Returns: (address, privatekey)
        """
        index = self.settings.get("next_identity_index", 100000001)
        privatekey = CryptEpix.hdPrivatekey(self.master_seed, index)
        address = CryptEpix.privatekeyToAddress(privatekey)
        if not address or address is False:
            raise Exception("Failed to generate identity address at index %d" % index)

        # Store so addCert can find the privatekey by auth_address
        if address not in [sd.get("auth_address") for sd in self.sites.values()]:
            # Create a synthetic site entry keyed by the address itself
            self.sites["_identity_%d" % index] = {
                "auth_address": address,
                "auth_privatekey": privatekey
            }

        self.settings["next_identity_index"] = index + 1
        self.save()
        self.log.debug("Generated new identity address: %s (index %d)" % (address, index))
        return address, privatekey

    # Get BIP32 address from site address
    # Return: cert auth_address if cert active, otherwise BIP32 derived auth address
    def getAuthAddress(self, address, create=True):
        cert = self.getCert(address)
        if cert:
            return cert["auth_address"]
        else:
            return self.getSiteData(address, create)["auth_address"]

    def getAuthPrivatekey(self, address, create=True):
        cert = self.getCert(address)
        if cert:
            return cert["auth_privatekey"]
        else:
            return self.getSiteData(address, create)["auth_privatekey"]

    # Add cert for the user
    def addCert(self, auth_address, domain, auth_type, auth_user_name, cert_sign):
        # Find privatekey by auth address
        if auth_address == self.master_address:
            auth_privatekey = self.master_seed
        else:
            matching = [site["auth_privatekey"] for site in list(self.sites.values()) if site["auth_address"] == auth_address]
            if not matching:
                raise Exception("Auth address %s not found in sites or master" % auth_address)
            auth_privatekey = matching[0]
        cert_node = {
            "auth_address": auth_address,
            "auth_privatekey": auth_privatekey,
            "auth_type": auth_type,
            "auth_user_name": auth_user_name,
            "cert_sign": cert_sign
        }
        # Check if we have already cert for that domain and its not the same
        if self.certs.get(domain) and self.certs[domain] != cert_node:
            return False
        elif self.certs.get(domain) == cert_node:  # Same, not updated
            return None
        else:  # Not exist yet, add
            self.certs[domain] = cert_node
            self.save()
            return True

    # Remove cert from user
    def deleteCert(self, domain):
        del self.certs[domain]

    # Set active cert for a site
    def setCert(self, address, domain):
        site_data = self.getSiteData(address)
        if domain:
            site_data["cert"] = domain
        else:
            if "cert" in site_data:
                del site_data["cert"]
        self.saveDelayed()
        return site_data

    # Activate cert on ALL existing sites (portable cert)
    def setCertGlobal(self, domain):
        for address, site_data in self.sites.items():
            if address.startswith("_identity_"):
                continue  # Skip synthetic identity entries
            if domain:
                site_data["cert"] = domain
            else:
                if "cert" in site_data:
                    del site_data["cert"]
        self.saveDelayed()

    # Get the globally active cert domain (if any site has a cert set)
    def getActiveCertDomain(self):
        for address, site_data in self.sites.items():
            if address.startswith("_identity_"):
                continue
            cert_domain = site_data.get("cert")
            if cert_domain and cert_domain in self.certs:
                return cert_domain
        return None

    # Get cert for the site address
    # Return: { "auth_address":.., "auth_privatekey":.., "auth_type": "web", "auth_user_name": "mud", "cert_sign":.. } or None
    def getCert(self, address):
        site_data = self.getSiteData(address, create=False)
        if not site_data or "cert" not in site_data:
            return None  # Site dont have cert
        return self.certs.get(site_data["cert"])

    # Get the directory name for user content on a site.
    # If an xID cert is active, returns the xID name with TLD (e.g. "smile.epix")
    # so content is stored under data/users/smile.epix/.
    # Otherwise returns the auth_address for backward compatibility.
    def getUserDirectory(self, address):
        cert = self.getCert(address)
        if cert and cert.get("auth_type") == "xid" and cert.get("auth_user_name"):
            return "%s.epix" % cert["auth_user_name"]
        return self.getAuthAddress(address)

    # Get cert user name for the site address
    # Return: user@certprovider.epix or None
    def getCertUserId(self, address):
        site_data = self.getSiteData(address, create=False)
        if not site_data or "cert" not in site_data:
            return None  # Site dont have cert
        cert = self.certs.get(site_data["cert"])
        if cert:
            return cert["auth_user_name"] + "@" + site_data["cert"]
