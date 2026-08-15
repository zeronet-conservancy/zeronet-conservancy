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
"""
import heapq
import itertools
import json

import trio

from .Future import Future


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
