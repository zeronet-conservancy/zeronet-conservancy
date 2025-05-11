"""API related to getting info/manipulation on sites
"""

from .Exceptions import BadAddress
from .Util import ws_api_call, requires_permission, wrap_api_reply
from Content import ContentDb
from Site.Sanity import checkSite, fixAddressesIn
import dataclasses
from typeguard import typechecked
from typing import List
from util.deprecate import wip

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
def siteDetails(ws, to, address):
    """Details on specified site"""
    site = ws.server.sites.get(address)
    if site is None:
        raise BadAddress(address)
    cdb = ContentDb.getContentDb()
    total_size, optional_size = cdb.getTotalSize(site)
    owned_size = cdb.getTotalSignedSize(site.address)
    return {
        'total_size': total_size,
        'optional_size': optional_size,
        'owned_size': owned_size,
    }

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@typechecked
def siteDiagnose(ws, to, address: str):
    """Diagnose sanity of a site"""
    site = ws.server.sites.get(address)
    if site is None:
        raise BadAddress(address)
    res = checkSite(site)
    return dataclasses.asdict(res)

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@wip
@typechecked
def siteFixUserPermissions(
        ws,
        to,
        address: str,
        content_path: str,
        user_addresses: List[str]
):
    site = ws.server.sites.get(address)
    if site is None:
        raise BadAddress(address)
    fixAddressesIn(site, content_path, user_addresses)
    return 'ok'
