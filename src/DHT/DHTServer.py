from rich import print

import asyncio

import asyncio_gevent

from aiobtdht import DHT
from aioudp import UDPServer

from Config import config

initial_nodes = [
    ("67.215.246.10", 6881),  # router.bittorrent.com
    ("87.98.162.88", 6881),  # dht.transmissionbt.com
    ("82.221.103.244", 6881)  # router.utorrent.com
]

class DHTServer:
    """Process DHT requests"""
    def __init__(self):
        self.peers = {}

    def start(self):
        self.loop = asyncio_gevent.EventLoop()
        asyncio.set_event_loop(self.loop)
        print('Starting asyncio loop')
        self.loop.run_until_complete(self.run(self.loop))
        self.loop.run_forever()
        print('DHTServer finished..')

    async def run(self, loop):
        # return None
        udp = UDPServer()
        udp.run("0.0.0.0", 12346, loop=loop)
        node_id = "0x54A10C9B159FC0FBBF6A39029BCEF406904019E0" # TODO

        self.dht = DHT(int(node_id, 16), server=udp, loop=self.loop)

        print('Bootstrapping DHT')
        await self.dht.bootstrap(initial_nodes)
        print('Bootstrap complete')

    async def _announce(self, site_hash):
        await self.dht.announce(site_hash, config.fileserver_port)
        print(f'announced {site_hash.hex()}, looking for peers')
        self.peers[site_hash] = await self.dht[site_hash]

    def announce(self, site_hash):
        # send announce to DHT
        self.loop.create_task(self._announce(site_hash))
        # return peers that we already have
        return [{'addr': peer[0], 'port': peer[1]} for peer in self.peers.get(site_hash, set())]
