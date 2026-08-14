"""Trio port of util/ThreadPool.py.

The gevent version's complexity is almost entirely a workaround for a
gevent-specific constraint: only the main gevent-cooperative thread may
safely touch gevent's hub/greenlets/semaphores, so calls arriving from
other real OS threads have to be marshalled back onto the main thread by
hand (MainLoopCaller, built on real thread-safe Lock/Event classes since
even gevent's own primitives aren't safe to touch from another thread).

trio has no equivalent constraint: trio.to_thread.run_sync() offloads a
blocking call to a real worker thread and awaits it cooperatively, and
trio.from_thread.run_sync()/run() (usable from within a to_thread-spawned
worker without any extra setup) call back into the main trio task from
that worker. Both are built-in and well-tested, so the hand-rolled
MainLoopCaller/Lock/Event/patchSleep machinery isn't needed here -- see
call_from_worker_thread() below for the one place Db.py used it
(main_loop.call(self.conn.close)).
"""
import trio

Lock = trio.Lock  # has .acquire()/.release()/.locked() already


class ThreadPool:
    """Offloads blocking calls to a real worker thread, bounded to at most
    `max_size` concurrent threads, awaited cooperatively by the caller."""

    def __init__(self, max_size: int, name: str | None = None):
        self.name = name or "ThreadPool#%s" % id(self)
        self.setMaxSize(max_size)

    def setMaxSize(self, max_size: int) -> None:
        self.max_size = max_size
        self._limiter = trio.CapacityLimiter(max_size) if max_size > 0 else None

    def wrap(self, func):
        """Decorator: `@pool.wrap` on a sync function makes it an async
        function that runs on the pool when awaited."""
        if self._limiter is None:
            async def call_directly(*args, **kwargs):
                return func(*args, **kwargs)
            return call_directly

        async def call_offloaded(*args, **kwargs):
            return await self.apply(func, args, kwargs)

        return call_offloaded

    async def spawn(self, func, *args, **kwargs):
        return await self.apply(func, args, kwargs)

    async def apply(self, func, args=(), kwargs=None):
        kwargs = kwargs or {}
        if self._limiter is None:
            return func(*args, **kwargs)
        if kwargs:
            def bound():
                return func(*args, **kwargs)
            return await trio.to_thread.run_sync(bound, limiter=self._limiter)
        return await trio.to_thread.run_sync(func, *args, limiter=self._limiter)

    def kill(self) -> None:
        self._limiter = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.kill()


def call_from_worker_thread(sync_fn, *args):
    """For code running inside a trio.to_thread.run_sync() worker that
    needs to call back into the main trio task -- direct replacement for
    ThreadPool.py's `main_loop.call(...)`."""
    return trio.from_thread.run_sync(sync_fn, *args)
