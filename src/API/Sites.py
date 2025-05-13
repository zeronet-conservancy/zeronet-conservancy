"""API related to getting info/manipulation on sites
"""

from .Exceptions import BadAddress
from .Util import ws_api_call, requires_permission, wrap_api_reply
from Content import ContentDb
from Content.Limits import updateLimitDataForSite, removeAllSiteLimits
from Site.Sanity import checkSite, fixAddressesIn
import dataclasses
from typeguard import typechecked
from typing import List
from util.deprecate import wip

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@typechecked
def siteDetails(ws, to, address: str):
    """Details on specified site"""
    site = ws.server.sites.get(address)
    if site is None:
        raise BadAddress(address)
    cdb = ContentDb.getContentDb()
    total_size, optional_size = cdb.getTotalSize(site)
    owned_size = cdb.getTotalSignedSize(site.address)
    favorite = site.settings.get('favorite')
    use_limit_priority = site.settings.get('use_limit_priority')
    return {
        'total_size': total_size,
        'optional_size': optional_size,
        'owned_size': owned_size,
        'favorite': favorite,
        'use_limit_priority': use_limit_priority,
    }

def setSiteSetting(ws, address, name, value) -> str:
    site = ws.server.sites.get(address)
    if site is None:
        raise BadAddress(address)
    site.settings[name] = value
    site.saveSettings()
    return 'ok'

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@typechecked
def siteFavorite(ws, to, address: str) -> str:
    return setSiteSetting(ws, address, 'favorite', True)

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@typechecked
def siteUnfavorite(ws, to, address: str) -> str:
    return setSiteSetting(ws, address, 'favorite', False)

siteFavourite = siteFavorite
siteUnfavourite = siteUnfavorite

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@typechecked
def siteLimitsUnsubscribe(ws, to, address: str) -> str:
    res = setSiteSetting(ws, address, 'use_limit_priority', None)
    site = ws.server.sites.get(address)
    if site is None:
        raise BadAddress(address)
    removeAllSiteLimits(site)
    return res

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@typechecked
def siteLimitsSubscribe(ws, to, address: str, priority: int) -> str:
    res = setSiteSetting(ws, address, 'use_limit_priority', priority)
    site = ws.server.sites.get(address)
    if site is None:
        raise BadAddress(address)
    updateLimitDataForSite(site)
    return res

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
