"""Port of File/FileRequest.py's actionUpdate -- receives a pushed
content.json update from a peer and applies it if it's newer and valid.
This is the wire-level piece every prior "no update/broadcast protocol
exists yet" note (P2P/actions.py's and P2P/Ui/commands.py's sitePublish,
SiteAnnouncer.py) was waiting on.

Scoped down from the original, deliberately, not just incidentally:
  - content.json only, matching the original's own restriction ("Only
    content.json update allowed" -- non-root/include files still aren't
    pushable here either way).
  - No "body missing, fetch it yourself" fallback. The original supports
    a peer sending just a change notification and having the receiver
    pull the body separately (site.addPeer + peer.getFile); every real
    caller here (Peer.pushUpdate(), WorkerManager.publishUpdate()) always
    sends the full body, so that fallback would only ever trigger for a
    hand-crafted request -- and erroring is the safer response to that,
    not fetching from whoever just sent it.
  - No further-file-download-after-content-update and no re-gossip-to-
    other-peers-on-apply (the original's site.publish() flood-forward
    from inside the handler). Applying the new content.json is a
    complete, useful action on its own; the caller decides whether/how
    to fetch the files it newly lists (WorkerManager.syncSite() already
    does exactly that) and whether to forward the update further. Update:
    "forward the update further" now also has a real path -- gossipsub
    (see GossipManager.py, protocols/gossip_update.py) -- but that's a
    peer-to-swarm broadcast, orthogonal to this stream's peer-to-peer RPC,
    not something this handler triggers.
  - No per-connection in-flight-dedup bookkeeping (files_parsing) --
    WorkerManager.Scheduler already dedupes needFile() calls; this
    handler doesn't need its own copy for a single verify-and-write.

applyContentUpdate() below is the shared verify+write+notify core, used
both by this RPC handler and by gossip_update.py's topic-subscription
consumer, so gossiped and directly-pushed updates go through identical
validation and application logic.
"""
import json

PROTOCOL_ID = "/zeronet/update/1.0.0"


class ContentUpdateError(Exception):
    """Raised by applyContentUpdate() when body isn't a valid content.json
    update for the given site -- bad JSON, or a verifyContentJson()
    failure (bad signature, stale/future timestamp, bad path, oversize,
    failed include checks, ...). Callers translate this into whatever
    error shape their own protocol needs: an RPC error dict here, a
    reject from gossip_update.py's topic validator."""


async def applyContentUpdate(site, inner_path: str, body: bytes, on_applied=None) -> bool:
    """Verify body against site.content_manager and, if it's a genuine
    update, write it and refresh the in-memory contents. Returns True if
    applied, False for the benign "same content, not updated" case (not
    an error -- the caller already has this version). Raises
    ContentUpdateError for anything actually invalid."""
    try:
        content = json.loads(body.decode("utf8"))
    except Exception as err:
        raise ContentUpdateError("File invalid JSON: %s" % err) from err

    try:
        applied = site.content_manager.verifyContentJson(content, inner_path=inner_path)
    except Exception as err:
        raise ContentUpdateError("File invalid update: %s" % err) from err

    if applied is False:
        return False

    await site.storage.write(inner_path, body)
    site.content_manager.contents[inner_path] = content
    if on_applied is not None:
        on_applied(site, inner_path)
    return True


def make_handler(site_resolver, on_applied=None):
    """site_resolver(site_address) -> Site | None: the site to update, or
    None if unknown/not serving. on_applied(site, inner_path), if given, is
    called after a real write -- not for the "Same content, not updated"
    no-op case -- so callers (FileServer.py) can push a live UI update to
    any open dashboard/site tab without this handler needing to know
    anything about UiApp.broadcast() itself."""

    async def handle(params: dict) -> dict:
        site = site_resolver(params.get("site"))
        if site is None:
            return {"error": "Unknown site"}

        inner_path = params.get("inner_path") or "content.json"
        if not inner_path.endswith("content.json"):
            return {"error": "Only content.json update allowed"}

        body = params.get("body")
        if not body:
            return {"error": "Missing body"}

        try:
            applied = await applyContentUpdate(site, inner_path, body, on_applied=on_applied)
        except ContentUpdateError as err:
            return {"error": str(err)}

        if not applied:
            return {"ok": "Same content, not updated"}
        return {"ok": "Thanks, file %s updated!" % inner_path}

    return handle
