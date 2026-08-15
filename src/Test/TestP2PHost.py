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

    def testDialViaRelayReachesPeerWithNoDirectConnection(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as dr, tempfile.TemporaryDirectory() as dd, \
                    tempfile.TemporaryDirectory() as dc:
                relay = Host(pathlib.Path(dr), enable_relay_hop=True)
                dest = Host(pathlib.Path(dd), enable_relay_client=True)
                dialer = Host(pathlib.Path(dc), enable_relay_client=True)
                async with relay.run(), dest.run(), dialer.run():
                    relay_info = PeerInfo(relay.peer_id, relay.get_addrs())

                    # dest reserves on the relay so it can be dialed through it.
                    await dest.connect(relay_info)
                    reserved = await dest.reserve_relay(relay_info)

                    # dialer only ever talks to the relay -- never connects
                    # to dest directly.
                    await dialer.connect(relay_info)
                    await dialer.dial_via_relay(relay_info, dest.peer_id)

                    return reserved, dest.peer_id in dialer.get_network().connections

        reserved, connected = compat.run(scenario)
        assert reserved is True
        assert connected is True

    def testDiscoverRelaysAutoReservesAndDialViaRelayFallsBack(self):
        """No explicit relay_peer_info anywhere in this test -- dest and
        dialer each connect to the relay (still a manual bootstrap step;
        discovery only scans already-connected peers), then discover it,
        which on dest's side also auto-reserves (RelayConfig.enable_client
        is already True whenever enable_relay_client=True). dial_via_relay
        falls back to whatever discover_relays() found."""
        async def scenario():
            with tempfile.TemporaryDirectory() as dr, tempfile.TemporaryDirectory() as dd, \
                    tempfile.TemporaryDirectory() as dc:
                relay = Host(pathlib.Path(dr), enable_relay_hop=True)
                dest = Host(pathlib.Path(dd), enable_relay_client=True)
                dialer = Host(pathlib.Path(dc), enable_relay_client=True)
                async with relay.run(), dest.run(), dialer.run():
                    relay_info = PeerInfo(relay.peer_id, relay.get_addrs())

                    await dest.connect(relay_info)
                    dest_relays = await dest.discover_relays()

                    await dialer.connect(relay_info)
                    dialer_relays = await dialer.discover_relays()

                    # No relay_peer_info passed -- dial_via_relay must
                    # resolve one from what discover_relays() found.
                    await dialer.dial_via_relay(None, dest.peer_id)

                    return (
                        relay.peer_id in dest_relays,
                        relay.peer_id in dialer_relays,
                        dest.relay_transport.discovery.get_relay_info(relay.peer_id).has_reservation,
                        dest.peer_id in dialer.get_network().connections,
                    )

        dest_found, dialer_found, dest_reserved, connected = compat.run(scenario)
        assert dest_found is True
        assert dialer_found is True
        assert dest_reserved is True  # Auto-reserved once discovered, no explicit reserve_relay() call
        assert connected is True

    def testEnableRelayDiscoveryRequiresRelayClient(self):
        with tempfile.TemporaryDirectory() as d:
            with pytest.raises(ValueError):
                Host(pathlib.Path(d), enable_relay_discovery=True)
