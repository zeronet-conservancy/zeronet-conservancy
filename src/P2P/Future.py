"""One-shot future, trio equivalent of gevent.event.AsyncResult.

Needed by WorkerManager.py's addTaskCreate() (not yet ported -- it depends
on Peer.py/Site.py, which are Phase 6's job): it creates one of these per
task, up to three different completion paths call .set(value) exactly once,
and callers elsewhere await the eventual result. trio has no built-in
value-carrying one-shot future (trio.Event carries no value), so this pairs
an Event with a stored value/error.
"""
import trio


class Future:
    def __init__(self):
        self._event = trio.Event()
        self._value = None
        self._error: BaseException | None = None

    def set(self, value=None) -> None:
        if self._event.is_set():
            return
        self._value = value
        self._event.set()

    def set_error(self, error: BaseException) -> None:
        if self._event.is_set():
            return
        self._error = error
        self._event.set()

    async def get(self):
        await self._event.wait()
        if self._error is not None:
            raise self._error
        return self._value

    def is_set(self) -> bool:
        return self._event.is_set()
