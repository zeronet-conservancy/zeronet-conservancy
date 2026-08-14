import os
import json
import random
import socket
import logging

from rich import print

import asyncio
import gevent

import asyncio_gevent

from aiobtdht import DHT
from aioudp import UDPServer

from Config import config
from util import helper

initial_nodes = [
    ("67.215.246.10", 6881),  # router.bittorrent.com
    ("87.98.162.88", 6881),  # dht.transmissionbt.com
    ("82.221.103.244", 6881)  # router.utorrent.com
]

NODE_ID_FILE = "dht.json"
REFRESH_INTERVAL = 60 * 5  # seconds


def loadNodeId():
    """Load persisted DHT node id or generate and persist a new one."""
    path = config.start_dir / NODE_ID_FILE
    try:
        with path.open() as f:
            node_id = json.load(f).get("node_id")
        if node_id and len(node_id) == 40:
            return int(node_id, 16)
    except (OSError, ValueError, json.JSONDecodeError):
        pass

    node_id_int = int.from_bytes(os.urandom(20), "big")
    node_id = "%040x" % node_id_int
    try:
        with path.open("w") as f:
            json.dump({"node_id": node_id}, f)
    except OSError as err:
        logging.warning("DHT: can't persist node id: %s" % err)
    return node_id_int


class DHTServer:
    """Process DHT requests"""
    def __init__(self):
        self.peers = {}
        self.site_hashes = set()
        self.on_peers = {}  # site_hash -> callback
        self.node_id = loadNodeId()
        self.port = self.getPort()
        self.loop = None
        self.dht = None
        self.stopping = False

    def getRandomPort(self, ip, port_range_from, port_range_to):
        for _ in range(100):
            port = random.randint(port_range_from, port_range_to)
            sock = helper.createSocket(ip, socket.SOCK_DGRAM)
            try:
                sock.bind((ip, port))
                sock.close()
                return port
            except OSError:
                sock.close()
        return False

    def getPort(self):
        if config.dht_port:
            return config.dht_port

        port_range_from, port_range_to = list(map(int, config.dht_port_range.split("-")))
        port = self.getRandomPort("0.0.0.0", port_range_from, port_range_to)
        if not port:
            raise Exception("Can't find bindable DHT port")
        config.saveValue("dht_port", port)  # Save random port value for next restart
        config.arguments.dht_port = port
        config.dht_port = port
        return port

    def setOnPeers(self, site_hash, callback):
        self.on_peers[site_hash] = callback

    def start(self):
        self.loop = asyncio_gevent.EventLoop()
        asyncio.set_event_loop(self.loop)
        logging.info('Starting asyncio loop')
        gevent.spawn(self.refresh)
        self.loop.run_until_complete(self.run(self.loop))
        self.loop.run_forever()
        logging.info('DHTServer finished..')

    def stop(self):
        self.stopping = True
        if self.loop is not None:
            try:
                self.loop.stop()
            except Exception:
                pass

    async def run(self, loop):
        udp = UDPServer()
        udp.run("0.0.0.0", self.port, loop=loop)

        self.dht = DHT(self.node_id, server=udp, loop=self.loop)

        logging.info('Bootstrapping DHT')
        await self.dht.bootstrap(initial_nodes)
        logging.info('DHT bootstrap complete')

    def _setPeers(self, site_hash, peers):
        self.peers[site_hash] = peers
        callback = self.on_peers.get(site_hash)
        if callback:
            callback(peers)

    async def _announce(self, site_hash):
        await self.dht.announce(site_hash, config.fileserver_port)
        logging.info(f'DHT: announced {site_hash.hex()}, looking for peers')
        peers = await self.dht[site_hash]
        self._setPeers(site_hash, peers)

    async def _get(self, site_hash):
        peers = await self.dht[site_hash]
        self._setPeers(site_hash, peers)

    def refresh(self):
        while not self.stopping:
            gevent.sleep(REFRESH_INTERVAL)
            if self.dht is None or self.loop is None:
                continue
            for site_hash in list(self.site_hashes):
                try:
                    self.loop.create_task(self._get(site_hash))
                except Exception as err:
                    logging.warning("DHT: refresh error: %s" % err)

    def announce(self, site_hash):
        # send announce to DHT
        self.site_hashes.add(site_hash)
        if self.loop is not None:
            try:
                self.loop.create_task(self._announce(site_hash))
            except Exception as err:
                logging.warning("DHT: announce error: %s" % err)
        # return peers that we already have
        return list(self.peers.get(site_hash, set()))
