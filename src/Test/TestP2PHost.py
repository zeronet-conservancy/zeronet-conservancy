import tempfile
import pathlib

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P import compat


class TestP2PHost:
    """Phase 1 milestone: two libp2p hosts complete a Noise handshake over TCP.

    Runs via P2P.compat.run() rather than a gevent bridge -- the P2P stack
    (and the rest of the app, eventually) runs directly under trio; see the
    libp2p migration plan's gevent-removal decision.
    """

    def testHandshake(self):
        async def handshake():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da))
                host_b = Host(pathlib.Path(db))
                async with host_a.run(), host_b.run():
                    addrs_a = host_a.get_addrs()
                    await host_b.connect(PeerInfo(host_a.peer_id, addrs_a))
                    return host_a.peer_id in host_b.get_network().connections

        result = compat.run(handshake)
        assert result is True
