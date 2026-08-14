import tempfile
import pathlib

import gevent

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.geventtrio import TrioLoop


class TestP2PHost:
    """Phase 1 milestone: two libp2p hosts complete a Noise handshake over
    TCP, driven from gevent-land through the trio bridge -- proving the
    trio-run P2P stack and the gevent/Site side of the codebase can actually
    talk to each other before Phase 2 builds real protocol handlers on top.
    """

    def testHandshakeThroughGeventBridge(self):
        loop = TrioLoop()
        loop.start()

        async def handshake():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da))
                host_b = Host(pathlib.Path(db))
                async with host_a.run(), host_b.run():
                    addrs_a = host_a.get_addrs()
                    await host_b.connect(PeerInfo(host_a.peer_id, addrs_a))
                    return host_a.peer_id in host_b.get_network().connections

        results = []

        def worker():
            results.append(loop.run(handshake))

        greenlet = gevent.spawn(worker)
        gevent.joinall([greenlet])

        assert results == [True]
