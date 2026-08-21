"""Trio replacement for the bare `gevent.spawn()`-at-module-level pattern
used today by RateLimit.py (its cleanup loop) and Db.py (dbCleanup,
dbCommitCheck, delayed writes). Trio has no global fire-and-forget spawn --
every task needs an owning nursery with a bounded lifetime, by design
(structured concurrency). This module provides that owning nursery for
app-wide background bookkeeping tasks: main.py opens one nursery for the
app's lifetime and calls init(nursery) once; everything else spawns into it.
"""
import trio

_background_nursery: trio.Nursery | None = None


def init(nursery: trio.Nursery) -> None:
    global _background_nursery
    _background_nursery = nursery


def spawn(async_fn, *args) -> None:
    if _background_nursery is None:
        raise RuntimeError("TaskManager.init() must be called before spawn()")
    _background_nursery.start_soon(async_fn, *args)


async def _sleep_then_call(delay: float, async_fn, args) -> None:
    await trio.sleep(delay)
    await async_fn(*args)


def spawn_later(delay: float, async_fn, *args) -> None:
    spawn(_sleep_then_call, delay, async_fn, args)
