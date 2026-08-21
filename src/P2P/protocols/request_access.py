"""Direct P2P delivery for a private-site access request (P2P/Ui/commands.py's
siteRequestAccess), replacing the earlier "copy this payload and relay it out
of band" design with an actual wire push to whatever peers the requester is
already connected to for that site.

Two acceptors, in order:
  - The site OWNER's node stores it durably (SiteManager's own
    private_pending_requests setting) -- the real destination.
  - Any other peer serving the site accepts it too, but only into
    RequestAccessRelay's bounded, TTL'd, in-memory store, not durable
    settings -- see that module's own docstring for why. This is the
    "owner is offline right now" half: WorkerManager.
    forwardPendingAccessRequests(), driven by App._announceLoop's existing
    periodic per-site re-announce, re-pushes whatever a relay is holding to
    newly-known peers each cycle, so a request keeps getting carried along
    node to node until it reaches a peer that's actually the owner --
    including the owner coming back online later and connecting to
    whoever's still holding it. Before this, only the OWNER accepted these
    at all, so delivery required the requester to be directly connected to
    the owner's node at request time; that direct-connection path still
    works unchanged (and is naturally the fast path when the owner happens
    to already be online) -- this only adds a slower fallback on top.

Verification happens here, for both acceptors, not just on approval:
recovering the requester's public key from the signature and checking it
matches the claimed auth_address (the same check ContentManager.
addRecipientKey() does at approval time) keeps junk/spoofed entries out of
both stores in the first place, even though addRecipientKey() re-derives
and re-checks the same thing again when the owner actually approves --
cheap, and it means what gets held (durably by the owner, temporarily by a
relay) is already known-genuine, not just known-well-formed. A relay
storing an unverified request would also be a cheap way to fill a
stranger's relay slots with garbage it then dutifully carries around.
"""
import time

from Crypt import CryptEcies

PROTOCOL_ID = "/zeronet/request_access/1.0.0"


def make_handler(site_resolver, site_manager_getter, on_request=None, relay=None):
    """site_resolver(site_address) -> Site | None, same contract as
    update.py's make_handler(). site_manager_getter() -> SiteManager | None
    is a callable (not a plain value) because FileServer wires site_manager
    in as a late-bound attribute, same reason update.py's on_applied is a
    callback rather than a constructor param -- see FileServer.py's own
    comment on why. on_request(site, auth_address), if given, is called
    after a request is newly stored BY THE OWNER (not for a relay-only
    accept -- there's nothing for a UI to show on a node that isn't the
    owner), so callers (App) can push a live UI notification without this
    handler needing to know about UiApp.broadcast(). relay, if given, is
    the RequestAccessRelay a non-owner node falls back to instead of
    rejecting outright."""

    async def handle(params: dict) -> dict:
        site = site_resolver(params.get("site"))
        if site is None:
            return {"error": "Unknown site"}

        address = params.get("auth_address")
        signature = params.get("signature")
        if not address or not signature:
            return {"error": "auth_address and signature required"}

        message = CryptEcies.ACCESS_REQUEST_MESSAGE % site.address
        try:
            publickey = CryptEcies.recoverPublicKey(signature, message)
        except Exception:
            return {"error": "Invalid signature"}
        if CryptEcies.publicToAddress(publickey) != address:
            return {"error": "Signature does not match auth_address"}

        site_manager = site_manager_getter()
        if site_manager is not None and site_manager.isOwn(site.address):
            pending = dict(site_manager.getSiteSetting(site.address, "private_pending_requests", {}))
            pending[address] = {"signature": signature, "received_at": time.time()}
            await site_manager.setSiteSetting(site.address, "private_pending_requests", pending)

            if on_request is not None:
                on_request(site, address)

            return {"ok": "Access request queued", "stored_by_owner": True}

        if relay is not None:
            relay.add(site.address, address, signature)
            return {"ok": "Access request relayed", "stored_by_owner": False}

        return {"error": "Not the owner of this site"}

    return handle
