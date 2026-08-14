import sys
import types
import asyncio

import pytest
import mock

# Provide stub modules so DHT can be imported even where aiobtdht/aioudp
# are not installed (they are only used at runtime, never in these tests)
try:
    import aiobtdht  # noqa: F401
    import aioudp  # noqa: F401
except ImportError:
    aiobtdht = types.ModuleType("aiobtdht")
    aiobtdht.DHT = mock.MagicMock()
    aioudp = types.ModuleType("aioudp")
    aioudp.UDPServer = mock.MagicMock()
    sys.modules["aiobtdht"] = aiobtdht
    sys.modules["aioudp"] = aioudp

from DHT.DHTServer import DHTServer, loadNodeId, NODE_ID_FILE
from Config import config


@pytest.fixture
def dht_server(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "start_dir", tmp_path)
    monkeypatch.setattr(config, "dht_port", 12346)
    return DHTServer()


@pytest.mark.usefixtures("resetSettings")
class TestDHT:
    def testLoadNodeId(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "start_dir", tmp_path)
        node_id_1 = loadNodeId()
        assert 0 <= node_id_1 < 2 ** 160
        assert (tmp_path / NODE_ID_FILE).is_file()
        node_id_2 = loadNodeId()
        assert node_id_1 == node_id_2

    def testLoadNodeIdCorrupted(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "start_dir", tmp_path)
        (tmp_path / NODE_ID_FILE).write_text("not json")
        node_id = loadNodeId()
        assert 0 <= node_id < 2 ** 160

    def testGetPortConfigured(self, dht_server):
        assert dht_server.port == 12346

    def testGetPortAuto(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config, "start_dir", tmp_path)
        monkeypatch.setattr(config, "dht_port", 0)
        monkeypatch.setattr(config, "dht_port_range", "40000-40010")
        monkeypatch.setattr(config, "saveValue", mock.MagicMock())
        monkeypatch.setattr(DHTServer, "getRandomPort", lambda self, ip, a, b: 40001)
        server = DHTServer()
        assert server.port == 40001
        config.saveValue.assert_called_once_with("dht_port", 40001)

    def testAnnounce(self, dht_server):
        class FakeLoop:
            def __init__(self):
                self.tasks = []
            def create_task(self, coro):
                coro.close()  # Avoid "coroutine was never awaited" warning
                self.tasks.append(coro)
        dht_server.loop = FakeLoop()
        site_hash = b"x" * 20
        dht_server.peers[site_hash] = {("1.2.3.4", 1234)}
        res = dht_server.announce(site_hash)
        assert res == [("1.2.3.4", 1234)]
        assert site_hash in dht_server.site_hashes
        assert len(dht_server.loop.tasks) == 1

    def testSetPeers(self, dht_server):
        site_hash = b"y" * 20
        received = []
        dht_server.setOnPeers(site_hash, received.append)
        dht_server._setPeers(site_hash, {("5.6.7.8", 4321)})
        assert dht_server.peers[site_hash] == {("5.6.7.8", 4321)}
        assert received == [{("5.6.7.8", 4321)}]

    def testGetAsync(self, dht_server):
        site_hash = b"z" * 20
        received = []
        dht_server.setOnPeers(site_hash, received.append)

        class FakeDHT:
            async def __getitem__(self, hash):
                return {("9.9.9.9", 9999)}
        dht_server.dht = FakeDHT()

        loop = asyncio.new_event_loop()
        loop.run_until_complete(dht_server._get(site_hash))
        loop.close()

        assert dht_server.peers[site_hash] == {("9.9.9.9", 9999)}
        assert received == [{("9.9.9.9", 9999)}]
