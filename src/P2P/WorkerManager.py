"""File-fetch-and-verify primitives, plus (Scheduler, below) a real
priority-ordered, multi-peer-racing task scheduler -- not a line-for-line
port of Worker/WorkerManager.py's 600-line hand-rolled greenlet worker
pool, but a genuine replacement for what it does, built on trio's
structured concurrency instead of manually reimplementing it:

  - Multi-peer racing ("ask several peers for one file, take the first
    verified success, drop the rest") is a nursery + the nursery's own
    cancel_scope.cancel() -- trio's supported way to cancel a nursery's
    children uniformly. Much of the original's size (findWorkers/
    addWorker/worker.skip()) existed to hand-roll exactly this without
    that primitive available.
  - Per-task timeouts are trio.move_on_after instead of a manual
    time.time() sweep loop (checkTasks()).
  - Priority ordering is NOT something trio gives for free -- its
    CapacityLimiter is FIFO, no priority concept. PriorityLimiter below is
    a small hand-rolled priority-aware semaphore for that (heap of
    waiters, released in priority order as slots free up; see its
    docstring for why slot handoff has to be atomic, not
    decrement-then-anyone-can-grab-it).
  - Task dedup: concurrent needFile() calls for the same inner_path share
    one in-flight fetch and its result, rather than each starting their own.

Out of scope, same reasoning as the rest of this migration: optional-file
discovery via findHashIds across the network, and the site-wide periodic
health-check sweep (checkTasks()'s broader responsibilities beyond one
task's lifecycle, like internet-outage detection).

Scheduler.needFile() is now wrapped by Site.needFile() (see Site.py's own
docstring) -- the real, plugin-overridable per-file fetch entrypoint, e.g.
ContentFilter's mute check. syncSite()'s own bulk per-file loop below now
routes through site.needFile() too (see that function's own docstring),
so a plugin's per-file policy applies during a whole-site sync, not just
a single on-demand fetch -- closes what used to be documented here as a
real, separate gap.
"""
import heapq
import itertools
import json
import pathlib

import trio

from .Future import Future
from .Bigfile import (
    Piecefield,
    load_piecemap,
    piece_count,
    piece_range,
    validate_file_info,
    verify_piece,
)
from .ContentManager import _getDirname


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


async def fetchAndVerifyPiece(site, inner_path: str, pos_from: int, pos_to: int,
                              expected_hash: bytes | str, peers: list) -> bytes:
    """Fetch exactly one ranged piece and verify it before returning it."""
    last_error = None
    for peer in peers:
        try:
            buff = await peer.getFile(site.address, inner_path, pos_from=pos_from, pos_to=pos_to)
            buff.seek(0)
            data = buff.read()
            if len(data) != pos_to - pos_from:
                raise NoPeerHadFileError("Short Bigfile piece: %s != %s" % (len(data), pos_to - pos_from))
            verify_piece(data, expected_hash)
            return data
        except Exception as err:
            last_error = err
    raise NoPeerHadFileError("No peer had a valid piece of %s: %s" % (inner_path, last_error))


async def peersForPiece(site, file_info: dict, piece_index: int, peers: list) -> list:
    """Prefer peers advertising a completed copy of this piece.

    Older/native test peers may not implement piecefield exchange; those are
    retained as fallback candidates and the piece hash remains authoritative.
    """
    file_hash = file_info.get("sha512")
    advertised = []
    fallback = []
    for peer in peers:
        if not hasattr(peer, "getPiecefields"):
            fallback.append(peer)
            continue
        try:
            cache = getattr(peer, "_piecefields", None)
            if cache is None:
                cache = await peer.getPiecefields(site.address)
                peer._piecefields = cache
            entry = cache.get(file_hash)
            if entry:
                field = Piecefield.unpack(entry["packed"], int(entry["count"]))
                if field[piece_index]:
                    advertised.append(peer)
                continue
        except Exception:
            pass
        fallback.append(peer)
    return advertised or fallback or peers


