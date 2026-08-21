import json
import pathlib
import tempfile

import trio_websocket

# Import side effect: registers this plugin's commands. No special
# ordering needed -- see the plugin's own module docstring.
import P2P.plugins.Chart  # noqa: F401

from P2P.Site import Site
from P2P.Ui.UiServer import UiServer
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    return json.loads(await ws.get_message())


class TestP2PPluginsChart:
    def testChartDbQueryAgainstRealButEmptyDb(self):
        """No ChartCollector exists to populate chart.db (see commands.py's
        own module docstring) -- a real query against a real, freshly
        created db should still succeed and return an honest empty
        result, not error."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                address = "1TestChartDbQuerySiteAAAAAA1"
                site = Site(address, data_dir / "site")
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site}, data_dir=data_dir)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "chartDbQuery", {"query": "SELECT * FROM data"})

        reply = compat.run(scenario)
        assert reply["result"] == []

    def testChartDbQueryReturnsRealInsertedRows(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                address = "1TestChartDbQuerySite2AAAAA1"
                site = Site(address, data_dir / "site")
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site}, data_dir=data_dir)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        from P2P.plugins.Chart.chart_db import getChartDb
                        from P2P.Ui.UiServer import UiSession

                        # Seed a real row directly through the same Db
                        # instance the command itself resolves to (same
                        # data_dir -> same cached instance, see chart_db.py).
                        fake_session = UiSession(server.app)
                        db = await getChartDb(fake_session)
                        await db.execute("INSERT INTO type ?", {"type_id": 1, "name": "peers"})
                        await db.execute("INSERT INTO data ?", {"type_id": 1, "site_id": None, "value": 42})
                        await db.commit("test setup")

                        return await _call(ws, "chartDbQuery", {"query": "SELECT value FROM data"})

        reply = compat.run(scenario)
        assert reply["result"] == [{"value": 42}]

    def testChartDbQueryRejectsNonSelect(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                address = "1TestChartDbQueryRejectAAAA1"
                site = Site(address, data_dir / "site")
                site.permissions = ["ADMIN"]

                server = UiServer(sites={address: site}, data_dir=data_dir)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "chartDbQuery", {"query": "DELETE FROM data"})

        reply = compat.run(scenario)
        assert "error" in reply["result"]

    def testChartDbQueryRequiresAdmin(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                address = "1TestChartDbQueryNonAdminAA1"
                site = Site(address, data_dir / "site")  # No ADMIN permission

                server = UiServer(sites={address: site}, data_dir=data_dir)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, site)) as ws:
                        return await _call(ws, "chartDbQuery", {"query": "SELECT * FROM data"})

        reply = compat.run(scenario)
        assert "error" in reply["result"]
