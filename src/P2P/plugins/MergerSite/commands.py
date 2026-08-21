"""mergerSiteList -- found live, driving the real ZeroMe site (a merger
site: it combines a "master" content site with per-user content sites,
e.g. each user's own posts, into one merged feed). ZeroMe's own
checkUser() calls mergerSiteList unconditionally on every page load;
with no command at all registered, the response came back undefined,
and merged_sites[address] crashed reading a property of undefined.

Real now, not just crash-preventing: returns every currently-loaded site
whose content.json declares itself as the connected site's own merged
type (via P2P.Ui.commands._mergedType()/_mergerTypes(), the same helpers
_resolveMergerPath() uses for the actual cross-site file reads -- see
that function's own docstring in P2P/Ui/commands.py for the read-path
half of MergerSite this shares a foundation with). {} for any site with
no merger permission at all, matching the original's own "not a merger
site" case exactly.

mergerSiteAdd/mergerSiteDelete are ported now too, once it turned out
they don't need a real download -- registering a site is already exactly
what commands.py's own siteAdd does (SiteManager.add() + a fire-and-
forget announce, no content actually fetched yet; that happens
on-demand via whatever needs it next, same as siteAdd), so
mergerSiteAdd is that same wiring per address, gated on the connected
site actually being a merger (_mergerTypes() non-empty). Skips the
original's confirm-dialog/RateLimit round trip for >1 address, same
"grant directly, no confirm step" precedent permissionAdd/
corsPermissionAdd already established (no server-held continuation
mechanism exists here -- see _resolveCorsPath()'s own docstring).
mergerSiteDelete matches the original closely: it doesn't actually
delete anything either (validates the merge-type permission and
responds "ok", relying on a separate real siteDelete call to do the
actual removal) -- ported faithfully, not a simplification on my part.

Deliberately NOT ported: the hasSitePermission() cross-site permission
bridge (letting a merged site's own connection implicitly gain
permissions on sites that merge it -- narrower, less commonly hit than
the read-path _resolveMergerPath() already covers)."""
from P2P.Ui.commands import _mergedType, _mergerTypes, _param, _requireSite, _requireSiteManager, command, formatSiteInfo


@command("mergerSiteList")
async def _cmdMergerSiteList(session, params):
    site = _requireSite(session)
    merger_types = _mergerTypes(site)
    if not merger_types:
        return {"error": "Not a merger site"}

    query_site_info = bool(_param(params, "query_site_info", 0, False))
    site_manager = _requireSiteManager(session)
    result = {}
    for address, merged_site in site_manager.sites.items():
        merged_type = _mergedType(merged_site)
        if merged_type not in merger_types:
            continue
        if query_site_info:
            result[address] = formatSiteInfo(merged_site, site_manager)
        else:
            result[address] = merged_type
    return result


@command("mergerSiteAdd")
async def _cmdMergerSiteAdd(session, params):
    site = _requireSite(session)
    addresses = _param(params, "addresses", 0, [])
    if not isinstance(addresses, list):
        addresses = [addresses]
    if not _mergerTypes(site):
        return {"error": "Not a merger site"}

    site_manager = _requireSiteManager(session)
    add_site = getattr(session.app, "on_missing_site", None)
    for address in addresses:
        if address in site_manager.sites:
            continue  # Already added
        new_site = add_site(address) if add_site is not None else site_manager.add(address)
        if not new_site:
            continue
        # App.addSite() -> App._wireSite() already starts this site's
        # announce loop (first iteration = immediate announce) if the app
        # is running -- no separate announce-once trigger needed here.
    return "ok"


@command("mergerSiteDelete")
async def _cmdMergerSiteDelete(session, params):
    site = _requireSite(session)
    address = _param(params, "address", 0)

    site_manager = _requireSiteManager(session)
    target = site_manager.sites.get(address)
    if target is None:
        return {"error": "No site found: %s" % address}

    merger_types = _mergerTypes(site)
    if not merger_types:
        return {"error": "Not a merger site"}
    merged_type = _mergedType(target)
    if merged_type not in merger_types:
        return {"error": "Merged type (%s) not in %s" % (merged_type, merger_types)}

    return "ok"
