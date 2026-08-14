"""Trio port of util/RateLimit.py.

Semantics unchanged: track last-called time per event key, allow immediate
calls outside the rate-limit window, coalesce repeated calls within the
window into one delayed call. Two real differences from the gevent version:

- func is now expected to be an async callable, awaited directly (the
  gevent version could spawn a plain blocking-looking function onto a
  greenlet; every caller is being ported to async as part of this
  migration anyway, so by the time this matters callers already pass
  async functions).
- The gevent version's module-level `gevent.spawn(rateLimitCleanup)` ran
  at import time. Trio has no fire-and-forget spawn, so the cleanup loop
  is started explicitly via startCleanup(), once, by whoever owns the
  app's background nursery (see TaskManager).
"""
import time
import logging

import trio

from . import TaskManager

log = logging.getLogger("RateLimit")

called_db = {}  # event -> last call time
queue_db = {}  # event -> (func, args, kwargs) queued to run


def called(event, penalty=0):
    called_db[event] = time.time() + penalty


def isAllowed(event, allowed_again=10):
    last_called = called_db.get(event)
    if not last_called:
        return True
    elif time.time() - last_called >= allowed_again:
        del called_db[event]
        return True
    else:
        return False


def delayLeft(event, allowed_again=10):
    last_called = called_db.get(event)
    if not last_called:
        return 0
    else:
        return allowed_again - (time.time() - last_called)


async def _callQueue(event):
    func, args, kwargs = queue_db[event]
    log.debug("Calling: %s" % event)
    called(event)
    del queue_db[event]
    await func(*args, **kwargs)


def callAsync(event, allowed_again=10, func=None, *args, **kwargs):
    """Fire-and-forget: call now if allowed, otherwise schedule the most
    recent call for when the rate-limit window clears."""
    if isAllowed(event, allowed_again):
        called(event)
        TaskManager.spawn(func, *args, **kwargs)
    else:
        time_left = allowed_again - max(0, time.time() - called_db[event])
        log.debug("Added to queue (%.2fs left): %s " % (time_left, event))
        if event not in queue_db:
            TaskManager.spawn_later(time_left, _callQueue, event)
        queue_db[event] = (func, args, kwargs)


async def call(event, allowed_again=10, func=None, *args, **kwargs):
    """Call now if allowed, otherwise await the rate-limit delay then call."""
    if isAllowed(event):
        called(event)
        return await func(*args, **kwargs)
    else:
        time_left = max(0, allowed_again - (time.time() - called_db[event]))
        log.debug("Calling sync (%.2fs left): %s" % (time_left, event))
        called(event, time_left)
        await trio.sleep(time_left)
        back = await func(*args, **kwargs)
        called(event)
        return back


async def _cleanupLoop():
    while True:
        expired = time.time() - 60 * 2  # 2 minutes
        for event in list(called_db.keys()):
            if called_db[event] < expired:
                del called_db[event]
        await trio.sleep(60 * 3)  # every 3 minutes


def startCleanup():
    TaskManager.spawn(_cleanupLoop)
