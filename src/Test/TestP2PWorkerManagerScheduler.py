import io
import pathlib
import tempfile

import pytest
import trio

from libp2p.peer.peerinfo import PeerInfo

from Crypt import CryptBitcoin
from P2P.Host import Host
from P2P.FileServer import FileServer
from P2P.Site import Site
from P2P.Peer import Peer
from P2P.ConnectionPolicy import ConnectionPolicy
from P2P.WorkerManager import PriorityLimiter, Scheduler, NoPeerHadFileError
from P2P import compat


class FakePeer:
    """Controllable stand-in for P2P.Peer -- returns/raises/delays exactly
    what the test wants, so racing/timeout/priority behavior can be tested
    deterministically instead of depending on real network timing."""

    def __init__(self, name, data=None, delay=0.0, fail=False):
        self.name = name
        self.data = data
        self.delay = delay
        self.fail = fail
        self.called = False

    async def getFile(self, site_address, inner_path):
        self.called = True
        if self.delay:
            await trio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("%s: simulated failure" % self.name)
        buff = io.BytesIO(self.data)
        buff.seek(0, io.SEEK_END)
        buff.seek(0)
        return buff


class FakeContentManager:
    def __init__(self, expected: dict):
        self.expected = expected  # inner_path -> bytes

    def verifyFile(self, inner_path, file):
        file.seek(0)
        data = file.read()
        if data != self.expected.get(inner_path):
            raise ValueError("hash mismatch")
        return True


class FakeSite:
    def __init__(self, address, expected: dict):
        self.address = address
        self.content_manager = FakeContentManager(expected)


class TestPriorityLimiter:
    def testAdmitsUpToCapacityImmediately(self):
        async def scenario():
            limiter = PriorityLimiter(2)
            order = []

            async def hold(name, priority):
                async with limiter.use(priority):
                    order.append(("acquired", name))

            async with trio.open_nursery() as nursery:
                nursery.start_soon(hold, "a", 0)
                nursery.start_soon(hold, "b", 0)
            return order

        order = compat.run(scenario)
        assert set(order) == {("acquired", "a"), ("acquired", "b")}

    def testReleasesHighestPriorityWaiterFirst(self):
        async def scenario():
            limiter = PriorityLimiter(1)
            admitted_order = []
            release_gate = trio.Event()

            async def holdFirst():
                async with limiter.use(priority=0):
                    admitted_order.append("first")
                    await release_gate.wait()

            async def waiter(name, priority):
                async with limiter.use(priority=priority):
                    admitted_order.append(name)

            async with trio.open_nursery() as nursery:
                nursery.start_soon(holdFirst)
                await trio.sleep(0.05)  # let holdFirst grab the only slot
                # Queue three waiters out of priority order; higher number = higher priority.
                nursery.start_soon(waiter, "low", 1)
                nursery.start_soon(waiter, "high", 10)
                nursery.start_soon(waiter, "medium", 5)
                await trio.sleep(0.05)  # let them all queue up before releasing
                release_gate.set()

            return admitted_order

        order = compat.run(scenario)
        assert order == ["first", "high", "medium", "low"]

    def testDoesNotOverAdmitPastCapacity(self):
        async def scenario():
            limiter = PriorityLimiter(2)
            concurrent = 0
            max_concurrent = 0

            async def worker():
                nonlocal concurrent, max_concurrent
                async with limiter.use():
                    concurrent += 1
                    max_concurrent = max(max_concurrent, concurrent)
                    await trio.sleep(0.02)
                    concurrent -= 1

            async with trio.open_nursery() as nursery:
                for _ in range(8):
                    nursery.start_soon(worker)
            return max_concurrent

        assert compat.run(scenario) <= 2


