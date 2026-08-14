"""Transition-period helper for running trio inside a still-gevent process.

gevent.monkey.patch_all() deletes select.epoll and replaces socket.socket
process-wide; trio's IO manager needs the real versions to run at all. But
restoring them process-wide and leaving them restored breaks gevent's own
cooperative networking permanently, for the rest of the process -- this is
not about a live trio thread or GIL contention (that was an earlier,
incorrect theory), it's simply that gevent's cooperation depends on
socket.socket staying as its patched class. So: bracket the restoration
tightly around each trio.run() call, and swap gevent's patched versions
back immediately after, every time.

This module -- and the need for it at all -- goes away once gevent is
removed from the app entirely (see the libp2p migration plan's Phase 11).
Until then, every standalone P2P test that calls trio.run() should go
through run() here instead of calling trio.run() directly.
"""
import select
import socket

import trio

try:
    from gevent import monkey as _gevent_monkey
except ImportError:
    _gevent_monkey = None


def run(async_fn, *args):
    if _gevent_monkey is None or not _gevent_monkey.is_module_patched("socket"):
        return trio.run(async_fn, *args)

    gevent_epoll = getattr(select, "epoll", None)
    gevent_socket = socket.socket
    real_epoll = _gevent_monkey.get_original("select", "epoll")
    real_socket = _gevent_monkey.get_original("socket", "socket")

    select.epoll = real_epoll
    socket.socket = real_socket
    try:
        return trio.run(async_fn, *args)
    finally:
        if gevent_epoll is not None:
            select.epoll = gevent_epoll
        else:
            del select.epoll
        socket.socket = gevent_socket
