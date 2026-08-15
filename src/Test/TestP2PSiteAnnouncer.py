import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from P2P.FileServer import FileServer
from P2P.Site import Site
from P2P.SiteAnnouncer import SiteAnnouncer
from P2P.discovery.kaddht import KadDHTDiscovery
from P2P import compat


class TestP2PSiteAnnouncer:
    def testAnnounceDHTDiscoversRealPeer(self):
        site_address = "1TestSiteForDHT"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_b = FileServer(pathlib.Path(db), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                site_b = Site(site_address, pathlib.Path(root_b))
                server_a.addSite(site_a)
                server_b.addSite(site_b)

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))

                    dht_a = KadDHTDiscovery(server_a.host, protocol_prefix="/zeronet-test-announcer")
                    dht_b = KadDHTDiscovery(server_b.host, protocol_prefix="/zeronet-test-announcer")

                    async with dht_a.run(), dht_b.run():
                        await dht_b.add_peer(server_a.host.peer_id)

                        announcer_a = SiteAnnouncer(site_a, server_a, dht_discovery=dht_a)
                        announcer_b = SiteAnnouncer(site_b, server_b, dht_discovery=dht_b)

                        await announcer_a.announceDHT()
                        await announcer_b.announceDHT()

                        return list(site_b.peers.keys()), server_a.host.peer_id.to_base58()

        peer_keys, host_a_id = compat.run(scenario)
        assert host_a_id in peer_keys

    def testAnnounceDHTDoesNotAddSelf(self):
        site_address = "1TestSiteSelf"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as root_a:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                server_a.addSite(site_a)

                async with server_a.run():
                    dht_a = KadDHTDiscovery(server_a.host, protocol_prefix="/zeronet-test-self")
                    async with dht_a.run():
                        announcer_a = SiteAnnouncer(site_a, server_a, dht_discovery=dht_a)
                        await announcer_a.announceDHT()
                        return dict(site_a.peers)

        peers = compat.run(scenario)
        assert peers == {}  # only found itself, which should be filtered out

    def testAnnouncePexAddsPeersFromExchange(self):
        site_address = "1TestSitePex"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_b = FileServer(pathlib.Path(db), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                site_b = Site(site_address, pathlib.Path(root_b))
                server_a.addSite(site_a)
                server_b.addSite(site_b)

                # Seed A's site with a peer it knows about (that B doesn't).
                from libp2p.crypto.ed25519 import create_new_key_pair
                from libp2p.peer.id import ID
                known_peer_id = ID.from_pubkey(create_new_key_pair().public_key)
                site_a.addPeer(known_peer_id, "5.5.5.5", 5555, source="tracker")

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    # B needs to know about A as a queryable peer for pex to have someone to ask.
                    site_b.addPeer(server_a.host.peer_id, "127.0.0.1", 1, source="other")

                    announcer_b = SiteAnnouncer(site_b, server_b)
                    added = await announcer_b.announcePex()

                    return added, known_peer_id.to_base58() in site_b.peers

        added, got_known_peer = compat.run(scenario)
        assert added >= 1
        assert got_known_peer is True

    def testAnnounceTrackerSkipsWithoutHandler(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as root_a:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site("1TestSiteTracker", pathlib.Path(root_a))
                announcer = SiteAnnouncer(site_a, server_a)
                return await announcer.announceTracker("http://example.com:80")

        assert compat.run(scenario) is None  # skipped, not an error -- core has no handler

    def testAnnounceThrottlesWithoutForce(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as root_a:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site("1TestSiteThrottle", pathlib.Path(root_a))
                announcer = SiteAnnouncer(site_a, server_a)

                await announcer.announce(mode="start", pex=False)
                first_time = announcer.time_last_announce
                await announcer.announce(mode="start", pex=False)  # too soon, should be a no-op
                second_time = announcer.time_last_announce

                await announcer.announce(mode="start", pex=False, force=True)
                third_time = announcer.time_last_announce

                return first_time, second_time, third_time

        first, second, third = compat.run(scenario)
        assert first == second  # throttled -- didn't update time_last_announce
        assert third > second  # force=True bypassed the throttle
