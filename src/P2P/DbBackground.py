"""Trio port of Db.py's background-task patterns: the periodic idle-cleanup
and commit-check loops, and the delayed-write batching used by
executeDelayed/insertOrUpdateDelayed/processDelayed.

Scoped narrowly on purpose: Db.py's actual SQLite access goes through
util/ThreadPool.py today (blocking calls offloaded to a gevent thread
pool), and ThreadPool's own trio port (trio.to_thread.run_sync) is Phase 4,
not this one. So these are the two *shapes* Db.py needs -- a periodic
sweep over live connections, and a coalesce-writes-for-1-second batcher --
built and tested generically here, ready to wire into the real Db class
once Phase 4's ThreadPool lands and Phase 6 does the full cutover.
"""
import time

import trio

from . import TaskManager


async def periodicLoop(interval: float, tick_fn, *, initial_delay: float | None = None) -> None:
    """Call tick_fn() (sync or async) every `interval` seconds, forever.
    Matches dbCleanup/dbCommitCheck's `while 1: time.sleep(n); ...` shape.
    """
    await trio.sleep(initial_delay if initial_delay is not None else interval)
    while True:
        result = tick_fn()
        if hasattr(result, "__await__"):
            await result
        await trio.sleep(interval)


def dbCleanupTick(opened_dbs, idle_after: float = 60 * 5) -> None:
    now = time.time()
    for db in list(opened_dbs):
        idle = now - db.last_query_time
        if idle > idle_after and db.close_idle:
            db.close("Cleanup")


def dbCommitCheckTick(opened_dbs) -> None:
    for db in list(opened_dbs):
        if not db.need_commit:
            continue
        if db.commit("Interval"):
            db.need_commit = False


class DelayedQueue:
    """Coalesces writes for `delay` seconds then flushes them as one batch
    via process_fn(queue) -- the executeDelayed/insertOrUpdateDelayed/
    processDelayed pattern, generalized over what "process a batch" means.
    """

    def __init__(self, process_fn, delay: float = 1.0):
        self._process_fn = process_fn
        self._delay = delay
        self._queue: list = []
        self._pending = False

    def add(self, item) -> None:
        if not self._pending:
            self._pending = True
            TaskManager.spawn_later(self._delay, self._flush)
        self._queue.append(item)

    async def _flush(self) -> None:
        if not self._queue:
            self._pending = False
            return
        queue, self._queue = self._queue, []
        self._pending = False
        result = self._process_fn(queue)
        if hasattr(result, "__await__"):
            await result

    async def flushNow(self) -> None:
        """For shutdown paths (Db.close() flushes any pending delayed queue
        before closing today) -- process whatever's queued immediately."""
        await self._flush()
