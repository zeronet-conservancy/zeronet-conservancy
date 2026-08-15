"""Trio port of Site/SiteAnnouncer.py, wired against real components now
that Site/Peer/FileServer/discovery all exist.

getTrackerHandler() returns None here just like the original core class:
actual HTTP/UDP tracker protocols are a plugin extension point in
zeronet-conservancy (AnnounceShare/AnnounceBitTorrent etc. supply real
handlers), not part of the core class itself. So the tracker side of
announce() is structurally present (matching the original's own
architecture, and reusing discovery/tracker.py's TrackerStats/
getAddressParts from Phase 5) but a no-op until something registers a
handler -- exactly like upstream with no plugins loaded. The working,
built-in discovery paths are DHT (discovery/kaddht.py) and peer exchange
(protocols/pex.py) -- both real here, not stubs.

@acceptPlugins (Phase 8) marks this as the real plugin extension point
that docstring paragraph above describes -- AnnounceShare/
AnnounceBitTorrent-equivalent plugins can now actually attach via
P2P.PluginManager.registerTo("SiteAnnouncer") once ported. Safe, no-op
change on its own: with no plugins registered (the default today, since
no plugin has been ported against this package yet), @acceptPlugins
returns this class completely unchanged -- see PluginManager.py's own
docstring for the ordering requirement (registerTo() has to run before
this class is imported/decorated) that porting individual plugins will
need to satisfy.
"""
import random
import time

from libp2p.peer.id import ID

from .Peer import Peer
from .PluginManager import acceptPlugins
from .discovery.tracker import TrackerStats, getAddressParts, global_tracker_stats


class AnnounceError(Exception):
    pass


@acceptPlugins
class SiteAnnouncer:
    def __init__(self, site, file_server, dht_discovery=None):
        self.site = site
        self.file_server = file_server
        self.dht_discovery = dht_discovery
        self.stats = TrackerStats()
        self.time_last_announce = 0.0

    def getTrackers(self) -> list:
        return []  # No trackers by default in core -- config/plugin extension point

    def getTrackerHandler(self, protocol):
        return None  # No built-in tracker protocol handler in core -- plugin extension point

    async def announceTracker(self, tracker: str, mode: str = "start", num_want: int = 10):
        """Returns False on error, None if skipped, else the time taken --
        same contract as the original. Always skips in core (no handler
        registered) unless something has set getTrackerHandler up."""
        address_parts = getAddressParts(tracker)
        if not address_parts:
            self.stats.recordError(tracker, AnnounceError("Invalid address"))
            return False

        if not global_tracker_stats.isReliable(tracker):
            return None

        self.stats.recordRequest(tracker)
        global_tracker_stats.recordRequest(tracker)

        handler = self.getTrackerHandler(address_parts["protocol"])
        if handler is None:
            self.stats.recordSkipped(tracker, "")
            return None

        s = time.time()
        try:
            peers = await handler(address_parts["address"], mode=mode, num_want=num_want)
        except Exception as err:
            self.stats.recordError(tracker, err)
            global_tracker_stats.recordError(tracker, err)
            return False

        self.stats.recordSuccess(tracker)
        global_tracker_stats.recordSuccess(tracker)

        for peer in peers or []:
            self.site.addPeer(peer["peer_id"], peer.get("ip"), peer.get("port"), source="tracker")
        return time.time() - s

    async def announceDHT(self) -> None:
        if self.dht_discovery is None:
            return
        await self.dht_discovery.announce(self.site.address_sha1)
        self.onDhtPeers(await self.dht_discovery.find_peers(self.site.address_sha1))

    def onDhtPeers(self, peer_infos: list) -> None:
        my_peer_id = self.file_server.host.peer_id if self.file_server else None
        for peer_info in peer_infos:
            if peer_info.peer_id == my_peer_id:
                continue
            self.site.addPeer(peer_info.peer_id, source="dht")

    async def announcePex(self, query_num: int = 2, need_num: int = 5) -> int:
        candidates = self.site.getConnectablePeers(query_num * 3)
        if not candidates:
            return 0
        random.shuffle(candidates)

        my_peers = [
            {"peer_id": record.peer_id.to_base58(), "ip": record.ip, "port": record.port}
            for record in self.site.getConnectablePeers(5)
            if record.ip
        ]

        done = 0
        total_added = 0
        for record in candidates:
            peer = Peer(record.peer_id, self.file_server.host, self.file_server.connection_policy)
            try:
                back_peers = await peer.pex(self.site.address, my_peers, need_num)
            except Exception:
                continue
            done += 1

            for back_peer in back_peers:
                try:
                    peer_id = ID.from_base58(back_peer["peer_id"])
                except Exception:
                    continue
                if self.site.addPeer(peer_id, back_peer.get("ip"), back_peer.get("port"), source="pex"):
                    total_added += 1

            if done >= query_num:
                break
        return total_added

    async def announce(self, force: bool = False, mode: str = "start", pex: bool = True) -> None:
        if time.time() - self.time_last_announce < 30 and not force:
            return
        self.time_last_announce = time.time()

        for tracker in self.getTrackers():
            await self.announceTracker(tracker, mode=mode)

        await self.announceDHT()

        if pex:
            await self.announcePex()
