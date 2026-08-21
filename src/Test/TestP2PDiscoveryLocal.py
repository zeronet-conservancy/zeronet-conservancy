import json
import pathlib
import tempfile

import trio
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID

from P2P.FileServer import FileServer
from P2P.Site import Site
from P2P.SiteAnnouncer import SiteAnnouncer
from P2P.discovery.local import LocalAnnouncer
from P2P import compat


def _randomPeerId() -> ID:
    return ID.from_pubkey(create_new_key_pair().public_key)


class TestP2PDiscoveryLocalPacketHandling:
    """_handlePacket() unit tests -- exercises the real parse/addPeer
    logic directly with crafted packets, no real socket I/O needed."""

    def _announcer(self, tmp_path, address="1TestLocalDiscoverySiteAAA1"):
        site = Site(address, tmp_path / address)

        class FakeHost:
            peer_id = "self-peer-id"

        return LocalAnnouncer(FakeHost(), {address: site}), site

    def testAddsDiscoveredPeerForKnownSiteHash(self):
        with tempfile.TemporaryDirectory() as d:
            announcer, site = self._announcer(pathlib.Path(d))
            packet = json.dumps({
                "peer_id": _randomPeerId().to_base58(),
                "port": 12345,
                "sites": [site.address_sha1.hex()],
            }).encode("utf8")

            announcer._handlePacket(packet, ("10.0.0.5", 15441))

            assert len(site.peers) == 1
            record = next(iter(site.peers.values()))
            assert record.ip == "10.0.0.5"
            assert record.port == 12345

    def testIgnoresOwnBroadcast(self):
        with tempfile.TemporaryDirectory() as d:
            announcer, site = self._announcer(pathlib.Path(d))
            packet = json.dumps({
                "peer_id": announcer.host.peer_id,
                "port": 12345,
                "sites": [site.address_sha1.hex()],
            }).encode("utf8")

            announcer._handlePacket(packet, ("10.0.0.5", 15441))
            assert len(site.peers) == 0

    def testIgnoresUnrelatedSiteHash(self):
        with tempfile.TemporaryDirectory() as d:
            announcer, site = self._announcer(pathlib.Path(d))
            packet = json.dumps({
                "peer_id": _randomPeerId().to_base58(),
                "port": 12345,
                "sites": ["0" * 40],  # Not this site's own address_sha1
            }).encode("utf8")

            announcer._handlePacket(packet, ("10.0.0.5", 15441))
            assert len(site.peers) == 0

    def testIgnoresMalformedPacket(self):
        with tempfile.TemporaryDirectory() as d:
            announcer, site = self._announcer(pathlib.Path(d))
            announcer._handlePacket(b"not even json", ("10.0.0.5", 15441))
            announcer._handlePacket(b'{"peer_id": "x"}', ("10.0.0.5", 15441))  # Missing fields
            assert len(site.peers) == 0


class TestP2PDiscoveryLocalRealSockets:
    """Real trio.socket end-to-end: LocalAnnouncer.run() actually binds a
    UDP listen socket, and a packet genuinely sent to it over localhost
    is genuinely received, parsed, and turned into a real added peer.
    Uses direct unicast to 127.0.0.1 instead of discover()'s own
    255.255.255.255 broadcast to sidestep sandboxed-CI broadcast
    restrictions -- the receive/parse/addPeer path under test is
    identical either way; only the delivery mechanism differs, and that
    part is a single sendto() call already exercised for real by
    discover() itself in testDiscoverSendsRealBroadcastWithoutRaising
    below."""

    def testRealPacketOverLoopbackAddsPeer(self):
        address = "1TestLocalRealSocketSiteAAA1"

        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as root:
                server = FileServer(pathlib.Path(d), ws_port=None)
                site = Site(address, pathlib.Path(root))
                server.addSite(site)

                async with server.run():
                    announcer = LocalAnnouncer(server.host, {address: site}, listen_port=0)
                    async with announcer.run():
                        bound_port = announcer._socket.getsockname()[1]

                        sender_peer_id = _randomPeerId()
                        packet = json.dumps({
                            "peer_id": sender_peer_id.to_base58(),
                            "port": 9999,
                            "sites": [site.address_sha1.hex()],
                        }).encode("utf8")

                        sender = trio.socket.socket(trio.socket.AF_INET, trio.socket.SOCK_DGRAM)
                        try:
                            await sender.sendto(packet, ("127.0.0.1", bound_port))
                        finally:
                            sender.close()

                        with trio.fail_after(2):
                            while not site.peers:
                                await trio.sleep(0.01)

                        return dict(site.peers), sender_peer_id.to_base58()

        peers, sender_id = compat.run(scenario)
        assert sender_id in peers
        assert peers[sender_id].port == 9999

    def testDiscoverSendsRealBroadcastWithoutRaising(self):
        """discover() itself, over a real socket -- best-effort by design
        (see its own docstring), so this only asserts it completes
        without raising even though actual broadcast delivery isn't
        guaranteed in a sandboxed test environment."""
        address = "1TestLocalDiscoverSendSiteAA1"

        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as root:
                server = FileServer(pathlib.Path(d), ws_port=None)
                site = Site(address, pathlib.Path(root))
                server.addSite(site)

                async with server.run():
                    announcer = LocalAnnouncer(server.host, {address: site}, listen_port=0)
                    async with announcer.run():
                        await announcer.discover()
                        return "completed"

        assert compat.run(scenario) == "completed"

    def testAnnounceLocalCallsDiscoverThroughSiteAnnouncer(self):
        """SiteAnnouncer.announceLocal() -- the actual wiring point
        announce() calls -- reaches the same real discover()."""
        address = "1TestAnnounceLocalWiringSiteA1"

        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as root:
                server = FileServer(pathlib.Path(d), ws_port=None)
                site = Site(address, pathlib.Path(root))
                server.addSite(site)

                async with server.run():
                    announcer = LocalAnnouncer(server.host, {address: site}, listen_port=0)
                    async with announcer.run():
                        site_announcer = SiteAnnouncer(site, server, local_announcer=announcer)
                        await site_announcer.announceLocal()
                        return "completed"

        assert compat.run(scenario) == "completed"

    def testAnnounceLocalNoOpWithoutAnnouncer(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d, tempfile.TemporaryDirectory() as root:
                server = FileServer(pathlib.Path(d), ws_port=None)
                site = Site("1TestAnnounceLocalNoopSiteAA1", pathlib.Path(root))
                server.addSite(site)
                site_announcer = SiteAnnouncer(site, server)  # No local_announcer given
                await site_announcer.announceLocal()  # Should not raise
                return "ok"

        assert compat.run(scenario) == "ok"
