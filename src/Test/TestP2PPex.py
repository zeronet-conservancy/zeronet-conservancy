import pathlib
import tempfile

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.ProtocolRouter import ProtocolRouter
from P2P.protocols import pex
from P2P import compat


def _random_peer_id_str() -> str:
    return ID.from_pubkey(create_new_key_pair().public_key).to_base58()


class TestP2PPex:
    def testPexRoundTrip(self):
        received_by_a = []
        candidate_id_1 = _random_peer_id_str()
        candidate_id_2 = _random_peer_id_str()
        requester_id = _random_peer_id_str()

        def known_peers_provider(site_address, exclude, limit):
            candidates = [
                {"peer_id": candidate_id_1, "ip": "1.2.3.4", "port": 1111},
                {"peer_id": candidate_id_2, "ip": "5.6.7.8", "port": 2222},
            ]
            return [p for p in candidates if ID.from_base58(p["peer_id"]) not in exclude][:limit]

        def peer_received_callback(site_address, peer_id, ip, port):
            received_by_a.append((site_address, peer_id.to_base58(), ip, port))

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)

                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(pex.PROTOCOL_ID, pex.make_handler(known_peers_provider, peer_received_callback))

                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    my_peers = [{"peer_id": requester_id, "ip": "9.9.9.9", "port": 3333}]
                    back_peers = await pex.request(host_b, host_a.peer_id, "1TestSiteAddress", my_peers, need_num=5)
                    return back_peers

        back_peers = compat.run(scenario)
        assert back_peers == [
            {"peer_id": candidate_id_1, "ip": "1.2.3.4", "port": 1111},
            {"peer_id": candidate_id_2, "ip": "5.6.7.8", "port": 2222},
        ]
        assert received_by_a == [("1TestSiteAddress", requester_id, "9.9.9.9", 3333)]

    def testExcludesPeersAlreadySentByRequester(self):
        candidate_id_1 = _random_peer_id_str()
        candidate_id_2 = _random_peer_id_str()

        def known_peers_provider(site_address, exclude, limit):
            candidates = [
                {"peer_id": candidate_id_1, "ip": "1.2.3.4", "port": 1111},
                {"peer_id": candidate_id_2, "ip": "5.6.7.8", "port": 2222},
            ]
            return [p for p in candidates if ID.from_base58(p["peer_id"]) not in exclude][:5]

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(pex.PROTOCOL_ID, pex.make_handler(known_peers_provider, lambda *a: None))
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    # Requester already knows about candidate_id_1 -- shouldn't get it back
                    my_peers = [{"peer_id": candidate_id_1, "ip": "1.2.3.4", "port": 1111}]
                    return await pex.request(host_b, host_a.peer_id, "1TestSiteAddress", my_peers)

        back_peers = compat.run(scenario)
        assert back_peers == [{"peer_id": candidate_id_2, "ip": "5.6.7.8", "port": 2222}]

    def testUnparseablePeerIdIsSkippedNotFatal(self):
        received = []

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(
                        pex.PROTOCOL_ID,
                        pex.make_handler(lambda *a: [], lambda site, pid, ip, port: received.append(ip)),
                    )
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    my_peers = [{"peer_id": "not-a-valid-peer-id", "ip": "1.1.1.1", "port": 1}]
                    return await pex.request(host_b, host_a.peer_id, "1Site", my_peers)

        back_peers = compat.run(scenario)
        assert back_peers == []
        assert received == []  # unparseable entry was skipped, not passed through
