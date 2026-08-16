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

Deliberately NOT ported: mergerSiteAdd/mergerSiteDelete (registering a
NEW merged site and syncing its own content.json -- a real, separate
site-discovery/download feature, not a listing/path-resolution one) and
the hasSitePermission() cross-site permission bridge (letting a merged
site's own connection implicitly gain permissions on sites that merge
it -- narrower, less commonly hit than the read-path this shares with
_resolveMergerPath())."""
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