class TestP2PWorkerManagerScheduler:
    def testRacingReturnsFastestPeerResult(self):
        async def scenario():
            slow = FakePeer("slow", data=b"slow-data", delay=1.0)
            fast = FakePeer("fast", data=b"fast-data", delay=0.01)
            site = FakeSite("1Site", {"data.json": b"fast-data"})
            scheduler = Scheduler(site, max_workers=5)

            with trio.move_on_after(2) as scope:
                result = await scheduler.needFile("data.json", [slow, fast])
            assert not scope.cancelled_caught
            return result, slow.called, fast.called

        result, slow_called, fast_called = compat.run(scenario)
        assert result == b"fast-data"
        assert fast_called is True
        # slow may or may not have started before losing the race, but it
        # should never be allowed to overwrite the already-won result.

    def testFailedPeerDoesNotBlockOthers(self):
        async def scenario():
            failing = FakePeer("failing", fail=True)
            good = FakePeer("good", data=b"good-data", delay=0.02)
            site = FakeSite("1Site", {"data.json": b"good-data"})
            scheduler = Scheduler(site, max_workers=5)
            return await scheduler.needFile("data.json", [failing, good])

        assert compat.run(scenario) == b"good-data"

    def testAllPeersFailingRaises(self):
        async def scenario():
            a = FakePeer("a", fail=True)
            b = FakePeer("b", fail=True)
            site = FakeSite("1Site", {})
            scheduler = Scheduler(site, max_workers=5)
            with pytest.raises(NoPeerHadFileError):
                await scheduler.needFile("data.json", [a, b])

        compat.run(scenario)

    def testTimeoutWhenAllPeersTooSlow(self):
        async def scenario():
            slow = FakePeer("slow", data=b"eventually", delay=5.0)
            site = FakeSite("1Site", {"data.json": b"eventually"})
            scheduler = Scheduler(site, max_workers=5)
            with pytest.raises(TimeoutError):
                await scheduler.needFile("data.json", [slow], timeout=0.05)

        compat.run(scenario)

    def testDedupSharesInFlightFetch(self):
        async def scenario():
            peer = FakePeer("peer", data=b"shared-data", delay=0.05)
            site = FakeSite("1Site", {"data.json": b"shared-data"})
            scheduler = Scheduler(site, max_workers=5)

            results = []

            async def caller():
                results.append(await scheduler.needFile("data.json", [peer]))

            async with trio.open_nursery() as nursery:
                for _ in range(5):
                    nursery.start_soon(caller)

            return results, peer.called

        results, peer_was_called = compat.run(scenario)
        assert results == [b"shared-data"] * 5
        assert peer_was_called is True


class TestP2PSchedulerRealNetwork:
    """One real end-to-end check with actual libp2p hosts and Peer.getFile(),
    not just FakePeer -- confirms Scheduler works against the real stack,
    not only its own mocked concurrency model."""

    def testSchedulerFetchesRealFileOverLibp2p(self):
        privatekey = CryptBitcoin.newPrivatekey()
        site_address = CryptBitcoin.privatekeyToAddress(privatekey)
        content = b"real network content for the scheduler"

        async def scenario():
            with tempfile.TemporaryDirectory() as da, tempfile.TemporaryDirectory() as db, \
                    tempfile.TemporaryDirectory() as root_a, tempfile.TemporaryDirectory() as root_b:
                server_a = FileServer(pathlib.Path(da), ws_port=None)
                site_a = Site(site_address, pathlib.Path(root_a))
                server_a.addSite(site_a)
                await site_a.storage.write("data.json", content)

                import json
                import time
                file_content = {
                    "address": site_address,
                    "modified": time.time(),
                    "files": {"data.json": {"size": len(content)}},
                }

                site_b = Site(site_address, pathlib.Path(root_b))
                site_b.content_manager.contents["content.json"] = file_content

                # Patch verifyFile expectations to just check size for this
                # test (real sha512 check already covered elsewhere).
                from Crypt import CryptHash
                site_b.content_manager.contents["content.json"]["files"]["data.json"]["sha512"] = CryptHash.sha512sum(io.BytesIO(content))

                server_b = FileServer(pathlib.Path(db), ws_port=None)

                async with server_a.run(), server_b.run():
                    await server_b.host.connect(PeerInfo(server_a.host.peer_id, server_a.host.get_addrs()))
                    policy_b = ConnectionPolicy(server_b.host)
                    peer_a = Peer(server_a.host.peer_id, server_b.host, policy_b)

                    scheduler = Scheduler(site_b, max_workers=3)
                    return await scheduler.needFile("data.json", [peer_a])

        assert compat.run(scenario) == content
