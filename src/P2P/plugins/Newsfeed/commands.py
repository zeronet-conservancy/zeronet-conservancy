"""Trio port of a scoped slice of plugins/Newsfeed/NewsfeedPlugin.py --
the per-user "which feeds am I following on this site" state
(feedFollow/feedListFollow), same "add new websocket commands" pattern
P2P/plugins/CryptMessage established (see its own module docstring for
why no special import-ordering is needed for this).

Deliberately NOT ported: actionFeedQuery/actionFeedSearch -- the actual
cross-site feed aggregation and search. Both need Db/DbQuery.py's SQL-
query-string-manipulation helper (rewriting a schema-declared query to
add date filters/search LIKE clauses) ported first, plus iterating every
site's own database (site_manager.sites, each site.storage.query()) --
real, substantial work of its own, not a small addition on top of what's
here. Also not ported: formatSiteInfo()'s feed_follow_num field override
-- P2P/Ui/commands.py's formatSiteInfo() is a plain function, not a class
method plugins can override via super(), so there's no hook point for
this without restructuring that function into something pluggable
(a bigger, separate design change, not specific to this plugin).

feedFollow/feedListFollow store directly on the user's per-site settings
dict (user.getSiteData(address)["follow"]) via markDirty() -- not calling
save() immediately, matching this stack's other simple per-site setters
(e.g. P2P/Ui/commands.py's userSetSettings does the same). Not routed
through a registerTo("User") setFeedFollow() extension the way the
original does it (a User plugin method) -- the command handler can just
manipulate the site data dict directly, which is simpler and avoids the
@acceptPlugins import-ordering requirement entirely for this piece.
"""
from P2P.Ui.commands import _param, _requireSite, _requireUser, command


@command("feedFollow")
async def _cmdFeedFollow(session, params):
    site = _requireSite(session)
    user = await _requireUser(session)
    feeds = _param(params, "feeds", 0)
    site_data = user.getSiteData(site.address)
    site_data["follow"] = feeds
    user.markDirty()
    return "ok"


@command("feedListFollow")
async def _cmdFeedListFollow(session, params):
    site = _requireSite(session)
    user = await _requireUser(session)
    return user.getSiteData(site.address, create=False).get("follow", {})
