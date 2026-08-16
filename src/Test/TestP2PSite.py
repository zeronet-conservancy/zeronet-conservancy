import pathlib

import pytest
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID

from P2P import compat
from P2P.Site import Site
from P2P.WorkerManager import NoPeerHadFileError


def _random_peer_id() -> ID:
    return ID.from_pubkey(create_new_key_pair().public_key)


class TestP2PSite:
    def testAddPeerCreatesRecord(self):
        site = Site("1Test", pathlib.Path("/tmp/x"))
        peer_id = _random_peer_id()
        record = site.addPeer(peer_id, "1.2.3.4", 1234, source="tracker")
        assert record.peer_id == peer_id
        assert record.ip == "1.2.3.4"
        assert record.reputation == 1  # tracker source
        assert site.peers[peer_id.to_base58()] is record

    def testAddPeerRejectsZeroIp(self):
        site = Site("1Test", pathlib.Path("/tmp/x"))
        assert site.addPeer(_random_peer_id(), "0.0.0.0", 1234) is False
        assert site.addPeer(_random_peer_id(), "", 1234) is False

    def testAddPeerAgainUpdatesReputationNotDuplicate(self):
        site = Site("1Test", pathlib.Path("/tmp/x"))
        peer_id = _random_peer_id()
        r1 = site.addPeer(peer_id, "1.2.3.4", 1234, source="local")
        r2 = site.addPeer(peer_id, "1.2.3.4", 1234, source="local")
        assert r1 is r2
        assert len(site.peers) == 1
        # "local" source only bumps reputation while it's still under 5, so
        # the first call gives +20 and the second call (already >= 5) is a no-op.
        assert r1.reputation == 20

    def testAddPeerBlacklisted(self):
        site = Site("1Test", pathlib.Path("/tmp/x"))
        peer_id = _random_peer_id()
        site.peer_blacklist.add(peer_id.to_base58())
        assert site.addPeer(peer_id, "1.2.3.4", 1234) is False
        assert len(site.peers) == 0

    def testGetConnectablePeersSortedByReputation(self):
        site = Site("1Test", pathlib.Path("/tmp/x"))
        low = _random_peer_id()
        high = _random_peer_id()
        site.addPeer(low, "1.1.1.1", 1, source="other")
        site.addPeer(high, "2.2.2.2", 2, source="local")  # higher reputation

        result = site.getConnectablePeers(need_num=5)
        assert [p.peer_id for p in result] == [high, low]

    def testGetConnectablePeersRespectsExcludeAndLimit(self):
        site = Site("1Test", pathlib.Path("/tmp/x"))
        ids = [_random_peer_id() for _ in range(3)]
        for i, pid in enumerate(ids):
            site.addPeer(pid, "1.1.1.%s" % i, 1000 + i)

        result = site.getConnectablePeers(need_num=1, exclude={ids[0]})
        assert len(result) == 1
        assert result[0].peer_id != ids[0]

    def testIsServing(self):
        assert Site("1Test", pathlib.Path("/tmp/x"), serving=True).isServing() is True
        assert Site("1Test", pathlib.Path("/tmp/x"), serving=False).isServing() is False

    def testNeedFileDelegatesToScheduler(self):
        """Baseline, no-plugin regression check for the new needFile()
        wrapper: an empty peers list can't succeed, so the real Scheduler
        underneath raises its own NoPeerHadFileError -- proving this
        actually reaches WorkerManager.Scheduler, not just returning
        early or swallowing the call. See TestP2PPluginsContentFilter.py
        for the plugin-override version of this same call."""
        async def scenario():
            site = Site("1Test", pathlib.Path("/tmp/x"))
            with pytest.raises(NoPeerHadFileError):
                await site.needFile("data.json", [])

        compat.run(scenario)

    def testRestorePeerSetsReputationDirectlyWithoutBump(self):
        """Unlike addPeer()'s found()-bump semantics, restorePeer() sets
        reputation exactly to what's given -- SiteManager.load()'s own
        sites.json-based peer persistence relies on this to bring back a
        peer's earned reputation across a restart unchanged, not treat
        rediscovery as a fresh find."""
        site = Site("1Test", pathlib.Path("/tmp/x"))
        peer_id = _random_peer_id()
        record = site.restorePeer(peer_id, "1.2.3.4", 1234, reputation=42)
        assert record.reputation == 42
        assert site.peers[peer_id.to_base58()] is record

    def testRestorePeerIgnoresBlacklist(self):
        """A straight restore of what was already on disk isn't a new
        trust decision -- addPeer() rejects a blacklisted peer_id, but
        restorePeer() (only ever called from SiteManager.load(), never
        from live network discovery) doesn't."""
        site = Site("1Test", pathlib.Path("/tmp/x"))
        peer_id = _random_peer_id()
        site.peer_blacklist.add(peer_id.to_base58())
        record = site.restorePeer(peer_id, "1.2.3.4", 1234, reputation=5)
        assert record is not None
        assert record.reputation == 5
