"""Replaces ConnectionServer.py's pool tracking + application-level policy.

libp2p's own Swarm/Peerstore already tracks live connections per peer_id
and handles reuse/dialing -- ConnectionServer.getConnection()/
removeConnection()'s pool bookkeeping is mostly redundant now. What's kept
is the policy on top that libp2p doesn't know about: a PeerSession
registry (PeerSessions carry reputation/timing state libp2p has no concept
of), max-connections enforcement, idle eviction, and bad-peer scoring --
ported from ConnectionServer.checkConnections()/checkMaxConnections(),
simplified since there's no more unpacker/incomplete-buffer/handshake-state
tracking to sweep (libp2p owns all of that internally now).
"""
import time

import trio

from .PeerSession import PeerSession

IDLE_TIMEOUT = 20 * 60  # 20 min, no requests sent
BAD_ACTIONS_LIMIT = 40
CHECK_INTERVAL = 15


class ConnectionPolicy:
    def __init__(self, host, max_connections: int = 512):
        self.host = host
        self.max_connections = max_connections
        self.sessions: dict = {}  # peer_id -> PeerSession
        self.has_internet = True

    def getSession(self, peer_id) -> PeerSession:
        session = self.sessions.get(peer_id)
        if session is None:
            session = PeerSession(self.host, peer_id)
            self.sessions[peer_id] = session
        return session

    def removeSession(self, peer_id) -> None:
        self.sessions.pop(peer_id, None)

    def liveConnectionCount(self) -> int:
        return len(self.host.get_network().connections)

    async def checkBadActions(self) -> int:
        """Disconnect any peer whose reputation has gone bad enough."""
        closed = 0
        for peer_id, session in list(self.sessions.items()):
            if session.bad_actions > BAD_ACTIONS_LIMIT:
                await self.host.raw.disconnect(peer_id)
                self.removeSession(peer_id)
                closed += 1
        return closed

    async def checkIdle(self, idle_timeout: float = IDLE_TIMEOUT) -> int:
        """Disconnect sessions that haven't been used in a while."""
        closed = 0
        now = time.time()
        for peer_id, session in list(self.sessions.items()):
            reference_time = session.last_req_time or session.connected_time
            if now - reference_time > idle_timeout:
                if not await session.ping():
                    await self.host.raw.disconnect(peer_id)
                    self.removeSession(peer_id)
                    closed += 1
        return closed

    async def checkMaxConnections(self) -> int:
        """Close the least-recently-used sessions once over the cap."""
        connections = self.host.get_network().connections
        if len(connections) <= self.max_connections:
            return 0

        candidates = sorted(
            (session for peer_id, session in self.sessions.items() if peer_id in connections),
            key=lambda s: s.last_req_time or s.connected_time,
        )
        num_to_close = len(connections) - self.max_connections
        closed = 0
        for session in candidates[:num_to_close]:
            await self.host.raw.disconnect(session.peer_id)
            self.removeSession(session.peer_id)
            closed += 1
        return closed

    def updateInternetStatus(self) -> None:
        if not self.sessions:
            return
        last_activity = max((s.last_req_time for s in self.sessions.values()), default=0)
        if last_activity == 0:
            return
        offline_threshold = max(60, 60 * 10 / max(1, len(self.sessions) / 50))
        is_online = (time.time() - last_activity) <= offline_threshold

        if is_online and not self.has_internet:
            self.has_internet = True
            self.onInternetOnline()
        elif not is_online and self.has_internet:
            self.has_internet = False
            self.onInternetOffline()

    def onInternetOnline(self) -> None:
        pass

    def onInternetOffline(self) -> None:
        pass

    async def runChecks(self, *, interval: float = CHECK_INTERVAL) -> None:
        """Periodic sweep -- spawn via TaskManager.spawn(policy.runChecks)."""
        while True:
            await trio.sleep(interval)
            await self.checkBadActions()
            await self.checkIdle()
            await self.checkMaxConnections()
            self.updateInternetStatus()
