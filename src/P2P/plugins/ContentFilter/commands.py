"""New websocket commands for the ContentFilter plugin's siteblock
feature -- see SiteManagerPlugin.py's own module docstring for scope.
Same "add new commands" pattern P2P/plugins/CryptMessage established
(no import-ordering ceremony needed for this half); SiteManagerPlugin.py
covers the registerTo("SiteManager") half instead, which DOES need
loadPlugins() to run before SiteManager is first imported/decorated --
see P2P.PluginManager's own module docstring for that ordering caveat.

filterIncludeAdd/filterIncludeRemove are ported now too -- see storage.py's
own module docstring for what "filter includes" are and why they're
implementable now (mutes existing was the only real prerequisite).
FilterIncludeList returns real data for the first time accordingly.
"""
import json

from P2P.Ui.commands import CommandError, _param, _requireAdmin, _requireSite, command

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
@command("MuteList")  # The real dashboard site's own MuteList.coffee calls
# this by its original legacy-cased name (Page.cmd("MuteList", ...)), not
# the camelCase this port otherwise settled on -- found live, auditing
# every bundled site's own Page.cmd() calls against this stack's registered
# commands (the same investigation that found fileRules missing for
# ZeroMail). Registering both names is cheaper and less risky than picking
# one and possibly breaking whichever caller isn't ported yet.
async def _cmdMuteList(session, params):
    _requireAdmin(session)
    return _requireFilterStorage().file_content["mutes"]


@command("filterIncludeAdd")
async def _cmdFilterIncludeAdd(session, params):
    """Real port of the original's actionFilterIncludeAdd -- subscribes to
    another already-known site's own mutes/siteblocks (site_manager.
    sites.get(address) has to already have it; see storage.py's own
    docstring on why no auto-download is triggered). address defaults to
    the connected site (self-managing its own includes, no ADMIN needed,
    matching the original's own no-address branch); an explicit address
    (managing a DIFFERENT site's includes, e.g. from an ADMIN dashboard)
    requires ADMIN, matching the original's own check exactly.

    Unlike the original, this always applies immediately rather than
    prompting a client-side confirm() dialog first for a non-ADMIN
    connection -- same "no server-initiated request/response continuation
    mechanism yet" gap corsPermission's own docstring already notes; that
    confirm() was a UX nicety, not an actual permission check (the
    connected session could already read/write its own site's includes
    either way)."""
    site = _requireSite(session)
    storage = _requireFilterStorage()
    inner_path = _param(params, "inner_path", 0)
    description = _param(params, "description", 1)
    address = _param(params, "address", 2)
    if address:
        _requireAdmin(session)
    else:
        address = site.address
    storage.includeAdd(address, inner_path, description)
    return "ok"


@command("filterIncludeRemove")
async def _cmdFilterIncludeRemove(session, params):
    site = _requireSite(session)
    storage = _requireFilterStorage()
    inner_path = _param(params, "inner_path", 0)
    address = _param(params, "address", 1)
    if address:
        _requireAdmin(session)
    else:
        address = site.address
    if storage.includeRemove(address, inner_path):
        return "ok"
    return {"error": "Include not found"}


@command("FilterIncludeList")
async def _cmdFilterIncludeList(session, params):
    """Real port of the original's actionFilterIncludeList, now that
    filterIncludeAdd/Remove exist to actually create includes -- see
    storage.py's own module docstring for what's ported and what isn't
    (live refresh when an included file changes on disk). all_sites=True
    (every site's own includes, admin-visible -- what the real dashboard
    site's own MuteList.updateFilterIncludes() actually requests)
    requires ADMIN, matching the original; the default only returns the
    CONNECTED site's own includes, no ADMIN needed. filters=True expands
    each include with the referenced site's current mutes/siteblocks
    (skipped, not errored, for an include whose site isn't locally known
    -- same contract as includeUpdateAll() itself)."""
    site = _requireSite(session)
    storage = _requireFilterStorage()
    all_sites = bool(_param(params, "all_sites", 0, False))
    want_filters = bool(_param(params, "filters", 1, False))
    if all_sites:
        _requireAdmin(session)

    site_manager = getattr(session.app, "site_manager", None)
    back = []
    for include in storage.file_content["includes"].values():
        if not all_sites and include["address"] != site.address:
            continue
        include = dict(include)
        if want_filters:
            include_site = site_manager.sites.get(include["address"]) if site_manager else None
            if include_site is None:
                continue
            try:
                content = json.loads(include_site.storage.getPath(include["inner_path"]).read_text(encoding="utf8"))
            except (OSError, ValueError):
                continue
            include["mutes"] = content.get("mutes", {})
            include["siteblocks"] = content.get("siteblocks", {})
        back.append(include)
    return back
