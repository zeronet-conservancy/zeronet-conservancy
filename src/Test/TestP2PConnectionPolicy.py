import pathlib
import tempfile
import time

from libp2p.peer.peerinfo import PeerInfo

from P2P.Host import Host
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.PeerSession import PeerSession
from P2P import compat


class FakeSession:
    def __init__(self, last_req_time=0.0, connected_time=0.0, bad_actions=0):
        self.last_req_time = last_req_time
        self.connected_time = connected_time
        self.bad_actions = bad_actions


class TestP2PConnectionPolicy:
    def testGetSessionCreatesAndReuses(self):
        policy = ConnectionPolicy(host=None)
        peer_id = object()
        s1 = policy.getSession(peer_id)
        s2 = policy.getSession(peer_id)
        assert s1 is s2
        assert peer_id in policy.sessions

    def testRemoveSession(self):
        policy = ConnectionPolicy(host=None)
        peer_id = object()
        policy.getSession(peer_id)
        policy.removeSession(peer_id)
        assert peer_id not in policy.sessions

    def testUpdateInternetStatusGoesOfflineThenOnline(self):
        policy = ConnectionPolicy(host=None)
        events = []
        policy.onInternetOnline = lambda: events.append("online")
        policy.onInternetOffline = lambda: events.append("offline")

        peer_id = object()
        policy.sessions[peer_id] = FakeSession(last_req_time=time.time() - 1000)
        policy.updateInternetStatus()
        assert events == ["offline"]
        assert policy.has_internet is False

        policy.sessions[peer_id].last_req_time = time.time()
        policy.updateInternetStatus()
        assert events == ["offline", "online"]
        assert policy.has_internet is True

    def testCheckMaxConnectionsClosesOldestOverCap(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as dc:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)
                host_c = Host(pathlib.Path(dc), ws_port=None)

                async with host_a.run(), host_b.run(), host_c.run():
                    await host_a.connect(PeerInfo(host_b.peer_id, host_b.get_addrs()))
                    await host_a.connect(PeerInfo(host_c.peer_id, host_c.get_addrs()))

                    policy = ConnectionPolicy(host_a, max_connections=1)
                    session_b = policy.getSession(host_b.peer_id)
                    session_c = policy.getSession(host_c.peer_id)
                    session_b.last_req_time = time.time() - 100  # older, should be closed first
                    session_c.last_req_time = time.time()

                    assert policy.liveConnectionCount() == 2
                    closed = await policy.checkMaxConnections()

                    return closed, policy.liveConnectionCount(), host_b.peer_id in policy.sessions, host_c.peer_id in policy.sessions

        closed, remaining, b_survived, c_survived = compat.run(scenario)
        assert closed == 1
        assert remaining == 1
        assert b_survived is False  # the older session got disconnected
        assert c_survived is True

    def testCheckBadActionsDisconnectsOverLimit(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db:
                host_a = Host(pathlib.Path(da), ws_port=None)
                host_b = Host(pathlib.Path(db), ws_port=None)

                async with host_a.run(), host_b.run():
                    await host_a.connect(PeerInfo(host_b.peer_id, host_b.get_addrs()))

                    policy = ConnectionPolicy(host_a)
                    session = policy.getSession(host_b.peer_id)
                    session.badAction(41)

                    closed = await policy.checkBadActions()
                    return closed, host_b.peer_id in policy.sessions

        closed, survived = compat.run(scenario)
        assert closed == 1
        assert survived is False
