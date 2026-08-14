import trio

from P2P import RateLimit, TaskManager, compat


class TestP2PRateLimit:
    def testCallAsyncImmediateThenCoalesced(self):
        RateLimit.called_db.clear()
        RateLimit.queue_db.clear()
        calls = []

        async def record(label):
            calls.append(label)

        async def scenario():
            async with trio.open_nursery() as nursery:
                TaskManager.init(nursery)

                RateLimit.callAsync("test-event", 0.2, record, "first")
                await trio.sleep(0.01)
                # Called again within the window -- should coalesce, not
                # fire a second immediate call.
                RateLimit.callAsync("test-event", 0.2, record, "second")
                RateLimit.callAsync("test-event", 0.2, record, "third")
                await trio.sleep(0.01)
                assert calls == ["first"], calls

                await trio.sleep(0.25)  # let the coalesced delayed call finish

        compat.run(scenario)
        assert calls == ["first", "third"], calls

    def testCallAwaitsRateLimitDelay(self):
        RateLimit.called_db.clear()
        RateLimit.queue_db.clear()
        calls = []

        async def record(label):
            calls.append((label, trio.current_time()))
            return label

        async def scenario():
            async with trio.open_nursery() as nursery:
                TaskManager.init(nursery)
                t0 = trio.current_time()
                result1 = await RateLimit.call("sync-event", 0.15, record, "a")
                result2 = await RateLimit.call("sync-event", 0.15, record, "b")
                return t0, result1, result2

        t0, result1, result2 = compat.run(scenario)
        assert result1 == "a"
        assert result2 == "b"
        assert calls[0][0] == "a"
        assert calls[1][0] == "b"
        assert calls[1][1] - calls[0][1] >= 0.14  # second call waited out the window
