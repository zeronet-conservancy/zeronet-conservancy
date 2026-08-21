import time

import trio

from P2P import TaskManager, DbBackground, compat


class FakeDb:
    def __init__(self, idle_time, need_commit=False, close_idle=True):
        self.last_query_time = time.time() - idle_time
        self.need_commit = need_commit
        self.close_idle = close_idle
        self.closed_reason = None
        self.committed = False

    def close(self, reason):
        self.closed_reason = reason

    def commit(self, reason):
        self.committed = True
        return True


class TestP2PDbBackground:
    def testDbCleanupTick(self):
        stale = FakeDb(idle_time=1000)
        fresh = FakeDb(idle_time=1)
        DbBackground.dbCleanupTick([stale, fresh], idle_after=60)
        assert stale.closed_reason == "Cleanup"
        assert fresh.closed_reason is None

    def testDbCommitCheckTick(self):
        dirty = FakeDb(idle_time=0, need_commit=True)
        clean = FakeDb(idle_time=0, need_commit=False)
        DbBackground.dbCommitCheckTick([dirty, clean])
        assert dirty.committed and dirty.need_commit is False
        assert not clean.committed

    def testDelayedQueueCoalescesThenFlushes(self):
        flushed = []

        def process(batch):
            flushed.append(list(batch))

        async def scenario():
            async with trio.open_nursery() as nursery:
                TaskManager.init(nursery)
                dq = DbBackground.DelayedQueue(process, delay=0.05)
                dq.add("a")
                dq.add("b")
                assert flushed == []
                await trio.sleep(0.1)
                assert flushed == [["a", "b"]]

                dq.add("c")
                await dq.flushNow()
                assert flushed[-1] == ["c"]

        compat.run(scenario)

    def testPeriodicLoopTicksRepeatedly(self):
        ticks = []

        async def run_loop():
            await DbBackground.periodicLoop(0.05, lambda: ticks.append(time.monotonic()), initial_delay=0.01)

        async def scenario():
            with trio.move_on_after(0.18):
                async with trio.open_nursery() as nursery:
                    nursery.start_soon(run_loop)

        compat.run(scenario)
        assert len(ticks) >= 2, ticks
