"""Minimal file-fetch-and-verify primitive -- not a full port of
Worker/WorkerManager.py's task queue/scheduler (600 lines: priority
queues, per-task worker pools with retry/timeout, optional-file discovery
via findHashIds across the network). That's genuinely large, separate
distributed-download-orchestration logic deserving its own dedicated pass.

What's here is the actual mechanism the Phase 6 end-to-end milestone
needs: given a list of candidate peers, try them in turn until one
produces a file that verifies -- the "give me this file, checked" building
block WorkerManager's much richer scheduling would sit on top of. Good
enough to prove a real site update propagates and verifies end to end;
not a replacement for real peer-selection/retry/priority logic.
"""
import json


class NoPeerHadFileError(Exception):
    pass


async def fetchAndVerify(site, inner_path: str, peers: list) -> bytes:
    """Try each peer in turn; return the first verified file's bytes."""
    last_error = None
    for peer in peers:
        try:
            buff = await peer.getFile(site.address, inner_path)
        except Exception as err:
            last_error = err
            continue

        try:
            buff.seek(0)
            site.content_manager.verifyFile(inner_path, buff)
        except Exception as err:
            last_error = err
            continue

        buff.seek(0)
        return buff.read()

    raise NoPeerHadFileError("No peer had a valid %s: %s" % (inner_path, last_error))


async def downloadContentJson(site, peers: list) -> dict:
    """Fetch and verify a fresh content.json from candidate peers, applying
    it to site.content_manager if it's actually newer. Returns whichever
    content ends up current (the newly-applied one, or -- if every peer
    only had what we already have -- our existing one)."""
    last_error = None
    for peer in peers:
        try:
            buff = await peer.getFile(site.address, "content.json")
            buff.seek(0)
            content = json.loads(buff.read().decode("utf8"))
        except Exception as err:
            last_error = err
            continue

        try:
            applied = site.content_manager.verifyContentJson(content)
        except Exception as err:
            last_error = err
            continue

        if applied is False:  # Peer's content.json was the same as what we already have
            return site.content_manager.contents.get("content.json")

        site.content_manager.contents["content.json"] = content
        await site.storage.writeJson("content.json", content)
        return content

    raise NoPeerHadFileError("No peer had a valid content.json: %s" % last_error)


async def syncSite(site, peers: list) -> list:
    """content.json + every listed file, fetched and verified from
    whichever peers have them. Returns the inner_paths actually
    (re)written. This is the flow the Phase 6 milestone exercises: a real
    site update propagating from one node to another over libp2p."""
    content = await downloadContentJson(site, peers)
    updated = []
    for relative_path, file_info in content.get("files", {}).items():
        if site.storage.isFile(relative_path) and site.storage.getSize(relative_path) == file_info.get("size"):
            continue  # Cheap skip -- same size as what we'd fetch; not a full hash re-check
        data = await fetchAndVerify(site, relative_path, peers)
        await site.storage.write(relative_path, data)
        updated.append(relative_path)
    return updated
