"""Trio port of a scoped slice of plugins/Newsfeed/NewsfeedPlugin.py --
the per-user "which feeds am I following on this site" state
(feedFollow/feedListFollow), plus feedQuery (the actual cross-site feed
aggregation), same "add new websocket commands" pattern P2P/plugins/
CryptMessage established (see its own module docstring for why no
special import-ordering is needed for this).

feedQuery was found missing live, driving the real ZeroHello dashboard
in a browser: FeedList's periodic "Updating feed" call got an undefined
result back (an unrecognized command), crashing on res.rows. Ported
faithfully from actionFeedQuery(): Db.DbQuery is a pure SQL-string
rewriting utility (no gevent/network dependency, safe to import as-is),
and the aggregation loop is the same shape -- iterate every site the
CURRENT USER has "follow" queries stored for (not just the current
site), run each one for real via that site's own site.storage.query(),
inject a day_limit date filter into a UNION-aware WHERE clause the same
way the original does, and merge/sort/limit the results. Genuinely a
no-op returning an empty (correctly-shaped) result on a fresh install:
nothing is followed anywhere until feedFollow is called for at least one
site, so the aggregation loop below simply doesn't execute -- this isn't
a stub, it's what the real logic does with no input.

feedSearch is ported now too, found live auditing every bundled site's
own Page.cmd() calls against this stack's registered commands (the same
investigation that found fileRules missing for ZeroMail). Unlike
feedQuery (aggregates only the CURRENT USER's own followed queries),
feedSearch is a LIKE-based full-text search across every KNOWN site's
own dbschema.json "feeds" queries, with optional "site:"/"type:" filter
prefixes parsed out of the search text (parseSearch(), same regex split
as the original). Reads each site's schema straight off disk via
SiteStorage.getDbSchema() -- same "answered directly from disk, not a
cached copy" choice this stack's own OptionalManager plugin already
made, for the same reason: no schema-caching layer exists here to keep
in sync with an already-open db's own in-memory schema.

Deliberately NOT ported from actionFeedQuery: the ":params" placeholder
substitution via util.helper.sqlquote (an advanced feed-query feature
none of the queries ZeroHello ships with actually use).

formatSiteInfo()'s feed_follow_num field IS ported, directly in
P2P/Ui/commands.py's formatSiteInfo() rather than here -- that function
is a plain function, not a class method plugins can override via
super(), but it already takes `user` as a plain argument, so the field
is set inline next to the other user-scoped fields (auth_address,
cert_user_id, privatekey) rather than needing a plugin hook point.

feedFollow/feedListFollow store directly on the user's per-site settings
dict (user.getSiteData(address)["follow"]) via markDirty() -- not calling
save() immediately, matching this stack's other simple per-site setters
(e.g. P2P/Ui/commands.py's userSetSettings does the same). Not routed
through a registerTo("User") setFeedFollow() extension the way the
original does it (a User plugin method) -- the command handler can just
manipulate the site data dict directly, which is simpler and avoids the
@acceptPlugins import-ordering requirement entirely for this piece.
"""
import re
import time

from Db.DbQuery import DbQuery

from P2P.Ui.commands import _param, _requireAdmin, _requireSite, _requireSiteManager, _requireUser, command


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


