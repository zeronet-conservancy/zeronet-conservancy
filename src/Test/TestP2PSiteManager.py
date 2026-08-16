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

    def testSavePersistsPeersAndLoadRestoresThem(self):
        """This stack's own PeerDb-equivalent (see SiteManager.save()'s
        own docstring): known peers fold into sites.json instead of a
        separate global content.db, so a fresh process doesn't have to
        rediscover the same swarm from nothing on every restart."""
        async def scenario():
            from libp2p.crypto.ed25519 import create_new_key_pair
            from libp2p.peer.id import ID

            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                sm1 = SiteManager(data_dir)
                site1 = sm1.add(VALID_ADDRESS, own=True)
                peer_id = ID.from_pubkey(create_new_key_pair().public_key)
                site1.addPeer(peer_id, "203.0.113.5", 15441, source="tracker")
                await sm1.save()

                sm2 = SiteManager(data_dir)
                await sm2.load()
                return sm2.sites[VALID_ADDRESS].peers, peer_id.to_base58()

        peers, peer_key = compat.run(scenario)
        assert peer_key in peers
        restored = peers[peer_key]
        assert restored.ip == "203.0.113.5"
        assert restored.port == 15441
        assert restored.reputation == 1  # tracker source's own +1 bump, preserved exactly across the restart

    def testSaveCapsPersistedPeersToHighestReputation(self):
        async def scenario():
            from P2P.SiteManager import MAX_PERSISTED_PEERS_PER_SITE
            from libp2p.crypto.ed25519 import create_new_key_pair
            from libp2p.peer.id import ID

            with tempfile.TemporaryDirectory() as d:
                data_dir = pathlib.Path(d)
                sm = SiteManager(data_dir)
                site = sm.add(VALID_ADDRESS, own=True)
                for i in range(MAX_PERSISTED_PEERS_PER_SITE + 10):
                    peer_id = ID.from_pubkey(create_new_key_pair().public_key)
                    record = site.addPeer(peer_id, "10.0.%s.%s" % (i // 256, i % 256), 1000 + i, source="local")
                    record.reputation = i  # Spread reputations so the cap picks the highest ones deterministically
                await sm.save()
                data = json.loads((data_dir / "sites.json").read_text())
                return data[VALID_ADDRESS]["peers"], MAX_PERSISTED_PEERS_PER_SITE

        persisted, cap = compat.run(scenario)
        assert len(persisted) == cap
        assert all(entry["reputation"] >= 10 for entry in persisted)  # The lowest 10 (0-9) were dropped
