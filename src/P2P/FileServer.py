"""Async replacement for File/FileServer.py, backed by a P2P.Host instead
of subclassing ConnectionServer.

Scoped to what's genuinely independent of Site.py (not yet ported): host
lifecycle, protocol registration, and routing incoming requests to the
right site. FileServer.py's periodic maintenance loops -- checkSites,
cleanupSites, announceSites, wakeupWatcher, portCheck -- all operate on
real Site objects (site.isServing()/.announce()/.update()/.addPeer()) and
land once Site.py itself does; porting them now against methods that don't
exist yet would just be untestable stub code.

Sites are held behind a small duck-typed interface (address, storage,
isServing(), getConnectablePeers(), addPeer()) matching Site.py's real
method signatures, so the real Site class slots in here unchanged --
addSite()/removeSite() don't care what "site" actually is.
"""
import pathlib

from .Host import Host
from .ConnectionPolicy import ConnectionPolicy
from .ProtocolRouter import ProtocolRouter
from .protocols import getfile, pex, ping, update


class FileServer:
    def __init__(self, data_dir: pathlib.Path, tcp_port: int = 0, ws_port: int | None = 0,
                 enable_relay_hop: bool = False):
        self.host = Host(data_dir, tcp_port=tcp_port, ws_port=ws_port, enable_relay_hop=enable_relay_hop)
        self.connection_policy = ConnectionPolicy(self.host)
        self.router = ProtocolRouter(self.host)
        self.sites: dict = {}  # site address -> site object

        self._registerProtocols()

    def _registerProtocols(self) -> None:
        self.router.register(ping.PROTOCOL_ID, ping.handle)
        self.router.register(getfile.PROTOCOL_ID, getfile.make_handler(self._resolveSiteStorage))
        self.router.register(pex.PROTOCOL_ID, pex.make_handler(self._knownPeersForSite, self._onPeerReceived))
        self.router.register(update.PROTOCOL_ID, update.make_handler(self._resolveSite))

    def _resolveSiteStorage(self, site_address: str):
        site = self.sites.get(site_address)
        if site is None or not site.isServing():
            return None
        return site.storage

    def _resolveSite(self, site_address: str):
        site = self.sites.get(site_address)
        if site is None or not site.isServing():
            return None
        return site

    def _knownPeersForSite(self, site_address: str, exclude: set, limit: int) -> list:
        site = self.sites.get(site_address)
        if site is None:
            return []
        peers = site.getConnectablePeers(need_num=limit, exclude=exclude)
        return [{"peer_id": peer.peer_id.to_base58(), "ip": peer.ip, "port": peer.port} for peer in peers]

    def _onPeerReceived(self, site_address: str, peer_id, ip: str, port: int) -> None:
        site = self.sites.get(site_address)
        if site is not None:
            site.addPeer(peer_id, ip, port, source="pex")

    def addSite(self, site) -> None:
        self.sites[site.address] = site

    def removeSite(self, site_address: str) -> None:
        self.sites.pop(site_address, None)

    def run(self):
        """Async context manager: `async with file_server.run(): ...`"""
        return self.host.run()
