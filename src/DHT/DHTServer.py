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
    ("67.215.246.10", 6881),   # router.bittorrent.com
    ("87.98.162.88", 6881),    # dht.transmissionbt.com
    ("82.221.103.244", 6881),  # router.utorrent.com
    ("212.129.33.50", 6881),   # dht.aelitis.com
    ("router.silotis.us", 6881),
]

def randomNodeId():
    r = ''
    for _ in range(20):
        byte = int(random.random()*256)
        r += f'{byte:02X}'
    return f'0x{r}'

ANNOUNCE_INTERVAL = 60  # Don't re-announce same hash within this many seconds
ANNOUNCE_TIMEOUT = 30   # Seconds to wait for a single DHT announce/lookup


class DHTServer:
    """Process DHT requests.

    DHT runs on its own asyncio event loop inside a gevent greenlet.
    To avoid gevent<->asyncio starvation (gevent callers blocking while the
    asyncio loop can't run), announce() is fire-and-forget: it submits the
    async task and immediately returns cached peers. When the async task
    completes, it calls the provided callback with fresh results.
    """
    def __init__(self):
        self.peers = {}
        self.dht = None
        self.loop = None
        self.num_announces = 0
        self.num_peers_found = 0
        self.num_timeouts = 0
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
        for attempt in range(3):
            await self.dht.bootstrap(initial_nodes)
            num_nodes = self.getNodeCount()
            if num_nodes >= 4:
                break
            if attempt < 2:
                logging.info(f'DHT bootstrap got only {num_nodes} nodes, retrying ({attempt + 1}/3)...')
                await asyncio.sleep(2)
        logging.info(f'DHT bootstrap complete, routing table has {num_nodes} nodes')

    def getNodeCount(self):
        if self.dht is None:
            return 0
        count = 0
        for bucket in self.dht.routing_table._buckets:
            count += sum(1 for _ in bucket.nodes)
        return count

    async def _periodic_status(self):
        last_announces = 0
        last_peers_found = 0
        last_timeouts = 0
        while True:
            await asyncio.sleep(60)
            num_nodes = self.getNodeCount()
            sites_with_peers = sum(1 for p in self.peers.values() if p)
            total_sites = len(self.peers)
            total_peers = sum(len(p) for p in self.peers.values())
            unique_ips = set()
            for peer_set in self.peers.values():
                for addr, port in peer_set:
                    unique_ips.add(addr)
            new_announces = self.num_announces - last_announces
            new_peers = self.num_peers_found - last_peers_found
            new_timeouts = self.num_timeouts - last_timeouts
            last_announces = self.num_announces
            last_peers_found = self.num_peers_found
            last_timeouts = self.num_timeouts
            logging.info(
                f'DHT: {num_nodes} nodes, '
                f'{sites_with_peers}/{total_sites} sites with peers, '
                f'{len(unique_ips)} unique peers, '
                f'last 60s: {new_announces} ok / {new_timeouts} timeout / {new_peers} peers'
            )

    async def _announce_one(self, site_hash, callback=None):
        """Announce a single site hash. Calls callback(peers) when done."""
        now = time.time()
        last = self.last_announce_time.get(site_hash, 0)
        if now - last < ANNOUNCE_INTERVAL:
            return  # Recently announced, skip

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
            logging.debug(
                f'DHT: {site_hash.hex()}: {len(peers)} peers in {elapsed:.1f}s'
            )
            if callback and peers:
                peer_list = [{'addr': p[0], 'port': p[1]} for p in peers]
                callback(peer_list)
        except asyncio.TimeoutError:
            self.num_timeouts += 1
            logging.debug(f'DHT: {site_hash.hex()}: timed out after {ANNOUNCE_TIMEOUT}s')
        except Exception as e:
            self.num_timeouts += 1
            logging.debug(f'DHT: {site_hash.hex()}: error: {e}')

    def announce(self, site_hash, callback=None):
        """Submit a DHT announce (fire-and-forget).

        Immediately returns cached peers. When the async announce completes
        and finds new peers, calls callback(peers_list) if provided.
        This avoids blocking gevent greenlets waiting for the asyncio loop.
        """
        if self.loop is None or self.dht is None:
            return [{'addr': p[0], 'port': p[1]} for p in self.peers.get(site_hash, set())]

        # Fire-and-forget: submit to asyncio loop, don't block
        self.loop.create_task(self._announce_one(site_hash, callback=callback))

        # Return whatever we have cached
        return [{'addr': p[0], 'port': p[1]} for p in self.peers.get(site_hash, set())]
