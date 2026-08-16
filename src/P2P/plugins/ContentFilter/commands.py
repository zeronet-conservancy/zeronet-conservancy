"""New websocket commands for the ContentFilter plugin's siteblock
feature -- see SiteManagerPlugin.py's own module docstring for scope.
Same "add new commands" pattern P2P/plugins/CryptMessage established
(no import-ordering ceremony needed for this half); SiteManagerPlugin.py
covers the registerTo("SiteManager") half instead, which DOES need
loadPlugins() to run before SiteManager is first imported/decorated --
see P2P.PluginManager's own module docstring for that ordering caveat.
"""
from P2P.Ui.commands import CommandError, _param, _requireAdmin, command

from . import SiteManagerPlugin


def _requireFilterStorage():
    if SiteManagerPlugin.filter_storage is None:
        raise CommandError("ContentFilter storage not initialized -- no SiteManager constructed yet")
    return SiteManagerPlugin.filter_storage


@command("siteblockAdd")
async def _cmdSiteblockAdd(session, params):
    _requireAdmin(session)
    storage = _requireFilterStorage()
    address = _param(params, "site_address", 0)
    reason = _param(params, "reason", 1)
    storage.siteblockAdd(address, reason)
    return "ok"


@command("siteblockRemove")
async def _cmdSiteblockRemove(session, params):
    _requireAdmin(session)
    storage = _requireFilterStorage()
    address = _param(params, "site_address", 0)
    storage.siteblockRemove(address)
    return "ok"


@command("siteblockList")
async def _cmdSiteblockList(session, params):
    _requireAdmin(session)
    storage = _requireFilterStorage()
    return storage.file_content["siteblocks"]


@command("siteblockGet")
async def _cmdSiteblockGet(session, params):
    _requireAdmin(session)
    storage = _requireFilterStorage()
    address = _param(params, "site_address", 0)
    details = storage.getSiteblockDetails(address)
    if details is None:
        return {"error": "Site block not found"}
    return details


@command("muteAdd")
async def _cmdMuteAdd(session, params):
    _requireAdmin(session)
    storage = _requireFilterStorage()
    auth_address = _param(params, "auth_address", 0)
    storage.muteAdd(auth_address, _param(params, "cert_user_id", 1), _param(params, "reason", 2))
    return "ok"


@command("muteRemove")
async def _cmdMuteRemove(session, params):
    _requireAdmin(session)
    storage = _requireFilterStorage()
    storage.muteRemove(_param(params, "auth_address", 0))
    return "ok"


@command("muteList")
async def _cmdMuteList(session, params):
    _requireAdmin(session)
    return _requireFilterStorage().file_content["mutes"]


@command("FilterIncludeList")
async def _cmdFilterIncludeList(session, params):
    """The "filter includes" feature itself (subscribing to another
    site's own mute/siteblock list) is NOT ported -- see this plugin's
    module docstring and storage.py's for why (filter-includes/mutes need
    WorkerManager to be pluggable, which it isn't yet). But the real
    wrapper.js's MuteList.updateFilterIncludes() calls this command
    unconditionally on load, and an "Unknown command" reply crashed on
    res.length. An empty list is the honest answer, not a stub standing
    in for a lie -- this stack genuinely has zero filter-includes, since
    there's no way to add one yet."""
    return []
