"""Tracker discovery helpers, ported from Site/SiteAnnouncer.py.

Scoped to the stateless/pure pieces: address parsing and the per-tracker
reliability bookkeeping that decides whether to skip an announce. The full
announceTracker() integration (actual HTTP/UDP requests, adding peers to a
site, worker_manager.onPeers()) needs real Peer/Site objects and lands in
Phase 6 -- but that logic "carries over unchanged" per the migration plan,
and this is the unchanged part: identical bookkeeping shape to today's
per-tracker `self.stats[tracker]` / module-level `global_stats[tracker]`
dicts, just as a small reusable class instead of two free-floating dicts.
"""
import re
import time


def getAddressParts(tracker: str) -> dict | None:
    if "://" not in tracker or not re.match(r"^[A-Za-z0-9:/\.#-]+$", tracker):
        return None
    protocol, address = tracker.split("://", 1)
    if ":" in address:
        ip, port = address.rsplit(":", 1)
    else:
        ip = address
        port = 443 if protocol.startswith("https") else 80
    return {"protocol": protocol, "address": address, "ip": ip, "port": port}


class TrackerStats:
    """Per-tracker request/success/error bookkeeping, used both to report
    status and to decide whether a tracker "looks unreliable" and should be
    skipped for a while (SiteAnnouncer.announce()'s pre-loop check)."""

    def __init__(self):
        self._stats: dict[str, dict] = {}

    def _entry(self, tracker: str) -> dict:
        return self._stats.setdefault(tracker, {
            "status": "", "num_request": 0, "num_success": 0, "num_error": 0,
            "time_request": 0.0, "time_status": 0.0, "time_last_error": 0.0,
            "last_error": None,
        })

    def get(self, tracker: str) -> dict:
        return dict(self._entry(tracker))

    def all(self) -> dict:
        """Every tracker's stats dict, for reporting (e.g. an
        announcerInfo/announcerStats-style command) rather than a single
        reliability decision."""
        return {tracker: dict(entry) for tracker, entry in self._stats.items()}

    def isReliable(self, tracker: str, force: bool = False) -> bool:
        """False if this tracker has errored enough recently that it should
        be skipped this round (unless force=True)."""
        if force:
            return True
        entry = self._entry(tracker)
        time_announce_allowed = time.time() - 60 * min(30, entry["num_error"])
        if entry["num_error"] > 5 and entry["time_request"] > time_announce_allowed:
            return False
        return True

    def recordRequest(self, tracker: str) -> None:
        entry = self._entry(tracker)
        entry["status"] = "announcing"
        entry["time_request"] = time.time()

    def recordSkipped(self, tracker: str, previous_status: str) -> None:
        entry = self._entry(tracker)
        entry["time_status"] = time.time()
        entry["status"] = previous_status

    def recordSuccess(self, tracker: str) -> None:
        entry = self._entry(tracker)
        entry["status"] = "announced"
        entry["time_status"] = time.time()
        entry["num_success"] += 1
        entry["num_request"] += 1
        entry["num_error"] = 0

    def recordError(self, tracker: str, error: Exception, has_internet: bool = True) -> None:
        entry = self._entry(tracker)
        entry["status"] = "error"
        entry["time_status"] = time.time()
        entry["last_error"] = str(error)
        entry["time_last_error"] = time.time()
        entry["num_request"] += 1
        if has_internet:
            entry["num_error"] += 1


# A tracker being unreliable is a fact about the tracker, not about any one
# site -- today's module-level `global_stats` (shared across every site's
# own SiteAnnouncer) exists so that all sites back off together instead of
# each independently rediscovering the same dead tracker. isReliable()
# checks should go through this shared instance; per-site display stats
# (num_success, last status, etc. for that site's UI) get their own
# TrackerStats() instance instead, mirroring today's self.stats/global_stats split.
global_tracker_stats = TrackerStats()