async def loadBigfileInfo(site, inner_path: str, file_info: dict, peers: list) -> dict:
    """Resolve inline or legacy msgpack piece hashes for a Bigfile entry."""
    if file_info.get("sha512_pieces"):
        info = dict(file_info)
        validate_file_info(info)
        return info
    piecemap = file_info.get("piecemap")
    if not piecemap:
        raise ValueError("Bigfile metadata has no piece map")

    content_dir = _getDirname(file_info.get("content_inner_path", ""))
    piecemap_path = (content_dir + piecemap).strip("/")
    if site.storage.isFile(piecemap_path):
        raw = await site.storage.read(piecemap_path)
    else:
        raw = await fetchAndVerify(site, piecemap_path, peers)
        await site.storage.write(piecemap_path, raw)

    file_name = pathlib.PurePosixPath(inner_path).name
    info = dict(file_info)
    info.update(load_piecemap(raw, file_name))
    validate_file_info(info)
    return info


async def downloadBigfilePiece(site, inner_path: str, file_info: dict, piece_index: int,
                               peers: list, piecefield=None, state_lock=None) -> bool:
    info = await loadBigfileInfo(site, inner_path, file_info, peers)
    size, piece_size, hashes = validate_file_info(info)
    start, end = piece_range(size, piece_size, piece_index)
    if piecefield is None:
        piecefield = await site.storage.loadPiecefield(info["sha512"], len(hashes))
    if piecefield[piece_index]:
        return False

    candidates = await peersForPiece(site, info, piece_index, peers)
    data = await fetchAndVerifyPiece(site, inner_path, start, end, hashes[piece_index], candidates)
    if not site.storage.isFile(inner_path):
        site.storage.createSparseFile(inner_path, size)
    await site.storage.writeRange(inner_path, start, data)

    if state_lock is None:
        piecefield[piece_index] = True
        await site.storage.savePiecefield(info["sha512"], piecefield)
    else:
        async with state_lock:
            piecefield[piece_index] = True
            await site.storage.savePiecefield(info["sha512"], piecefield)
    return True


