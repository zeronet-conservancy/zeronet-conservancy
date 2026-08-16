"""mergerSiteList only -- found live, driving the real ZeroMe site (a
merger site: it combines a "master" content site with per-user content
sites, e.g. each user's own posts, into one merged feed). ZeroMe's own
checkUser() calls mergerSiteList unconditionally on every page load;
with no command at all registered, the response came back undefined,
and merged_sites[address] crashed reading a property of undefined.

Real, not faked: legacy MergerSitePlugin.actionMergerSiteList() returns
{} for any site with no merged sites tracked yet ("not a merger site" is
even its own explicit case for an empty merger_types lookup) -- this
stack genuinely has zero merged sites for any address, since the rest
of the merger mechanism below is NOT ported, so an empty dict is the
honest, correct answer for every site, not a stand-in.

Deliberately NOT ported: mergerSiteAdd/mergerSiteDelete (registering a
merged site and syncing its own content.json), and the actual DB/file
merging machinery itself (merger_db/merged_db, checkMergerPath()'s
inner_path rewriting for "merged-*" paths, the hasSitePermission()
cross-site permission bridge). A real, substantial separate feature --
this stack's ContentManager/SiteStorage have no concept of one site's
storage transparently reading through into another's, and building
that is out of scope for what was needed here (stopping a crash on an
otherwise-uncalled path, not adding merge functionality)."""
from P2P.Ui.commands import command


@command("mergerSiteList")
async def _cmdMergerSiteList(session, params):
    return {}
