import random
import logging

from rich import print

import asyncio

import asyncio_gevent

# Apply fix for aiobtdht KeyError bug before importing DHT
from .aiobtdht_fix import patch_aiobtdht
patch_aiobtdht()

from aiobtdht import DHT

from Config import config


class UDPServerAdapter:
    """
    Adapter class that provides the old aioudp UDPServer interface
    expected by aiokrpc/aiobtdht using asyncio's DatagramProtocol.

    Required interface:
    - subscribe(callback) - register async callback(data, addr)
    - send(data, addr) - send datagram to address
    - run(host, port, loop=loop) - start the server
    """
    def __init__(self):
        self._subscribers = {}
        self._subscriber_id = 0
        self._transport = None
        self._protocol = None
        self._loop = None

    def subscribe(self, callback):
        """Register a callback to receive datagrams."""
        self._subscriber_id += 1
        self._subscribers[self._subscriber_id] = callback
        return self._subscriber_id

    def unsubscribe(self, sub_id):
        """Unregister a callback."""
        self._subscribers.pop(sub_id, None)

    def send(self, data, addr):
        """Send data to the specified address."""
        if self._transport and not self._transport.is_closing():
            try:
                # Validate addr is a tuple (host, port), not just a port
                if not isinstance(addr, tuple) or len(addr) != 2:
                    import traceback
                    logging.warning(f"UDP send: invalid addr format: {addr} (type={type(addr).__name__})\n{''.join(traceback.format_stack())}")
                    return
                self._transport.sendto(data, addr)
            except (AttributeError, OSError, TypeError) as e:
                # Transport may have been closed between check and send
                logging.debug(f"UDP send failed: {e}")

    async def run(self, host, port, loop=None):
        """Start the UDP server and wait for it to be ready."""
        self._loop = loop or asyncio.get_event_loop()

        # Create the protocol class
        adapter = self

        class _Protocol(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                adapter._transport = transport

            def datagram_received(self, data, addr):
                # Notify all subscribers
                for callback in adapter._subscribers.values():
                    asyncio.ensure_future(callback(data, addr), loop=adapter._loop)

            def error_received(self, exc):
                logging.debug(f"UDP error received: {exc}")

            def connection_lost(self, exc):
                adapter._transport = None
                if exc:
                    logging.debug(f"UDP connection lost: {exc}")

        # Create the endpoint and wait for it to be ready
        transport, self._protocol = await self._loop.create_datagram_endpoint(
            _Protocol,
            local_addr=(host, port)
        )
        self._transport = transport

initial_nodes = [
    ("67.215.246.10", 6881),  # router.bittorrent.com
    ("87.98.162.88", 6881),  # dht.transmissionbt.com
    ("82.221.103.244", 6881)  # router.utorrent.com
]

def randomNodeId():
    r = ''
    for _ in range(20):
        byte = int(random.random()*256)
        r += f'{byte:02X}'
    return f'0x{r}'

class DHTServer:
    """Process DHT requests"""
    def __init__(self):
        self.peers = {}
        self.dht = None
        self.loop = None

    def start(self):
        self.loop = asyncio_gevent.EventLoop()
        asyncio.set_event_loop(self.loop)
        logging.info('Starting asyncio loop')
        self.loop.run_until_complete(self.run(self.loop))
        self.loop.run_forever()
        logging.info('DHTServer finished..')

    async def run(self, loop):
        udp = UDPServerAdapter()
        # Use port 0 to let OS assign an available ephemeral port
        await udp.run("0.0.0.0", 0, loop=loop)

        # TODO: preserve DHT id among sessions
        node_id = randomNodeId()

        self.dht = DHT(int(node_id, 16), server=udp, loop=self.loop)

        logging.info('Bootstrapping DHT')
        await self.dht.bootstrap(initial_nodes)
        logging.info('DHT bootstrap complete')

    async def _announce(self, site_hash):
        if self.dht is None:
            logging.warning(f'DHT not yet initialized, skipping announce for {site_hash.hex()}')
            return
        await self.dht.announce(site_hash, config.fileserver_port)
        logging.debug(f'DHT: announced {site_hash.hex()}, looking for peers')
        self.peers[site_hash] = await self.dht[site_hash]

    def announce(self, site_hash):
        # send announce to DHT
        if self.loop is not None:
            self.loop.create_task(self._announce(site_hash))
        # return peers that we already have
        return [{'addr': peer[0], 'port': peer[1]} for peer in self.peers.get(site_hash, set())]
