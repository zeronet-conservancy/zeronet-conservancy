import pathlib
import tempfile

import trio
from libp2p.peer.peerinfo import PeerInfo

from Crypt import CryptBitcoin
from P2P.FileServer import FileServer
from P2P.Site import Site
from P2P.WorkerManager import publishGossip
from P2P import compat


class TestP2PGossipIntegration:
    """Real end-to-end proof that gossipsub propagation actually works,
    independent of the unicast update.py RPC path: two full FileServer/
    GossipManager pairs, connected, both subscribed to the same site's
    topic (App._wireSite()'s real wiring, exercised directly here since
    there's no App instance in this test), and a publishGossip() call on
    one side with *no* unicast push anywhere in the scenario."""

    def testGossipOnlyPropagationBetweenTwoNodes(self):
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                site_a = Site(address, pathlib.Path(root_a))
                await site_a.content_manager.sign(privatekey)

                site_b = Site(address, pathlib.Path(root_b))

                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(site_a)
                server_b = FileServer(pathlib.Path(db), ws_port=None)
                server_b.addSite(site_b)

                async with server_a.run(), server_a.gossip.run(), \
                        server_b.run(), server_b.gossip.run():
                    await server_b.host.connect(
                        PeerInfo(server_a.host.peer_id, server_a.host.get_addrs())
                    )
                    server_a.gossip.subscribeSite(site_a)
                    server_b.gossip.subscribeSite(site_b)

                    # Let gossipsub's mesh actually form (join()'s
                    # immediate graft attempt, then a heartbeat or two --
                    # see GossipManager.HEARTBEAT_INTERVAL's own comment on
                    # why this needs to happen well inside a few seconds,
                    # not the library's 120s default) before publishing.
                    with trio.fail_after(15):
                        while not server_a.gossip._gossipsub.mesh.get(
                            server_a.gossip.topicFor(address)
                        ):
                            await trio.sleep(0.1)

                    await publishGossip(site_a, server_a.gossip)

                    with trio.fail_after(10):
                        while "content.json" not in site_b.content_manager.contents:
                            await trio.sleep(0.1)

                    on_disk = await site_b.storage.loadJson("content.json")
                    return site_b.content_manager.contents["content.json"], on_disk

        received, on_disk = compat.run(scenario)
        assert received["address"] == address
        assert on_disk == received

    def testGossipDoesNotDeliverToUnsubscribedSite(self):
        """A site that was never subscribeSite()'d (e.g. not loaded on
        this node) must not receive updates -- proves topic isolation,
        not just "messages arrive somehow"."""
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        other_privatekey = CryptBitcoin.newPrivatekey()
        other_address = CryptBitcoin.privatekeyToAddress(other_privatekey)

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                site_a = Site(address, pathlib.Path(root_a))
                await site_a.content_manager.sign(privatekey)

                # site_b is a DIFFERENT site (different address) -- never
                # subscribed to `address`'s topic at all.
                site_b = Site(other_address, pathlib.Path(root_b))

                server_a = FileServer(pathlib.Path(da), ws_port=None)
                server_a.addSite(site_a)
                server_b = FileServer(pathlib.Path(db), ws_port=None)
                server_b.addSite(site_b)

                async with server_a.run(), server_a.gossip.run(), \
                        server_b.run(), server_b.gossip.run():
                    await server_b.host.connect(
                        PeerInfo(server_a.host.peer_id, server_a.host.get_addrs())
                    )
                    server_a.gossip.subscribeSite(site_a)
                    # server_b never subscribes to anything.

                    await trio.sleep(1.5)
                    await publishGossip(site_a, server_a.gossip)
                    await trio.sleep(1.0)

                    return "content.json" in site_b.content_manager.contents

        received_unsubscribed = compat.run(scenario)
        assert received_unsubscribed is False
