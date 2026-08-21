import json
import pathlib
import tempfile
import time

import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.Newsfeed  # noqa: F401

from P2P.Site import Site
from P2P.SiteManager import SiteManager
from P2P.UserManager import UserManager
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsNewsfeed:
    def testFeedFollowThenListFollowRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()

                address = "1TestNewsfeedSiteAAAAAAAAAAAA"
                site = Site(address, data_dir / address)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        feeds = {"my_feed": ["SELECT * FROM post", []]}
                        follow_reply = await _call(ws, "feedFollow", {"feeds": feeds}, msg_id=1)
                        list_reply = await _call(ws, "feedListFollow", msg_id=2)
                        return follow_reply, list_reply

        follow_reply, list_reply = compat.run(scenario)
        assert follow_reply["result"] == "ok"
        assert list_reply["result"] == {"my_feed": ["SELECT * FROM post", []]}

    def testFeedListFollowEmptyByDefault(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()

                address = "1TestNewsfeedSite2AAAAAAAAAAA"
                site = Site(address, data_dir / address)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "feedListFollow")

        reply = compat.run(scenario)
        assert reply["result"] == {}

    def testFeedFollowPersistsAcrossUserManagerReload(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user = user_manager.create()

                address = "1TestNewsfeedSite3AAAAAAAAAAA"
                site = Site(address, data_dir / address)

                server = UiServer(sites={address: site}, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        await _call(ws, "feedFollow", {"feeds": {"f": ["q", []]}})

                await user.save()  # markDirty() alone doesn't persist -- caller's job, matching User.py's convention

                reloaded_manager = UserManager(data_dir)
                await reloaded_manager.load()
                reloaded_user = next(iter(reloaded_manager.users.values()))
                return reloaded_user.getSiteData(address, create=False).get("follow")

        assert compat.run(scenario) == {"f": ["q", []]}

    def testFeedSearchFindsMatchingRowsAcrossAllKnownSites(self):
        """Real port of the original's actionFeedSearch -- a full-text
        search across every KNOWN site's own dbschema.json "feeds"
        queries, not just ones the current user follows (that's
        feedQuery's own job, already ported). Found live auditing every
        bundled site's own Page.cmd() calls against this stack's
        registered commands (the same investigation that found fileRules
        missing for ZeroMail)."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                site_manager = SiteManager(data_dir)

                address = "1TestFeedSearchSiteAAAAAAAA1"
                site = Site(address, data_dir / "site")
                site.permissions = ["ADMIN"]
                site.content_manager.contents["content.json"] = {"title": "Search Site"}
                site_manager.sites[address] = site

                schema = {
                    "db_name": "Test", "db_file": "site.db", "version": 1,
                    "tables": {
                        "post": {
                            "cols": [["date_added", "INTEGER"], ["title", "TEXT"], ["body", "TEXT"]],
                            "schema_changed": 1,
                        },
                    },
                    "feeds": {"posts": "SELECT date_added, title AS title, body AS body FROM post"},
                }
                await site.storage.writeJson("dbschema.json", schema)
                db = await site.storage.getDb()
                now = int(time.time())
                await db.execute(
                    "INSERT INTO post (date_added, title, body) VALUES (?, ?, ?)",
                    (now, "Hello world", "a matching post"),
                )
                await db.execute(
                    "INSERT INTO post (date_added, title, body) VALUES (?, ?, ?)",
                    (now, "Other", "unrelated content"),
                )
                await db.commit("test setup")

                server = UiServer(sites={address: site}, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "feedSearch", {"search": "matching"})

        reply = compat.run(scenario)
        result = reply["result"]
        assert result["num"] == 1
        assert result["rows"][0]["title"] == "Hello world"
        assert result["rows"][0]["site"] == "1TestFeedSearchSiteAAAAAAAA1"
        assert result["rows"][0]["feed_name"] == "posts"

    def testFeedSearchSiteFilterExcludesOtherSites(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                site_manager = SiteManager(data_dir)

                schema = {
                    "db_name": "Test", "db_file": "site.db", "version": 1,
                    "tables": {
                        "post": {
                            "cols": [["date_added", "INTEGER"], ["title", "TEXT"], ["body", "TEXT"]],
                            "schema_changed": 1,
                        },
                    },
                    "feeds": {"posts": "SELECT date_added, title AS title, body AS body FROM post"},
                }
                now = int(time.time())

                address_a = "1TestFeedSearchSiteAAAAAAAA2"
                site_a = Site(address_a, data_dir / "a")
                site_a.permissions = ["ADMIN"]
                site_a.content_manager.contents["content.json"] = {"title": "Site A"}
                site_manager.sites[address_a] = site_a
                await site_a.storage.writeJson("dbschema.json", schema)
                db_a = await site_a.storage.getDb()
                await db_a.execute(
                    "INSERT INTO post (date_added, title, body) VALUES (?, ?, ?)", (now, "A post", "shared text"),
                )
                await db_a.commit("test setup")

                address_b = "1TestFeedSearchSiteAAAAAAAA3"
                site_b = Site(address_b, data_dir / "b")
                site_b.content_manager.contents["content.json"] = {"title": "Site B"}
                site_manager.sites[address_b] = site_b
                await site_b.storage.writeJson("dbschema.json", schema)
                db_b = await site_b.storage.getDb()
                await db_b.execute(
                    "INSERT INTO post (date_added, title, body) VALUES (?, ?, ?)", (now, "B post", "shared text"),
                )
                await db_b.commit("test setup")

                server = UiServer(sites={address_a: site_a}, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site_a)) as ws:
                        return await _call(ws, "feedSearch", {"search": "shared site:Site A"})

        reply = compat.run(scenario)
        result = reply["result"]
        assert result["num"] == 1
        assert result["rows"][0]["site"] == "1TestFeedSearchSiteAAAAAAAA2"

    def testFeedSearchRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                user_manager = UserManager(data_dir)
                user_manager.create()
                site_manager = SiteManager(data_dir)

                address = "1TestFeedSearchNonAdminSiteA1"
                site = Site(address, data_dir / "site")  # No ADMIN permission
                site_manager.sites[address] = site

                server = UiServer(sites={address: site}, site_manager=site_manager, user_manager=user_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "feedSearch", {"search": "anything"})

        reply = compat.run(scenario)
        assert "error" in reply
