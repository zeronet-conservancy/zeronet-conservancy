import json
import pathlib
import tempfile

import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.Newsfeed  # noqa: F401

from P2P.Site import Site
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
