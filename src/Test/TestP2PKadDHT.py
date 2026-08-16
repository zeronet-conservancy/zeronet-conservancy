import hashlib
import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.discovery.kaddht import KadDHTDiscovery
from P2P import compat


class TestP2PKadDHT:
    """Phase 5 milestone: a site announced by node A on kad-dht is found by
    node B via find_peers(), replacing DHTServer.py + aiobtdht entirely.
    """

    def testAnnounceAndFindPeers(self):
        site_hash = hashlib.sha1(b"1TestSiteAddress").digest()

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    dht_a = KadDHTDiscovery(host_a)
                    dht_b = KadDHTDiscovery(host_b)

                    async with dht_a.run(), dht_b.run():
                        await dht_b.add_peer(host_a.peer_id)

                        await dht_a.announce(site_hash)
                        peers = await dht_b.find_peers(site_hash)
                        return [p.peer_id for p in peers]

        peer_ids = compat.run(scenario)
        # host_a's peer_id is only known to us via the test scope, so just
        # assert something was found -- the identity check happens below
        # in a second scenario that returns both.
        assert len(peer_ids) >= 1

    def testProviderIsTheAnnouncingHost(self):
        site_hash = hashlib.sha1(b"1AnotherTestSite").digest()

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)

                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    dht_a = KadDHTDiscovery(host_a)
                    dht_b = KadDHTDiscovery(host_b)

                    async with dht_a.run(), dht_b.run():
                        await dht_b.add_peer(host_a.peer_id)
                        await dht_a.announce(site_hash)
                        peers = await dht_b.find_peers(site_hash)
                        return host_a.peer_id, [p.peer_id for p in peers]

        host_a_id, found_ids = compat.run(scenario)
        assert host_a_id in found_ids

    def testIdentityAnnouncementUsesOpaqueZeroNetKey(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                async with host_a.run(), host_b.run():
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))
                    dht_a = KadDHTDiscovery(host_a, protocol_prefix="/zeronet-test-identity")
                    dht_b = KadDHTDiscovery(host_b, protocol_prefix="/zeronet-test-identity")
                    async with dht_a.run(), dht_b.run():
                        await dht_b.add_peer(host_a.peer_id)
                        key = await dht_a.announce_identity("zeronet.local", "web", "alice")
                        peers = await dht_b.find_identity_providers("zeronet.local", "web", "alice")
                        return key, [peer.peer_id for peer in peers]

        key, peers = compat.run(scenario)
        assert len(key) == 32
        assert all(len(peer.to_bytes()) > 0 for peer in peers)
        assert KadDHTDiscovery.identity_key("zeronet.local", "web", "alice") == key
        assert KadDHTDiscovery.identity_key("zeronet.local", "web", "bob") != key
