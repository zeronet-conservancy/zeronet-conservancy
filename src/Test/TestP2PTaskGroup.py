import trio

from P2P.TaskGroup import TaskGroup, wait_all
from P2P.Future import Future
from P2P import compat


class TestP2PFuture:
    def testSetAndGet(self):
        async def scenario():
            future = Future()
            assert not future.is_set()
            future.set(42)
            assert future.is_set()
            return await future.get()

        assert compat.run(scenario) == 42

    def testSetErrorRaisesOnGet(self):
        async def scenario():
            future = Future()
            future.set_error(ValueError("boom"))
            try:
                await future.get()
            except ValueError as e:
                return str(e)

        assert compat.run(scenario) == "boom"

    def testSecondSetIsIgnored(self):
        async def scenario():
            future = Future()
            future.set(1)
            future.set(2)  # ignored, first value wins
            return await future.get()

        assert compat.run(scenario) == 1


class TestP2PTaskGroup:
    def testSpawnReturnsResultViaFuture(self):
        async def worker(x):
            return x * 2

        async def scenario():
            async with trio.open_nursery() as nursery:
                tg = TaskGroup(nursery)
                future = tg.spawn(worker, 21)
                return await future.get()

        assert compat.run(scenario) == 42

    def testWaitAllWaitsForJustTheGivenBatch(self):
        order = []

        async def slow(label, delay):
            await trio.sleep(delay)
            order.append(label)
            return label

        async def scenario():
            async with trio.open_nursery() as nursery:
                tg = TaskGroup(nursery)
                batch = [tg.spawn(slow, "a", 0.02), tg.spawn(slow, "b", 0.04)]
                unrelated = tg.spawn(slow, "unrelated", 0.2)
                await wait_all(batch)
                assert order == ["a", "b"], order
                unrelated_future = unrelated
                nursery.cancel_scope.cancel()  # stop the unrelated 0.2s task, don't wait for it
                return unrelated_future

        compat.run(scenario)

    def testWaitAllRespectsTimeout(self):
        async def slow():
            await trio.sleep(1)

        async def scenario():
            async with trio.open_nursery() as nursery:
                tg = TaskGroup(nursery)
                future = tg.spawn(slow)
                t0 = trio.current_time()
                await wait_all([future], timeout=0.05)
                elapsed = trio.current_time() - t0
                tg.stop_all()
                return elapsed

        elapsed = compat.run(scenario)
        assert elapsed < 0.5, elapsed

    def testOneTaskFailingDoesNotCancelSiblings(self):
        results = []

        async def failer():
            raise ValueError("nope")

        async def succeeder():
            await trio.sleep(0.02)
            results.append("ok")

        async def scenario():
            async with trio.open_nursery() as nursery:
                tg = TaskGroup(nursery)
                fail_future = tg.spawn(failer)
                ok_future = tg.spawn(succeeder)
                await wait_all([fail_future, ok_future])
                return fail_future, ok_future

        fail_future, ok_future = compat.run(scenario)
        assert results == ["ok"]
        assert fail_future.is_set()
