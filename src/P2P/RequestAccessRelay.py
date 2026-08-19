"""Bystander store-and-forward for private-site access requests.

protocols/request_access.py's direct push (Peer.requestAccess()) only
reaches the owner if the requester happens to already be connected to the
owner's node at request time -- fine when the owner is usually online, a
real gap when they're not. This is the "offline owner" half: any peer
serving the site, not just the owner, can accept a request it can't itself
approve and hold it here temporarily, so it gets carried along and re-pushed
to other peers (the App._announceLoop's own periodic re-announce is what
drives the re-push -- see WorkerManager.forwardPendingAccessRequests()) --
eventually reaching a peer that actually owns the site, including the owner
coming back online later and connecting to whoever's still holding it.

Bounded and TTL'd because, unlike protocols/update.py's already-signed
content or protocols/pex.py's already-known peer records, this accepts
data from an unauthenticated stranger about a site this node doesn't own:
nothing stops someone from generating many (site_address, auth_address)
pairs and pushing all of them at every relay they can reach. The signature
check in protocols/request_access.py already rejects anything that isn't a
genuine, correctly-signed request for that exact site address, so this
can't be filled with pure garbage -- but a real requester could still
oversubscribe many different sites' relay slots. MAX_PER_SITE and MAX_TOTAL
cap the blast radius to "this node's disk/memory usage stays bounded", not
"no one can ever waste a relay slot"; TTL_SECONDS bounds how long a stale,
already-approved-or-abandoned request keeps taking up a slot.

Deliberately in-memory only, not persisted to disk: unlike private_recipients/
private_pending_requests (SiteManager's settings store, the OWNER's actual
durable state), a relay copy is disposable by design -- losing it on
restart just means this one relay stops carrying it, and any other relay
(or a future retry) still can.
"""
import time

MAX_PER_SITE = 20
MAX_TOTAL = 200
TTL_SECONDS = 7 * 24 * 3600


class RequestAccessRelay:
    def __init__(self, max_per_site: int = MAX_PER_SITE, max_total: int = MAX_TOTAL, ttl: float = TTL_SECONDS):
        self._max_per_site = max_per_site
        self._max_total = max_total
        self._ttl = ttl
        # site_address -> {auth_address: {"signature": str, "received_at": float}}
        # Insertion order (a plain dict already preserves it) doubles as
        # oldest-first eviction order -- no separate bookkeeping needed.
        self._store: dict[str, dict[str, dict]] = {}

    def _prune(self) -> None:
        now = time.time()
        for site_address in list(self._store):
            entries = self._store[site_address]
            for auth_address in list(entries):
                if now - entries[auth_address]["received_at"] > self._ttl:
                    del entries[auth_address]
            if not entries:
                del self._store[site_address]

    def _totalCount(self) -> int:
        return sum(len(entries) for entries in self._store.values())

    def add(self, site_address: str, auth_address: str, signature: str) -> None:
        self._prune()
        entries = self._store.setdefault(site_address, {})
        entries.pop(auth_address, None)  # re-insert at the end (freshest) on a repeat request
        entries[auth_address] = {"signature": signature, "received_at": time.time()}

        while len(entries) > self._max_per_site:
            entries.pop(next(iter(entries)))

        while self._totalCount() > self._max_total:
            oldest_site = next(iter(self._store))
            oldest_entries = self._store[oldest_site]
            oldest_entries.pop(next(iter(oldest_entries)))
            if not oldest_entries:
                del self._store[oldest_site]

    def remove(self, site_address: str, auth_address: str) -> None:
        entries = self._store.get(site_address)
        if entries is not None:
            entries.pop(auth_address, None)
            if not entries:
                del self._store[site_address]

    def getAll(self, site_address: str) -> dict:
        self._prune()
        return dict(self._store.get(site_address, {}))
