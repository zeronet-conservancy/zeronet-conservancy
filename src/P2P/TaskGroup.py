"""Trio replacement for util/GreenletManager.py.

GreenletManager tracks greenlets spawned by one owner (today, one instance
per Site) so they can all be cancelled together (`stopGreenlets`) without
touching unrelated background work. The trio shape for "spawn tasks
in-line, into an already-running scope, at unpredictable times, cancellable
as a group" is one CancelScope per task, tracked in a set, spawned into a
nursery the owner already has open for its own lifetime -- there is no
trio construct that lets you add tasks to a nursery from outside an
`async with` block the way gevent.spawn() can be called from anywhere.
"""
import trio

from .Future import Future


class TaskGroup:
    def __init__(self, nursery: trio.Nursery):
        self._nursery = nursery
        self._cancel_scopes: set[trio.CancelScope] = set()

    def spawn(self, async_fn, *args) -> Future:
        """Returns a Future that resolves with async_fn's return value once
        the task completes -- lets callers collect a batch of handles and
        wait_all() on just that batch, matching gevent.joinall(threads, ...).
        """
        cancel_scope = trio.CancelScope()
        self._cancel_scopes.add(cancel_scope)
        future = Future()

        async def runner():
            try:
                with cancel_scope:
                    try:
                        result = await async_fn(*args)
                        future.set(result)
                    except trio.Cancelled:
                        raise  # let cancellation propagate as normal
                    except BaseException as exc:
                        # One task's failure shouldn't cancel its siblings in
                        # the group (matches gevent.joinall's tolerance of
                        # individual greenlet failures) -- store it on the
                        # future instead; callers see it via Future.get().
                        future.set_error(exc)
            finally:
                self._cancel_scopes.discard(cancel_scope)

        self._nursery.start_soon(runner)
        return future

    def spawn_later(self, delay: float, async_fn, *args) -> None:
        async def delayed():
            await trio.sleep(delay)
            await async_fn(*args)

        self.spawn(delayed)

    def stop_all(self, reason: str = "Stopping all tasks") -> int:
        num = len(self._cancel_scopes)
        for scope in list(self._cancel_scopes):
            scope.cancel()
        return num


async def wait_all(futures, timeout: float | None = None) -> None:
    """Wait for a specific batch of Futures (as returned by TaskGroup.spawn),
    matching gevent.joinall(threads, timeout=N) -- unlike stop_all(), this
    doesn't touch the group's other tasks, just waits on the ones you hand
    it. Does not raise stored task errors; check individual futures for
    those if you care.
    """
    async def _wait_one(future):
        try:
            await future.get()
        except BaseException:
            pass  # errors are inspected via the future, not raised here

    if timeout is None:
        for future in futures:
            await _wait_one(future)
    else:
        with trio.move_on_after(timeout):
            for future in futures:
                await _wait_one(future)