async def downloadBigfile(site, inner_path: str, file_info: dict, peers: list,
                          max_workers: int = 5) -> list[int]:
    """Download missing pieces concurrently and persist resumable progress."""
    info = await loadBigfileInfo(site, inner_path, file_info, peers)
    size, piece_size, hashes = validate_file_info(info)
    if not site.storage.isFile(inner_path):
        site.storage.createSparseFile(inner_path, size)
    piecefield = await site.storage.loadPiecefield(info["sha512"], len(hashes))
    state_lock = trio.Lock()
    limiter = trio.CapacityLimiter(max_workers)
    downloaded: list[int] = []

    async def one(piece_index):
        async with limiter:
            changed = await downloadBigfilePiece(
                site, inner_path, info, piece_index, peers, piecefield, state_lock,
            )
            if changed:
                downloaded.append(piece_index)

    async with trio.open_nursery() as nursery:
        for piece_index in range(len(hashes)):
            if not piecefield[piece_index]:
                nursery.start_soon(one, piece_index)
    return sorted(downloaded)


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
    site update propagating from one node to another over libp2p.

    Routes each file through site.needFile() (added alongside Site's own
    @acceptPlugins) rather than calling fetchAndVerify()/downloadBigfile()
    directly -- closes the gap plugins/ContentFilter/SitePlugin.py's own
    docstring used to flag ("WorkerManager.syncSite()'s bulk whole-site
    download loop bypasses [Site.needFile()] entirely"): a plugin's mute
    check now actually applies during a full site sync, not just a single
    on-demand fetch. needFile() itself already branches on piece_size/
    piecemap internally (see Site.needFile()'s own docstring), so this no
    longer needs its own separate Bigfile-vs-regular-file check either --
    one call handles both, and only a regular file's returned bytes still
    need an explicit storage.write() (a Bigfile's pieces are already
    written to disk piece-by-piece by the time needFile() returns).

    Per-file failures (network OR a plugin's own refusal, e.g. a mute
    match) are caught and skipped, not propagated -- a real behavior
    change from this function's earlier all-or-nothing version, and a
    deliberate one: a bulk sync where one peer doesn't have one file (or
    where content policy refuses it) should still bring back everything
    else, the same "best effort, return what actually updated" contract
    the original's own downloadContent() has. A caller that wants "all or
    nothing" for a single file already has that via site.needFile()
    directly (commands.py's fileNeed, actions.py's siteNeedFile) --
    unaffected, since neither goes through this loop."""
    content = await downloadContentJson(site, peers)
    updated = []
    for relative_path, file_info in content.get("files", {}).items():
        if site.storage.isFile(relative_path) and site.storage.getSize(relative_path) == file_info.get("size"):
            continue  # Cheap skip -- same size as what we'd fetch; not a full hash re-check
        is_bigfile = bool(file_info.get("piece_size") or file_info.get("piecemap"))
        try:
            data = await site.needFile(relative_path, peers)
        except Exception:
            continue
        if not is_bigfile:
            await site.storage.write(relative_path, data)
        updated.append(relative_path)
    return updated


async def publishUpdate(site, peers: list, inner_path: str = "content.json") -> int:
    """Pushes site's current, already-signed inner_path content to each
    peer via protocols/update.py's push protocol (Peer.pushUpdate()).
    Returns how many peers acknowledged it -- the counterpart to
    syncSite()'s pull direction. Requires inner_path to already be loaded
    into site.content_manager.contents (i.e. already signed via
    ContentManager.sign()); this doesn't sign anything itself.

    Reads the body straight off disk (site.storage.read()), not
    site.content_manager.contents[inner_path] -- for a private site that
    in-memory cache is the DECRYPTED plaintext (see ContentManager.py's
    own module docstring on why: only the owner, who always holds the
    content key, ever calls sign()), while what's actually supposed to
    go out over the wire is the encrypted envelope sitting on disk.
    Publishing the cached dict directly would leak the plaintext to
    every peer regardless of whether they're an approved recipient --
    found and fixed while wiring up the private-site propagation tests
    themselves. contents.get(inner_path) is still checked first as the
    "has this actually been signed/loaded yet" guard; only the body that
    goes over the wire changes."""
    if site.content_manager.contents.get(inner_path) is None:
        raise ValueError("No loaded content to publish for %s" % inner_path)
    body = await site.storage.read(inner_path)

    published = 0
    for peer in peers:
        try:
            res = await peer.pushUpdate(site.address, inner_path, body)
        except Exception:
            continue
        if res and "error" not in res:
            published += 1
    return published


async def publishGossip(site, gossip_manager, inner_path: str = "content.json") -> None:
    """Publishes site's current, already-signed inner_path content to its
    gossipsub topic (GossipManager.publish() -- a no-op if gossip isn't
    running). Sibling to publishUpdate(), not a replacement: gossipsub only
    reaches peers already meshed on this site's topic, so a peer with no
    mesh yet (e.g. right after its very first connection to the swarm)
    still needs the unicast push. Same content-already-loaded precondition
    as publishUpdate(); this doesn't sign anything either.

    Same disk-not-cache body source as publishUpdate() -- see that
    function's own docstring for why: publishing site.content_manager.
    contents[inner_path] directly would send a private site's decrypted
    plaintext out over the gossip mesh to every subscriber, not just
    approved recipients."""
    if site.content_manager.contents.get(inner_path) is None:
        raise ValueError("No loaded content to publish for %s" % inner_path)
    body = await site.storage.read(inner_path)
    await gossip_manager.publish(site.address, body)


class PriorityLimiter:
    """Like trio.CapacityLimiter, but waiters are released in priority
    order (highest first) rather than FIFO.

    Slot handoff on release() has to be atomic: if release() simply
    decremented a counter and then woke the highest-priority waiter, there
    would be a window between the decrement and the waiter actually
    resuming where a *different*, unrelated acquire() call could see a
    "free" slot and grab it too -- over-admitting past total_tokens. So
    release() either directly hands the slot to a waiter (count doesn't
    change, ownership transfers) or, if nobody's waiting, actually frees it.
    """

    def __init__(self, total_tokens: int):
        self.total_tokens = total_tokens
        self._in_use = 0
        self._waiters: list = []  # heap of (-priority, seq, trio.Event)
        self._seq = itertools.count()

    async def acquire(self, priority: int = 0) -> None:
        if self._in_use < self.total_tokens:
            self._in_use += 1
            return
        event = trio.Event()
        heapq.heappush(self._waiters, (-priority, next(self._seq), event))
        await event.wait()
        # release() handed this slot directly to us -- _in_use already accounts for it.

    def release(self) -> None:
        if self._waiters:
            _, _, event = heapq.heappop(self._waiters)
            event.set()
        else:
            self._in_use -= 1

    def use(self, priority: int = 0):
        return _PriorityLimiterContext(self, priority)


class _PriorityLimiterContext:
    def __init__(self, limiter: PriorityLimiter, priority: int):
        self._limiter = limiter
        self._priority = priority

    async def __aenter__(self):
        await self._limiter.acquire(self._priority)

    async def __aexit__(self, *exc_info):
        self._limiter.release()


class Scheduler:
    """Real task scheduler: priority-ordered, multi-peer-racing, deduped,
    timeout-bounded file fetches -- the trio-native replacement for
    Worker/WorkerManager.py's task queue. See module docstring for how
    each piece maps onto trio primitives."""

    def __init__(self, site, max_workers: int = 5):
        self.site = site
        self._limiter = PriorityLimiter(max_workers)
        self._inflight: dict[str, Future] = {}  # inner_path -> Future, for dedup

    async def needFile(self, inner_path: str, peers: list, priority: int = 0, timeout: float = 60) -> bytes:
        # Small scheduler adapters (and callers fetching an ordinary file
        # before content metadata is loaded) do not necessarily expose the
        # ContentManager metadata lookup.  Only big-file handling needs it;
        # ordinary files can use the peer race below without metadata.
        get_file_info = getattr(self.site.content_manager, "getFileInfo", None)
        file_info = get_file_info(inner_path) if get_file_info else None
        if file_info and (file_info.get("piece_size") or file_info.get("piecemap")):
            with trio.move_on_after(timeout) as scope:
                await downloadBigfile(self.site, inner_path, file_info, peers)
            if scope.cancelled_caught:
                raise TimeoutError("needFile timeout: %s" % inner_path)
            return await self.site.storage.read(inner_path)

        existing = self._inflight.get(inner_path)
        if existing is not None:
            return await existing.get()

        future = Future()
        self._inflight[inner_path] = future
        try:
            result_box: dict = {}
            with trio.move_on_after(timeout) as scope:
                async with trio.open_nursery() as nursery:
                    for peer in peers:
                        nursery.start_soon(self._tryPeer, inner_path, peer, priority, result_box, nursery.cancel_scope)

            if "data" in result_box:
                future.set(result_box["data"])
                return result_box["data"]

            if scope.cancelled_caught:
                error = TimeoutError("needFile timeout: %s" % inner_path)
            else:
                error = NoPeerHadFileError("No peer had a valid %s" % inner_path)
            future.set_error(error)
            raise error
        finally:
            self._inflight.pop(inner_path, None)

    async def _tryPeer(self, inner_path: str, peer, priority: int, result_box: dict, race_cancel_scope) -> None:
        async with self._limiter.use(priority):
            if "data" in result_box:
                return  # Another peer already won the race while we were waiting for a slot
            try:
                buff = await peer.getFile(self.site.address, inner_path)
                buff.seek(0)
                self.site.content_manager.verifyFile(inner_path, buff)
            except trio.Cancelled:
                raise
            except Exception:
                return  # This peer failed; siblings may still succeed

            if "data" not in result_box:
                buff.seek(0)
                result_box["data"] = buff.read()
                race_cancel_scope.cancel()  # First success wins -- stop the other racing peers
