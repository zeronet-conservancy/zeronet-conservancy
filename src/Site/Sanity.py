"""Check sanity of a site and/or fix it"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum
import json

from util.JSON import walkJSON

from Content import ContentDb
from Crypt.CryptBitcoin import isValidAddress

class DuplicateIdentity(Exception):
    def __init__(self, address, a, b):
        self.address = address
        self.a = a
        self.b = b
        super().__init__(f"Duplicate identity for {address}: '{a}', '{b}'")

@dataclass
class CheckAddressResult:
    is_ok: bool
    error: Optional[str] = None
    user: Optional[str] = None

    def __str__(self):
        if self.is_ok:
            return 'ok'
        err = self.error or 'unknown-error'
        return f'{err}({self.user})'

@dataclass
class CheckContentResult:
    is_ok: bool
    inner_path: str
    user_addresses: List[CheckAddressResult]

@dataclass
class CheckSiteResult:
    """Result of a sanity check.

    Currently only check for bad user permission list is implemented.
    """
    is_ok: bool
    contents: List[CheckContentResult]

def checkSite(site) -> CheckSiteResult:
    """Check for sanity of a site"""
    contents = checkUserPermissionsAddresses(site)
    return CheckSiteResult(
        is_ok = all(c.is_ok for c in contents),
        contents = contents,
    )

def checkUserPermissionsAddresses(site) -> List[CheckContentResult]:
    cdb = ContentDb.getContentDb()
    res = []
    for inner_path in cdb.getAllSiteOwnedContentPaths(site):
        user_addresses = []
        with site.storage.open(inner_path) as content_f:
            contents = json.load(content_f)
        user_permissions = contents.get('user_contents', {}).get('permissions')
        if user_permissions:
            for user_address in user_permissions:
                address_result = checkAddress(user_address)
                if not address_result.is_ok:
                    user_addresses.append(address_result)
        res.append(CheckContentResult(
            is_ok = all(x.is_ok for x in user_addresses),
            inner_path = str(inner_path),
            user_addresses = user_addresses
        ))
    return res

def checkAddress(address) -> CheckAddressResult:
    if '@' in address:
        return CheckAddressResult(is_ok = False, error = "non-unique", user = address)
    try:
        if isValidAddress(address):
            return CheckAddressResult(is_ok = True, user = address)
    except Exception as exc:
        return CheckAddressResult(is_ok = False, error = str(exc), user = address)
    return CheckAddressResult(
        is_ok = False,
        error = "not-a-key",
        user = address
    )

def fixAddressesIn(site, content_path, addresses):
    """Fixes user addresses in a given site/content_path"""
    print('fixADDDR_IN', content_path, addresses)
    replacements = getAddressReplacements(site, addresses)
    print(replacements)
    with site.storage.open(content_path) as f:
        contents = json.load(f)
    new_contents = replaceAddressesIn(contents, replacements)
    with site.storage.open(content_path, 'w') as f:
        json.dump(new_contents, f, indent=1)

def replaceAddressesIn(content, replaces):
    """Replace address in dict structure"""
    def onDictElement(key, obj):
        if key == "permissions":
            res = {}
            for address, permissions in obj.items():
                if address in replaces:
                    address = replaces[address]
                res[address] = permissions
            return key, res
        return None
    return walkJSON(
        content,
        onDictElement = onDictElement,
    )

# TODO: look for ID sites if address not found on site

def getAddressReplacements(site, addresses):
    """Find replacements

    Looks for users that have already posted to this site using their address
    """
    cdb = ContentDb.getContentDb()
    res = {}
    for inner_path in cdb.getAllSiteContentPaths(site):
        print('GAR:', inner_path)
        if inner_path.parent and inner_path.parent.name:
            maybe_address = inner_path.parent.name
            print(maybe_address)
            if isValidAddress(maybe_address):
                try:
                    with site.storage.open(inner_path) as content_f:
                        contents = json.load(content_f)
                except Exception as exc:
                    print('issue with file', exc)
                    continue
                user_id = contents.get('cert_user_id')
                if user_id and user_id in addresses:
                    if user_id in res and res[user_id] != maybe_address:
                        raise DuplicateIdentity(user_id, res[user_id], maybe_address)
                    res[user_id] = maybe_address
    return res
