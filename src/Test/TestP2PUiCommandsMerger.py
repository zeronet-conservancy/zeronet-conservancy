import json
import pathlib
import tempfile

import trio_websocket

from P2P.Ui.UiServer import UiServer
from P2P.SiteManager import SiteManager
import P2P.plugins.MergerSite  # noqa: F401 -- import side effect registers mergerSiteList
from P2P import compat


def _wsUrl(server, site):
    base_url = server.bound_addresses[0].replace("http://", "ws://")
    return "%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (base_url, site.wrapper_key)


async def _call(ws, cmd, params=None, msg_id=1):
    await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": msg_id}))
    while True:
        response = json.loads(await ws.get_message())
        if response.get("cmd") == "response" and response.get("to") == msg_id:
            return response


async def _makeMerged(site, merged_type):
    await site.storage.writeJson("content.json", {"merged_type": merged_type})
    await site.content_manager.loadContent("content.json")


class TestP2PUiCommandsMergerPathResolution:
    def testMergedPathWithoutPermissionIsDenied(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerNoPermSiteAAAAA1")  # No Merger: permission
                merged = site_manager.add("1TestMergerNoPermTargetAA1")
                await _makeMerged(merged, "ZeroMe")
                await merged.storage.write("data/1.json", b"post content")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(
                            ws, "fileGet",
                            {"inner_path": "merged-ZeroMe/%s/data/1.json" % merged.address},
                        )

        reply = compat.run(scenario)
        assert "error" in reply
        assert "No merger" in reply["error"]

    def testMergedPathReadsTargetSiteWhenTypesMatch(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerReaderSiteAAAA1")
                merger.permissions = ["Merger:ZeroMe"]
                merged = site_manager.add("1TestMergerTargetSiteAAAA1")
                await _makeMerged(merged, "ZeroMe")
                await merged.storage.write("data/1.json", b"a real merged post")
                await merged.storage.write("data/sub/2.json", b"nested")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        get_reply = await _call(
                            ws, "fileGet",
                            {"inner_path": "merged-ZeroMe/%s/data/1.json" % merged.address}, msg_id=1,
                        )
                        list_reply = await _call(
                            ws, "fileList",
                            {"inner_path": "merged-ZeroMe/%s/data" % merged.address}, msg_id=2,
                        )
                        dir_reply = await _call(
                            ws, "dirList",
                            {"inner_path": "merged-ZeroMe/%s/data" % merged.address}, msg_id=3,
                        )
                return get_reply, list_reply, dir_reply

        get_reply, list_reply, dir_reply = compat.run(scenario)
        assert get_reply["result"] == "a real merged post"
        assert sorted(list_reply["result"]) == ["1.json", "sub/2.json"]
        assert "sub" in dir_reply["result"]

    def testMergedPathRefusedWhenTargetDeclaresDifferentType(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerWrongTypeSiteA1")
                merger.permissions = ["Merger:ZeroMe"]
                merged = site_manager.add("1TestMergerWrongTypeTgtAA1")
                await _makeMerged(merged, "SomeOtherType")  # Doesn't match "ZeroMe"

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(
                            ws, "fileGet",
                            {"inner_path": "merged-ZeroMe/%s/data.json" % merged.address},
                        )

        reply = compat.run(scenario)
        assert "error" in reply
        assert "does not have permission" in reply["error"]

    def testMergedPathToUnknownSiteErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerUnknownReqSiteA1")
                merger.permissions = ["Merger:ZeroMe"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(
                            ws, "fileGet",
                            {"inner_path": "merged-ZeroMe/1UnknownMergedSiteXXXXXXXX/data.json"},
                        )

        reply = compat.run(scenario)
        assert "error" in reply
        assert "No site found" in reply["error"]


class TestP2PUiCommandsMergerSiteList:
    def testMergerSiteListNotAMergerSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                plain = site_manager.add("1TestMergerListPlainSiteA1")  # No Merger: permission

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, plain)) as ws:
                        return await _call(ws, "mergerSiteList")

        reply = compat.run(scenario)
        assert reply["result"] == {"error": "Not a merger site"}

    def testMergerSiteListReturnsKnownMergedSites(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerListSiteAAAAAA1")
                merger.permissions = ["Merger:ZeroMe"]
                merged_a = site_manager.add("1TestMergerListMergedAAAA1")
                await _makeMerged(merged_a, "ZeroMe")
                merged_b = site_manager.add("1TestMergerListMergedBBBB1")
                await _makeMerged(merged_b, "ZeroMe")
                unrelated = site_manager.add("1TestMergerListUnrelatedA1")
                await _makeMerged(unrelated, "SomeOtherType")  # Different type -- excluded

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(ws, "mergerSiteList")

        reply = compat.run(scenario)
        assert reply["result"] == {
            "1TestMergerListMergedAAAA1": "ZeroMe",
            "1TestMergerListMergedBBBB1": "ZeroMe",
        }

    def testMergerSiteListWithQuerySiteInfoReturnsFormattedInfo(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerListInfoSiteAA1")
                merger.permissions = ["Merger:ZeroMe"]
                merged = site_manager.add("1TestMergerListInfoTgtAAA1")
                await _makeMerged(merged, "ZeroMe")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(ws, "mergerSiteList", {"query_site_info": True})

        reply = compat.run(scenario)
        info = reply["result"]["1TestMergerListInfoTgtAAA1"]
        assert info["address"] == "1TestMergerListInfoTgtAAA1"  # Real formatSiteInfo() output, not a stub


class TestP2PUiCommandsMergerSiteAddDelete:
    def testMergerSiteAddRegistersNewSites(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerAddSiteAAAAAAAA1")
                merger.permissions = ["Merger:ZeroMe"]
                new_address_1 = "1TestMergerAddNewSiteAAAAA1"
                new_address_2 = "1TestMergerAddNewSiteBBBBB1"

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        reply = await _call(
                            ws, "mergerSiteAdd", {"addresses": [new_address_1, new_address_2]},
                        )
                return reply, new_address_1 in site_manager.sites, new_address_2 in site_manager.sites

        reply, has_1, has_2 = compat.run(scenario)
        assert reply["result"] == "ok"
        assert has_1 is True
        assert has_2 is True

    def testMergerSiteAddAcceptsSingleAddressNotJustList(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerAddSingleSiteAA1")
                merger.permissions = ["Merger:ZeroMe"]
                new_address = "1TestMergerAddSingleNewAAA1"

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        reply = await _call(ws, "mergerSiteAdd", {"addresses": new_address})
                return reply, new_address in site_manager.sites

        reply, added = compat.run(scenario)
        assert reply["result"] == "ok"
        assert added is True

    def testMergerSiteAddWithoutMergerPermissionErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                plain = site_manager.add("1TestMergerAddPlainSiteAA1")  # No Merger: permission

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, plain)) as ws:
                        return await _call(ws, "mergerSiteAdd", {"addresses": ["1SomeAddressAAAAAAAAAAAAAA1"]})

        reply = compat.run(scenario)
        assert reply["result"] == {"error": "Not a merger site"}

    def testMergerSiteDeleteOkWhenPermissionMatches(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerDeleteSiteAAAA1")
                merger.permissions = ["Merger:ZeroMe"]
                merged = site_manager.add("1TestMergerDeleteTargetAA1")
                await _makeMerged(merged, "ZeroMe")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(ws, "mergerSiteDelete", {"address": merged.address})

        reply = compat.run(scenario)
        assert reply["result"] == "ok"

    def testMergerSiteDeleteRefusedForWrongType(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerDeleteWrongSiteA1")
                merger.permissions = ["Merger:ZeroMe"]
                unrelated = site_manager.add("1TestMergerDeleteWrongTgtA1")
                await _makeMerged(unrelated, "SomeOtherType")

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(ws, "mergerSiteDelete", {"address": unrelated.address})

        reply = compat.run(scenario)
        assert "error" in reply["result"]

    def testMergerSiteDeleteUnknownSiteErrors(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                site_manager = SiteManager(data_dir)
                merger = site_manager.add("1TestMergerDeleteUnknownSiA1")
                merger.permissions = ["Merger:ZeroMe"]

                server = UiServer(sites=site_manager.sites, site_manager=site_manager)
                async with server.run():
                    async with trio_websocket.open_websocket_url(_wsUrl(server, merger)) as ws:
                        return await _call(ws, "mergerSiteDelete", {"address": "1NoSuchSiteXXXXXXXXXXXXXXX1"})

        reply = compat.run(scenario)
        assert "No site found" in reply["result"]["error"]
