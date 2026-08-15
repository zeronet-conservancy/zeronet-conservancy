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
    does exactly that) and whether to forward the update further.
  - No per-connection in-flight-dedup bookkeeping (files_parsing) --
    WorkerManager.Scheduler already dedupes needFile() calls; this
    handler doesn't need its own copy for a single verify-and-write.
"""
import json

PROTOCOL_ID = "/zeronet/update/1.0.0"


def make_handler(site_resolver):
    """site_resolver(site_address) -> Site | None: the site to update, or
    None if unknown/not serving."""

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
            content = json.loads(body.decode("utf8"))
        except Exception as err:
            return {"error": "File invalid JSON: %s" % err}

        try:
            applied = site.content_manager.verifyContentJson(content, inner_path=inner_path)
        except Exception as err:
            return {"error": "File invalid update: %s" % err}

        if applied is False:
            return {"ok": "Same content, not updated"}

        await site.storage.write(inner_path, body)
        site.content_manager.contents[inner_path] = content
        return {"ok": "Thanks, file %s updated!" % inner_path}

    return handle
