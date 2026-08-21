import threading
import time

import trio

from P2P.ThreadPool import ThreadPool, call_from_worker_thread
from P2P import compat


class TestP2PThreadPool:
    def testApplyOffloadsToRealThread(self):
        main_thread = threading.current_thread().ident

        def blocking_work(x):
            return threading.current_thread().ident, x * 2

        async def scenario():
            pool = ThreadPool(4)
            worker_thread, result = await pool.apply(blocking_work, (21,))
            return worker_thread, result, main_thread

        worker_thread, result, main_thread_id = compat.run(scenario)
        assert result == 42
        assert worker_thread != main_thread_id  # actually ran on a different OS thread

    def testWrapDecorator(self):
        pool = ThreadPool(2)

        @pool.wrap
        def add(a, b):
            return a + b

        async def scenario():
            return await add(2, 3)

        assert compat.run(scenario) == 5

    def testMaxSizeZeroRunsDirectly(self):
        pool = ThreadPool(0)
        main_thread = threading.current_thread().ident

        def work():
            return threading.current_thread().ident

        async def scenario():
            return await pool.apply(work)

        assert compat.run(scenario) == main_thread

    def testCapacityLimiterBoundsConcurrency(self):
        active = []
        max_concurrent = []

        def slow_work(n):
            active.append(n)
            max_concurrent.append(len(active))
            time.sleep(0.05)
            active.remove(n)
            return n

        async def scenario():
            pool = ThreadPool(2)  # only 2 concurrent workers allowed
            async with trio.open_nursery() as nursery:
                results = []

                async def run_one(n):
                    results.append(await pool.apply(slow_work, (n,)))

                for i in range(5):
                    nursery.start_soon(run_one, i)
            return results

        results = compat.run(scenario)
        assert sorted(results) == [0, 1, 2, 3, 4]
        assert max(max_concurrent) <= 2, max_concurrent

    def testCallFromWorkerThread(self):
        calls = []

        def on_main_thread(x):
            calls.append(x)
            return x + 1

        def worker(x):
            return call_from_worker_thread(on_main_thread, x)

        async def scenario():
            pool = ThreadPool(2)
            return await pool.apply(worker, (10,))

        result = compat.run(scenario)
        assert result == 11
        assert calls == [10]
