import tempfile
import pathlib

import pytest
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2 import PROTOCOL_ID as RELAY_HOP_PROTOCOL_ID

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

    def testRelayHopDisabledByDefault(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                relay = Host(pathlib.Path(da))
                client = Host(pathlib.Path(db))
                async with relay.run(), client.run():
                    assert relay.relay_protocol is None
                    await client.connect(PeerInfo(relay.peer_id, relay.get_addrs()))
                    with pytest.raises(Exception):
                        await client.raw.new_stream(relay.peer_id, [RELAY_HOP_PROTOCOL_ID])

        compat.run(scenario)

    def testRelayHopAcceptsStreamsWhenEnabled(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                relay = Host(pathlib.Path(da), enable_relay_hop=True)
                client = Host(pathlib.Path(db))
                async with relay.run(), client.run():
                    assert relay.relay_protocol is not None
                    await client.connect(PeerInfo(relay.peer_id, relay.get_addrs()))
                    stream = await client.raw.new_stream(relay.peer_id, [RELAY_HOP_PROTOCOL_ID])
                    negotiated = stream.get_protocol()
                    await stream.close()
                    return negotiated

        negotiated = compat.run(scenario)
        assert negotiated == RELAY_HOP_PROTOCOL_ID