@command("feedQuery")
async def _cmdFeedQuery(session, params):
    _requireAdmin(session)
    user = await _requireUser(session)
    site_manager = _requireSiteManager(session)
    limit = _param(params, "limit", 0, 10)
    day_limit = _param(params, "day_limit", 1, 3)

    rows = []
    stats = []
    total_s = time.time()
    num_sites = 0

    for address, site_data in list(user.sites.items()):
        feeds = site_data.get("follow")
        if not feeds or not isinstance(feeds, dict):
            continue
        num_sites += 1
        for name, query_set in feeds.items():
            site = site_manager.sites.get(address)
            if site is None:
                continue

            s = time.time()
            try:
                query_raw, _query_params = query_set
                query_parts = re.split(r"UNION(?:\s+ALL|)", query_raw)
                for i, query_part in enumerate(query_parts):
                    db_query = DbQuery(query_part)
                    if day_limit:
                        date_field = db_query.fields.get("date_added", "date_added")
                        where = " WHERE %s > strftime('%%s', 'now', '-%s day')" % (date_field, day_limit)
                        if "WHERE" in query_part:
                            query_part = re.sub(r"WHERE (.*?)(?=$| GROUP BY)", where + r" AND (\1)", query_part)
                        else:
                            query_part += where
                    query_parts[i] = query_part
                query = " UNION ".join(query_parts) + " ORDER BY date_added DESC LIMIT %s" % limit
                res = await site.storage.query(query)
                site_rows = [dict(row) for row in res.fetchall()]
            except Exception as err:
                stats.append({"site": address, "feed_name": name, "error": str(err)})
                continue

            for row in site_rows:
                date_added = row.get("date_added")
                if not isinstance(date_added, (int, float)):
                    continue
                if date_added > 1000000000000:  # Formatted as milliseconds
                    date_added = date_added / 1000
                    row["date_added"] = date_added
                if date_added > time.time() + 120:
                    continue  # Feed item is in the future, skip it
                row["site"] = address
                row["feed_name"] = name
                rows.append(row)
            stats.append({"site": address, "feed_name": name, "taken": round(time.time() - s, 3)})

    return {
        "rows": rows, "stats": stats, "num": len(rows), "sites": num_sites,
        "taken": round(time.time() - total_s, 3),
    }


def _parseSearch(search: str):
    parts = re.split(r"(site|type):", search)
    if len(parts) > 1:  # Found a filter
        search_text = parts[0]
        parts = [part.strip() for part in parts]
        filters = dict(zip(parts[1::2], parts[2::2]))
    else:
        search_text = search
        filters = {}
    return search_text, filters


@command("feedSearch")
async def _cmdFeedSearch(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    search = _param(params, "search", 0, "") or ""
    limit = _param(params, "limit", 1, 30)
    day_limit = _param(params, "day_limit", 2, 30)

    search_text, filters = _parseSearch(search)

    rows = []
    stats = []
    num_sites = 0
    total_s = time.time()

    for address, other_site in list(site_manager.sites.items()):
        if not other_site.storage.hasDbSchema():
            continue

        if "site" in filters:
            title = (other_site.content_manager.contents.get("content.json") or {}).get("title", "")
            if filters["site"].lower() not in (address.lower(), title.lower()):
                continue

        try:
            schema = await other_site.storage.getDbSchema()
        except Exception:
            continue
        feeds = schema.get("feeds")
        if not feeds:
            continue
        num_sites += 1

        for name, query in feeds.items():
            if filters.get("type") and filters["type"] not in query:
                continue

            s = time.time()
            try:
                db_query = DbQuery(query)
                query_params = []
                if search_text:
                    db_query.wheres.append(
                        "(%s LIKE ? OR %s LIKE ?)" % (db_query.fields["body"], db_query.fields["title"])
                    )
                    search_like = "%" + search_text.replace(" ", "%") + "%"
                    query_params += [search_like, search_like]
                if day_limit:
                    date_field = db_query.fields.get("date_added", "date_added")
                    db_query.wheres.append(
                        "%s > strftime('%%s', 'now', '-%s day')" % (date_field, day_limit)
                    )
                db_query.parts["ORDER BY"] = "date_added DESC"
                db_query.parts["LIMIT"] = str(limit)
                res = await other_site.storage.query(str(db_query), query_params)
                site_rows = [dict(row) for row in res.fetchall()]
            except Exception as err:
                stats.append({"site": address, "feed_name": name, "error": str(err), "query": query})
                continue

            for row in site_rows:
                date_added = row.get("date_added")
                if not date_added or date_added > time.time() + 120:
                    continue
                row["site"] = address
                row["feed_name"] = name
                rows.append(row)
            stats.append({"site": address, "feed_name": name, "taken": round(time.time() - s, 3)})

    return {
        "rows": rows, "num": len(rows), "sites": num_sites,
        "taken": round(time.time() - total_s, 3), "stats": stats,
    }
