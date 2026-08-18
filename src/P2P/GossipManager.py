"""Node-wide gossipsub pub/sub, for propagating site content.json updates
through a topic mesh instead of (or alongside) direct unicast push.

One shared GossipSub/Pubsub pair per node, not per site -- gossipsub
topics are a swarm-wide concept, unlike the per-connection RPC protocols
ProtocolRouter registers via host.raw.set_stream_handler(). Owned by
FileServer, the single owner of the node's one Host, same as ProtocolRouter.

Step 2 of the gossipsub rollout: per-site subscribe/unsubscribe (wired
into App._wireSite/deleteSite) plus the content-update topic validator
and consumer (protocols/gossip_update.py). Still no publish path -- that's
next, alongside WorkerManager.publishUpdate()'s unicast push.

subscribeSite()/unsubscribeSite() are sync -- App._wireSite/deleteSite are
themselves sync (called from sync contexts: UiServer's on_missing_site
callback, Ui/commands.py) and loadSites() wires every persisted site
*before* app.run() (and so before GossipManager.run()) ever starts, per
app.py's _main(). So both methods just record what's wanted in self._sites;
the actual async subscribe/unsubscribe is scheduled onto self._nursery
when one exists (gossip already running) and otherwise picked up by run()
itself, which subscribes every already-wanted site once it starts.

Conservative mesh parameters for zeronet-conservancy's site-swarm scale
(tens, not thousands, of peers per topic) -- the library's own defaults
target large public gossipsub networks and are oversized here. Provisional;
revisit once there's real swarm telemetry to tune against.
"""
from contextlib import AsyncExitStack, asynccontextmanager

import trio
from libp2p.pubsub.gossipsub import (
    GossipSub,
    PROTOCOL_ID,
    PROTOCOL_ID_V11,
    PROTOCOL_ID_V12,
    PROTOCOL_ID_V13,
    PROTOCOL_ID_V14,
    PROTOCOL_ID_V20,
)
from libp2p.pubsub.pubsub import Pubsub
from libp2p.tools.anyio_service import background_trio_service

from .protocols import gossip_update

# Newest first, so peers negotiate the most capable protocol both sides support.
GOSSIPSUB_PROTOCOLS = (
    PROTOCOL_ID_V20, PROTOCOL_ID_V14, PROTOCOL_ID_V13, PROTOCOL_ID_V12, PROTOCOL_ID_V11, PROTOCOL_ID,
)

TOPIC_PREFIX = "/zeronet/content-update/1.0.0"

DEGREE = 6
DEGREE_LOW = 4
DEGREE_HIGH = 12

# The library default (120s) targets large, low-churn public gossipsub
# networks. A peer only grafts into a topic's mesh during a heartbeat, and
# join() attempts an immediate graft but only from peers whose SUBSCRIBE
# announcement has already been received -- freshly-connected peers often
# haven't propagated that yet. At the 120s default, missing that first
# opportunistic graft means waiting up to two full minutes for the next
# heartbeat before any publish reaches anyone at all -- confirmed while
# building this (an end-to-end propagation test hung until this was
# lowered). 1s keeps mesh formation on a human/test timescale without
# being so frequent it floods small swarms with heartbeat control traffic.
HEARTBEAT_INTERVAL = 1


class GossipManager:
    """Owns the node's single GossipSub router and Pubsub instance.

    content.json already carries its own site-address-keyed signature
    (ContentManager.sign()/_verifySignature()), which is the real trust
    root for gossiped updates -- gossipsub's own strict_signing would only
    add a redundant peer-identity signature on top of what Noise transport
    security already guarantees, so it's disabled here.

    GossipSub/Pubsub are constructed inside run(), not __init__ -- same
    deferred-construction pattern Host.run() uses for CircuitV2Protocol/
    CircuitV2Transport. Pubsub.__init__ registers a network notifee that
    feeds a *zero-buffer* trio channel on every peer connection; that
    channel only has a reader once Pubsub.run()'s handle_peer_queue daemon
    task is actually running. Constructing Pubsub eagerly in __init__
    would register that notifee before anything is consuming it, so the
    very first peer connection on a Host/FileServer that never enters
    GossipManager.run() (most of the P2P test suite constructs and runs a
    bare Host/FileServer without the full app.py wiring) deadlocks inside
    host.connect() -- confirmed while building this.
    """

    def __init__(self, host, on_applied=None):
        self._host = host
        self._on_applied = on_applied
        self._gossipsub: GossipSub | None = None
        self._pubsub: Pubsub | None = None
        self._nursery: trio.Nursery | None = None
        self._sites: dict[str, object] = {}  # site address -> site object, sites we want subscribed
        self._cancel_scopes: dict[str, trio.CancelScope] = {}

    @staticmethod
    def topicFor(site_address: str) -> str:
        return "%s/%s" % (TOPIC_PREFIX, site_address)

    def subscribeSite(self, site) -> None:
        """Record that `site` should be subscribed, and start the
        subscription in the background immediately if gossip is already
        running -- otherwise run() picks it up on startup."""
        self._sites[site.address] = site
        if self._nursery is not None:
            self._nursery.start_soon(self._subscribe, site)

    def unsubscribeSite(self, site_address: str) -> None:
        """Symmetric with subscribeSite(): drop `site_address` from the
        wanted set and, if it was actually subscribed, cancel its
        consumer loop and leave the topic."""
        self._sites.pop(site_address, None)
        scope = self._cancel_scopes.pop(site_address, None)
        if scope is not None:
            scope.cancel()
        if self._pubsub is not None and self._nursery is not None:
            self._nursery.start_soon(self._pubsub.unsubscribe, self.topicFor(site_address))

    async def publish(self, site_address: str, body: bytes) -> None:
        if self._pubsub is None:
            return
        await self._pubsub.publish(self.topicFor(site_address), body)

    async def _subscribe(self, site) -> None:
        with trio.CancelScope() as scope:
            self._cancel_scopes[site.address] = scope
            topic = self.topicFor(site.address)
            subscription = await self._pubsub.subscribe(topic)
            self._pubsub.set_topic_validator(topic, gossip_update.make_validator(site), False)
            await gossip_update.consume(site, subscription, on_applied=self._on_applied)

    @asynccontextmanager
    async def run(self):
        """Async context manager: `async with gossip_manager.run(): ...`"""
        self._gossipsub = GossipSub(
            protocols=list(GOSSIPSUB_PROTOCOLS),
            degree=DEGREE,
            degree_low=DEGREE_LOW,
            degree_high=DEGREE_HIGH,
            heartbeat_interval=HEARTBEAT_INTERVAL,
        )
        self._pubsub = Pubsub(self._host.raw, self._gossipsub, strict_signing=False)
        try:
            async with AsyncExitStack() as stack:
                await stack.enter_async_context(background_trio_service(self._gossipsub))
                await stack.enter_async_context(background_trio_service(self._pubsub))
                await self._pubsub.wait_until_ready()
                async with trio.open_nursery() as nursery:
                    self._nursery = nursery
                    for site in list(self._sites.values()):
                        nursery.start_soon(self._subscribe, site)
                    try:
                        yield
                    finally:
                        nursery.cancel_scope.cancel()
        finally:
            self._nursery = None
            self._gossipsub = None
            self._pubsub = None
            self._cancel_scopes.clear()
