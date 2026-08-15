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
