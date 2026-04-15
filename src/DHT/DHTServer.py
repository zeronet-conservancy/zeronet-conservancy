import random
import logging
import time

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

ANNOUNCE_INTERVAL = 60  # Don't re-announce same hash within this many seconds
ANNOUNCE_TIMEOUT = 5    # Seconds to wait for a single DHT announce


class DHTServer:
    """Process DHT requests"""
    def __init__(self):
        self.peers = {}
        self.dht = None
        self.loop = None
        self.num_announces = 0
        self.num_peers_found = 0
        self.last_announce_time = {}  # site_hash -> timestamp of last announce

    def start(self):
        self.loop = asyncio_gevent.EventLoop()
        asyncio.set_event_loop(self.loop)
        logging.info('Starting asyncio loop')
        self.loop.run_until_complete(self.run(self.loop))
        logging.info('DHT running, starting status logger')
        self.loop.create_task(self._periodic_status())
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
        num_nodes = self.getNodeCount()
        logging.info(f'DHT bootstrap complete, routing table has {num_nodes} nodes')

    def getNodeCount(self):
        if self.dht is None:
            return 0
        count = 0
        for bucket in self.dht.routing_table._buckets:
            count += sum(1 for _ in bucket.nodes)
        return count

    async def _periodic_status(self):
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            num_nodes = self.getNodeCount()
            num_sites = len(self.peers)
            total_peers = sum(len(p) for p in self.peers.values())
            logging.info(
                f'DHT status: {num_nodes} routing table nodes, '
                f'{num_sites} sites tracked, {total_peers} total peers cached, '
                f'{self.num_announces} announces, {self.num_peers_found} peers found'
            )

    async def _announce_one(self, site_hash):
        """Announce a single site hash. Returns (site_hash, peers_list)."""
        now = time.time()
        last = self.last_announce_time.get(site_hash, 0)
        if now - last < ANNOUNCE_INTERVAL:
            # Recently announced, just return cached peers
            cached = self.peers.get(site_hash, set())
            return (site_hash, [{'addr': p[0], 'port': p[1]} for p in cached])

        try:
            s = time.time()
            await asyncio.wait_for(
                self.dht.announce(site_hash, config.fileserver_port),
                timeout=ANNOUNCE_TIMEOUT
            )
            peers = await asyncio.wait_for(
                self.dht[site_hash],
                timeout=ANNOUNCE_TIMEOUT
            )
            self.peers[site_hash] = peers
            self.last_announce_time[site_hash] = time.time()
            self.num_announces += 1
            self.num_peers_found += len(peers)
            elapsed = time.time() - s
            if peers:
                logging.info(
                    f'DHT: {site_hash.hex()}: found {len(peers)} peers in {elapsed:.2f}s'
                )
            else:
                logging.debug(
                    f'DHT: {site_hash.hex()}: 0 peers in {elapsed:.2f}s'
                )
            return (site_hash, [{'addr': p[0], 'port': p[1]} for p in peers])
        except asyncio.TimeoutError:
            logging.debug(f'DHT: {site_hash.hex()}: announce timed out after {ANNOUNCE_TIMEOUT}s')
            cached = self.peers.get(site_hash, set())
            return (site_hash, [{'addr': p[0], 'port': p[1]} for p in cached])
        except Exception as e:
            logging.debug(f'DHT: {site_hash.hex()}: announce error: {e}')
            cached = self.peers.get(site_hash, set())
            return (site_hash, [{'addr': p[0], 'port': p[1]} for p in cached])

    async def _announce_batch(self, site_hashes):
        """Announce multiple site hashes concurrently. Returns dict of hash -> peers."""
        tasks = [self._announce_one(h) for h in site_hashes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out = {}
        for result in results:
            if isinstance(result, Exception):
                logging.debug(f'DHT: batch announce exception: {result}')
                continue
            site_hash, peers = result
            out[site_hash] = peers
        return out

    def announce(self, site_hash, timeout=ANNOUNCE_TIMEOUT + 2):
        """Announce a single site to DHT and wait for peer results.

        Returns list of {'addr': ip, 'port': port} dicts.
        """
        import gevent
        import gevent.event

        if self.loop is None or self.dht is None:
            return [{'addr': p[0], 'port': p[1]} for p in self.peers.get(site_hash, set())]

        result_event = gevent.event.AsyncResult()

        async def _run():
            try:
                _hash, peers = await self._announce_one(site_hash)
                result_event.set(peers)
            except Exception as e:
                result_event.set_exception(e)

        self.loop.create_task(_run())

        try:
            return result_event.get(timeout=timeout)
        except gevent.Timeout:
            logging.debug(f'DHT: {site_hash.hex()}: gevent timeout after {timeout}s')
            return [{'addr': p[0], 'port': p[1]} for p in self.peers.get(site_hash, set())]
        except Exception as e:
            logging.debug(f'DHT: {site_hash.hex()}: gevent error: {e}')
            return [{'addr': p[0], 'port': p[1]} for p in self.peers.get(site_hash, set())]
