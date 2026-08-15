import pathlib
import tempfile

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.ProtocolRouter import ProtocolRouter
from P2P.protocols import pex
from P2P import compat


class TestP2PPex:
    def testPexRoundTrip(self):
        received_by_a = []

        def known_peers_provider(site_address, exclude, limit):
            candidates = [
                {"ip": "1.2.3.4", "port": 1111},
                {"ip": "5.6.7.8", "port": 2222},
            ]
            return [p for p in candidates if (p["ip"], p["port"]) not in exclude][:limit]

        def peer_received_callback(site_address, ip, port):
            received_by_a.append((site_address, ip, port))

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)

                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(pex.PROTOCOL_ID, pex.make_handler(known_peers_provider, peer_received_callback))

                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    my_peers = [{"ip": "9.9.9.9", "port": 3333}]
                    back_peers = await pex.request(host_b, host_a.peer_id, "1TestSiteAddress", my_peers, need_num=5)
                    return back_peers

        back_peers = compat.run(scenario)
        assert back_peers == [{"ip": "1.2.3.4", "port": 1111}, {"ip": "5.6.7.8", "port": 2222}]
        assert received_by_a == [("1TestSiteAddress", "9.9.9.9", 3333)]

    def testExcludesPeersAlreadySentByRequester(self):
        def known_peers_provider(site_address, exclude, limit):
            candidates = [{"ip": "1.2.3.4", "port": 1111}, {"ip": "5.6.7.8", "port": 2222}]
            return [p for p in candidates if (p["ip"], p["port"]) not in exclude][:limit]

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                router_a = ProtocolRouter(host_a)

                async with host_a.run(), host_b.run():
                    router_a.register(pex.PROTOCOL_ID, pex.make_handler(known_peers_provider, lambda *a: None))
                    await host_b.connect(PeerInfo(host_a.peer_id, host_a.get_addrs()))

                    # Requester already knows about 1.2.3.4:1111 -- shouldn't get it back
                    my_peers = [{"ip": "1.2.3.4", "port": 1111}]
                    return await pex.request(host_b, host_a.peer_id, "1TestSiteAddress", my_peers)

        back_peers = compat.run(scenario)
        assert back_peers == [{"ip": "5.6.7.8", "port": 2222}]
