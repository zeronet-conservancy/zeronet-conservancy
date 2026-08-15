import json
import pathlib
import tempfile

from P2P.SiteManager import SiteManager
from P2P import compat


VALID_ADDRESS = "1TestSiteAddress1234567890AB"  # 28 chars, matches ADDRESS_RE


class TestP2PSiteManager:
    def testIsAddressValidatesFormat(self):
        sm = SiteManager(pathlib.Path("/tmp"))
        assert sm.isAddress(VALID_ADDRESS) is True
        assert sm.isAddress("too-short") is False
        assert sm.isAddress("has spaces in it 1234567890") is False

    def testLoadWithNoSitesJsonLeavesEmpty(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                sm = SiteManager(pathlib.Path(d))
                await sm.load()
                return sm.sites, sm.loaded

        sites, loaded = compat.run(scenario)
        assert sites == {}
        assert loaded is True

    def testLoadCreatesSiteForEachAddress(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                (data_dir / "sites.json").write_text(json.dumps({VALID_ADDRESS: {"serving": False, "own": True}}))
                sm = SiteManager(data_dir)
                await sm.load()
                return sm.sites, sm._site_settings

        sites, settings = compat.run(scenario)
        assert VALID_ADDRESS in sites
        assert sites[VALID_ADDRESS].isServing() is False
        assert settings[VALID_ADDRESS]["own"] is True

    def testLoadSkipsInvalidAddress(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                (data_dir / "sites.json").write_text(json.dumps({"not-a-valid-address": {}}))
                sm = SiteManager(data_dir)
                await sm.load()
                return sm.sites

        assert compat.run(scenario) == {}

    def testLoadWithCleanupRemovesMissingAddress(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                sm = SiteManager(data_dir)
                sm.add(VALID_ADDRESS)
                (data_dir / "sites.json").write_text(json.dumps({}))
                await sm.load(cleanup=True)
                return sm.sites

        assert compat.run(scenario) == {}

    def testLoadWithoutCleanupKeepsExtraSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                sm = SiteManager(data_dir)
                sm.add(VALID_ADDRESS)
                (data_dir / "sites.json").write_text(json.dumps({}))
                await sm.load(cleanup=False)
                return sm.sites

        assert VALID_ADDRESS in compat.run(scenario)

    def testAddReturnsSameSiteOnSecondCall(self):
        with tempfile.TemporaryDirectory() as d:
            sm = SiteManager(pathlib.Path(d))
            site1 = sm.add(VALID_ADDRESS)
            site2 = sm.add(VALID_ADDRESS)
            assert site1 is site2

    def testAddRejectsInvalidAddress(self):
        with tempfile.TemporaryDirectory() as d:
            sm = SiteManager(pathlib.Path(d))
            assert sm.add("not-valid") is False

    def testNeedCreatesIfMissing(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                sm = SiteManager(pathlib.Path(d))
                before = await sm.get(VALID_ADDRESS)
                site = await sm.need(VALID_ADDRESS)
                after = await sm.get(VALID_ADDRESS)
                return before, site, after

        before, site, after = compat.run(scenario)
        assert before is None
        assert site is not None
        assert after is site

    def testDeleteRemovesSite(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                sm = SiteManager(pathlib.Path(d))
                sm.add(VALID_ADDRESS)
                sm.delete(VALID_ADDRESS)
                return await sm.get(VALID_ADDRESS)

        assert compat.run(scenario) is None

    def testSaveWritesBackServingAndSize(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                sm = SiteManager(data_dir)
                site = sm.add(VALID_ADDRESS, own=True)
                site.serving = False
                await sm.save()
                return json.loads((data_dir / "sites.json").read_text())

        data = compat.run(scenario)
        assert data[VALID_ADDRESS]["serving"] is False
        assert data[VALID_ADDRESS]["own"] is True
        assert data[VALID_ADDRESS]["size"] == 0

    def testSaveThenLoadRoundTrips(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                sm1 = SiteManager(data_dir)
                sm1.add(VALID_ADDRESS, own=True)
                await sm1.save()

                sm2 = SiteManager(data_dir)
                await sm2.load()
                return sm2.sites, sm2._site_settings

        sites, settings = compat.run(scenario)
        assert VALID_ADDRESS in sites
        assert settings[VALID_ADDRESS]["own"] is True
