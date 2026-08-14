import select
import threading

import gevent
import gevent.monkey
import trio
from gevent.event import AsyncResult


def _restore_real_stdlib_io():
    """gevent.monkey.patch_all() replaces select.epoll and socket.socket
    process-wide (they're process-global module attributes, not
    thread-local), which breaks trio's IO manager even when trio runs in
    its own OS thread: trio's Linux epoll backend needs the real
    select.epoll, and trio_websocket's raw-socket handling does a strict
    `type(sock) is socket.socket` check that gevent's socket subclass fails.
    Put the real ones back -- safe to do globally, since gevent's own
    scheduling goes through libev, not through these symbols directly.
    """
    if not gevent.monkey.is_module_patched("select"):
        return
    select.epoll = gevent.monkey.get_original("select", "epoll")
    import socket
    socket.socket = gevent.monkey.get_original("socket", "socket")


class TrioLoop:
    """Runs a trio event loop in a dedicated OS thread and lets gevent
    greenlets call into it cooperatively.

    Unlike asyncio, trio has no hook letting a foreign scheduler share its
    OS thread (that's what asyncio_gevent exploits for DHTServer.py), so this
    bridge takes the other approach outlined in the plan: trio owns its own
    thread, and `run()` hands a coroutine to that thread via `trio.from_thread`,
    then blocks only the calling greenlet -- not the whole gevent hub -- on a
    gevent.event.AsyncResult until the trio side calls back through a
    thread-safe libev watcher.
    """

    def __init__(self):
        self._token: trio.lowlevel.TrioToken | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_trio, name="trio-loop", daemon=True)

    def start(self):
        _restore_real_stdlib_io()
        self._thread.start()
        self._ready.wait()

    def _run_trio(self):
        async def main():
            self._token = trio.lowlevel.current_trio_token()
            self._ready.set()
            await trio.sleep_forever()

        trio.run(main)

    def run(self, async_fn, *args):
        """Call from a gevent greenlet. Runs `await async_fn(*args)` on the
        trio loop and cooperatively blocks the calling greenlet until it
        completes, returning its result or raising its exception.
        """
        gresult = AsyncResult()
        watcher = gevent.get_hub().loop.async_()
        box: dict = {}

        def _on_wake():
            watcher.stop()
            if "error" in box:
                gresult.set_exception(box["error"])
            else:
                gresult.set(box["value"])

        watcher.start(_on_wake)

        def _deliver(error, value):
            if error is not None:
                box["error"] = error
            else:
                box["value"] = value
            watcher.send()

        async def _runner():
            try:
                value = await async_fn(*args)
            except BaseException as exc:  # noqa: BLE001 - relayed to the caller greenlet
                _deliver(exc, None)
            else:
                _deliver(None, value)

        trio.from_thread.run_sync(
            lambda: trio.lowlevel.spawn_system_task(_runner),
            trio_token=self._token,
        )
        return gresult.get()
