import time
import weakref
import gevent

class ConnectRequirement(object):
    next_id = 1
    def __init__(self, need_nr_peers, need_nr_connected_peers, expiration_interval=None):
        self.need_nr_peers = need_nr_peers # how many total peers we need
        self.need_nr_connected_peers = need_nr_connected_peers # how many connected peers we need
        self.result = gevent.event.AsyncResult() # resolves on need_nr_peers condition
        self.result_connected = gevent.event.AsyncResult() # resolves on need_nr_connected_peers condition

        self.expiration_interval = expiration_interval
        self.expired = False
        if expiration_interval:
            self.expire_at = time.time() + expiration_interval
        else:
            self.expire_at = None

        self.nr_peers = -1 # updated PeerConnector()
        self.nr_connected_peers = -1 # updated PeerConnector()

        self.heartbeat = gevent.event.AsyncResult()

        self.id = type(self).next_id
        type(self).next_id += 1

    def fulfilled(self):
        return self.result.ready() and self.result_connected.ready()

    def ready(self):
        return self.expired or self.fulfilled()

    # Heartbeat send when any of the following happens:
    # * self.result is set
    # * self.result_connected is set
    # * self.nr_peers changed
    # * self.nr_peers_connected changed
    # * self.expired is set
    def waitHeartbeat(self, timeout=None):
        if self.heartbeat.ready():
            self.heartbeat = gevent.event.AsyncResult()
        return self.heartbeat.wait(timeout=timeout)

    def sendHeartbeat(self):
        self.heartbeat.set_result()
        if self.heartbeat.ready():
            self.heartbeat = gevent.event.AsyncResult()

class PeerConnector(object):

    def __init__(self, site):
        self.site = site

        self.peer_reqs = weakref.WeakValueDictionary() # How many connected peers we need.
                                                       # Separate entry for each requirement.
                                                       # Objects of type ConnectRequirement.
        self.peer_connector_controller = None # Thread doing the orchestration in background.
        self.peer_connector_workers = dict()  # Threads trying to connect to individual peers.
        self.peer_connector_worker_limit = 5  # Max nr of workers.
        self.peer_connector_announcer = None  # Thread doing announces in background.

        # Max effective values. Set by processReqs().
        self.need_nr_peers = 0
        self.need_nr_connected_peers = 0
        self.nr_peers = 0 # set by processReqs()
        self.nr_connected_peers = 0 # set by processReqs2()

        self.peers = list()

    def addReq(self, req):
        self.peer_reqs[req.id] = req
        self.processReqs()

    def newReq(self, need_nr_peers, need_nr_connected_peers, expiration_interval=None):
        req = ConnectRequirement(need_nr_peers, need_nr_connected_peers, expiration_interval=expiration_interval)
        self.addReq(req)
        return req

    def processReqs(self, nr_connected_peers=None):
        nr_peers = len(self.site.peers)
        self.nr_peers = nr_peers

        need_nr_peers = 0
        need_nr_connected_peers = 0

        items = list(self.peer_reqs.items())
        for key, req in items:
            send_heartbeat = False

            if req.expire_at and req.expire_at < time.time():
                req.expired = True
                self.peer_reqs.pop(key, None)
                send_heartbeat = True
            elif req.result.ready() and req.result_connected.ready():
                pass
            else:
                if nr_connected_peers is not None:
                    if req.need_nr_peers <= nr_peers and req.need_nr_connected_peers <= nr_connected_peers:
                        req.result.set_result(nr_peers)
                        req.result_connected.set_result(nr_connected_peers)
                        send_heartbeat = True
                    if req.nr_peers != nr_peers or req.nr_connected_peers != nr_connected_peers:
                        req.nr_peers = nr_peers
                        req.nr_connected_peers = nr_connected_peers
                        send_heartbeat = True

                if not (req.result.ready() and req.result_connected.ready()):
                    need_nr_peers = max(need_nr_peers, req.need_nr_peers)
                    need_nr_connected_peers = max(need_nr_connected_peers, req.need_nr_connected_peers)

            if send_heartbeat:
                req.sendHeartbeat()

        self.need_nr_peers = need_nr_peers
        self.need_nr_connected_peers = need_nr_connected_peers

        if nr_connected_peers is None:
            nr_connected_peers = 0
        if need_nr_peers > nr_peers:
            self.spawnPeerConnectorAnnouncer();
        if need_nr_connected_peers > nr_connected_peers:
            self.spawnPeerConnectorController();

    def processReqs2(self):
        self.nr_connected_peers = len(self.site.getConnectedPeers(onlyFullyConnected=True))
        self.processReqs(nr_connected_peers=self.nr_connected_peers)

    # For adding new peers when ConnectorController is working.
    # While it is iterating over a cached list of peers, there can be a significant lag
    # for a newly discovered peer to get in sight of the controller.
    # Suppose most previously known peers are dead and we've just get a few
    # new peers from a tracker.
    # So we mix the new peer to the cached list.
    # When ConnectorController is stopped (self.peers is empty), we just do nothing here.
    def addPeer(self, peer):
        if not self.peers:
            return
        if peer not in self.peers:
            self.peers.append(peer)

    def keepGoing(self):
        return self.site.isServing() and self.site.connection_server.allowsCreatingConnections()

    def peerConnectorWorker(self, peer):
        if not peer.isConnected():
            peer.connect()
        if peer.isConnected():
            self.processReqs2()

    def peerConnectorController(self):
        self.peers = list()
        addendum = 20
        while self.keepGoing():

            if len(self.site.peers) < 1:
                # No peers and no way to manage this from this method.
                # Just give up.
                break

            self.processReqs2()

            if self.need_nr_connected_peers <= self.nr_connected_peers:
                # Ok, nobody waits for connected peers.
                # Done.
                break

            if len(self.peers) < 1:
                # refill the peer list
                self.peers = self.site.getRecentPeers(self.need_nr_connected_peers * 2 + addendum)
                addendum = addendum * 2 + 50
                if len(self.peers) <= self.nr_connected_peers:
                    # looks like all known peers are connected
                    # start announcePex() in background and give up
                    self.site.announcer.announcePex()
                    break

            # try connecting to peers
            while self.keepGoing() and len(self.peer_connector_workers) < self.peer_connector_worker_limit:
                if len(self.peers) < 1:
                    break

                peer = self.peers.pop(0)

                if peer.isConnected():
                    continue

                thread = self.peer_connector_workers.get(peer, None)
                if thread:
                    continue

                thread = self.site.spawn(self.peerConnectorWorker, peer)
                self.peer_connector_workers[peer] = thread
                thread.link(lambda thread, peer=peer: self.peer_connector_workers.pop(peer, None))

            # wait for more room in self.peer_connector_workers
            while self.keepGoing() and len(self.peer_connector_workers) >= self.peer_connector_worker_limit:
                gevent.sleep(2)

        self.peers = list()
        self.peer_connector_controller = None

    def peerConnectorAnnouncer(self):
        while self.keepGoing():
            if self.need_nr_peers <= self.nr_peers:
                break
            self.site.announce(mode="more")
            self.processReqs2()
            if self.need_nr_peers <= self.nr_peers:
                break
            gevent.sleep(10)
        self.peer_connector_announcer = None

    def spawnPeerConnectorController(self):
        if self.peer_connector_controller is None or self.peer_connector_controller.ready():
            self.peer_connector_controller = self.site.spawn(self.peerConnectorController)

    def spawnPeerConnectorAnnouncer(self):
        if self.peer_connector_announcer is None or self.peer_connector_announcer.ready():
            self.peer_connector_announcer = self.site.spawn(self.peerConnectorAnnouncer)
