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


class TaskGroup:
    def __init__(self, nursery: trio.Nursery):
        self._nursery = nursery
        self._cancel_scopes: set[trio.CancelScope] = set()

    def spawn(self, async_fn, *args) -> None:
        cancel_scope = trio.CancelScope()
        self._cancel_scopes.add(cancel_scope)

        async def runner():
            try:
                with cancel_scope:
                    await async_fn(*args)
            finally:
                self._cancel_scopes.discard(cancel_scope)

        self._nursery.start_soon(runner)

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
