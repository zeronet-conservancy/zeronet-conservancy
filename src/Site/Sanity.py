"""Check sanity of a site and/or fix it"""

from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum
import json

from util.JSONWalk import walkJSON

from Content import ContentDb
from Crypt.CryptBitcoin import isValidAddress

@dataclass
class CheckAddressResult:
    bad: bool
    error: Optional[str] = None
    user: Optional[str] = None

    def __str__(self):
        if not self.bad:
            return 'ok'
        err = self.error or 'unknown-error'
        return f'{err}({self.user})'

BadUserPermissionList = List[CheckAddressResult]

@dataclass
class CheckSiteResult:
    """Result of a sanity check.

    Currently only check for bad user permission list is implemented.
    """
    all_ok: bool
    bad_user_permissions: BadUserPermissionList

def checkSite(site) -> CheckSiteResult:
    """Check for sanity of a site"""
    bad_user_permissions = checkUserPermissionsAddresses(site)
    return CheckSiteResult(
        all_ok = not bad_user_permissions,
        bad_user_permissions = bad_user_permissions,
    )

def checkUserPermissionsAddresses(site) -> BadUserPermissionList:
    cdb = ContentDb.getContentDb()
    res = []
    for inner_path in cdb.getAllSiteOwnedContentPaths(site):
        with site.storage.open(inner_path) as content_f:
            contents = json.load(content_f)
        user_permissions = contents.get('user_contents', {}).get('permissions')
        if user_permissions:
            for user_address in user_permissions:
                address_result = checkAddress(user_address)
                if address_result.bad:
                    res.append(address_result)
    return res

def checkAddress(address) -> CheckAddressResult:
    if '@' in address:
        return CheckAddressResult(bad = True, error = "non-unique", user = address)
    try:
        if isValidAddress(address):
            return CheckAddressResult(bad = False, user = address)
    except Exception as exc:
        return CheckAddressResult(bad = True, error = str(exc), user = address)
    return CheckAddressResult(bad = True, error = "not-a-key", user = address)

def fixAddressesIn(site, content_path, addresses):
    replacements = getAddressReplacements(site, addresses)
    with site.storage.open(content_path) as f:
        contents = json.load(f)
    new_contents = replaceAddressesIn(contents, replacements)
    with site.storage.open(content_path, 'w') as f:
        json.dump(new_contents, f)

def replaceAddressesIn(content, replaces):
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

def getAddressReplacements(site, addresses):
    cdb = ContentDb.getContentDb()
    res = {}
    for inner_path in cdb.getAllContentPaths(site):
        if inner_path.parent:
            maybe_address = inner_path.parent.name
            if isValidAddress(maybe_address):
                with site.storage.open(inner_path) as content_f:
                    contents = json.load(content_f)
                    user_id = contents.get('cert_user_id')
                    if user_id and user_id in addresses:
                        res[user_id] = maybe_address
    return res
