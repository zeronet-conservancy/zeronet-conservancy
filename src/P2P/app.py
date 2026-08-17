"""Trio-native application entrypoint -- wires the ported P2P stack
(Host/FileServer/UiServer/SiteAnnouncer/DHT/SiteManager) into one running
process. This is the "everything wires together into one trio-native
main.py in a single cutover step" milestone the plan held open pending
Phase 7's UI work -- but scoped honestly, not a wholesale replacement of
src/main.py.

Deliberately NOT a replacement for src/main.py + Actions.py: those still
own the legacy plugin ecosystem under repo-root plugins/ (see
P2P/plugins/__init__.py for why that's a separate, non-overlapping set
from this stack's own P2P/plugins/). Tor is now also covered here, via
P2P.Tor.TorManager (enable_tor=True) -- control-port only (onion service
create/remove); TorManager's own module docstring has what's still not
ported (dialing out through Tor's SOCKS5 proxy). UPnP port mapping
(enable_upnp=True, the default) uses py-libp2p's own trio-native
UpnpManager (libp2p.discovery.upnp.upnp, backed by the miniupnpc
library) directly -- no separate port needed, since the original
zeronet's UpnpPunch.py-equivalent functionality already ships in the
libp2p dependency this stack is built on. Db.py-backed querying
and the CLI
actions (siteCreate/siteSign/siteVerify/dbRebuild/etc.) ARE covered now,
in P2P.Db/P2P.SiteStorage and P2P/actions.py respectively. Running this
alongside the legacy entrypoint in the SAME process is not supported:
this module never imports gevent, and per P2P/compat.py's own docstring,
trio and a gevent-monkey-patched process can't coexist reliably for
anything but brief, tightly-bracketed calls -- so this runs as its OWN
process, launched via `python -m P2P app ...` (see P2P/__main__.py for
why that's the real entrypoint, not `python -m P2P.app` directly), not
embedded inside src/main.py's.

Site loading/persistence is now real (P2P.SiteManager), not the flat
address-list stub this module used before that existed -- see
SiteManager.py's own docstring for what it in turn still doesn't cover
(size-limit enforcement, download-on-add, domain resolution).

User/UserManager (P2P.User/P2P.UserManager) are also wired in now --
loaded from the same private_dir as sites.json -- but nothing in the UI
command surface (P2P/Ui/commands.py) uses them yet for real
authentication/cert flows; that's still bucket 3 territory (see
UiServer.py's own module docstring) and stays explicitly deferred.

Per-site announce loops are simple fixed-interval polling (default 30
minutes, matching the original's ANNOUNCE_INTERVAL default order of
magnitude). New sites added through the native UI are also wired into the
file server/announcer registries and receive one immediate best-effort
announce; peer-count-drop and needFile-triggered announces still need the
remaining WorkerManager/UI-event plumbing.
"""
import logging
import pathlib
from contextlib import AsyncExitStack

import trio
from libp2p.discovery.upnp.upnp import UpnpManager

from .FileServer import FileServer
from .Site import Site
from .SiteAnnouncer import SiteAnnouncer
from .SiteManager import SiteManager
from .Tor import TorManager
from .UserManager import UserManager
from .Ui.UiServer import UiServer
from .discovery.kaddht import KadDHTDiscovery
from .discovery.local import LocalAnnouncer

log = logging.getLogger(__name__)

DEFAULT_ANNOUNCE_INTERVAL = 30 * 60.0
DEFAULT_SAVE_INTERVAL = 10 * 60.0


class App:
    def __init__(
        self,
        data_dir: pathlib.Path,
        tcp_port: int = 0,
        ws_port: int | None = 0,
        ui_host: str = "127.0.0.1",
        ui_port: int = 0,
        ui_allowed_hosts: list | None = None,
        enable_dht: bool = True,
        dht_protocol_prefix: str | None = None,
        enable_local_discovery: bool = True,
        announce_interval: float = DEFAULT_ANNOUNCE_INTERVAL,
        save_interval: float = DEFAULT_SAVE_INTERVAL,
        enable_tor: bool = False,
        tor_control_ip: str = "127.0.0.1",
        tor_control_port: int = 9051,
        tor_socks_port: int = 9050,
        tor_password: str | None = None,
        enable_upnp: bool = True,
        homepage: str | None = None,
        auto_download_timeout: float = 15.0,
        ui_password: str | None = None,
        multiuser: bool = False,
    ):
        self.data_dir = data_dir
        self.announce_interval = announce_interval
        self.save_interval = save_interval
        self.announcers: dict[str, SiteAnnouncer] = {}
        self._enable_tor = enable_tor
        self._tor_control_ip = tor_control_ip
        self._tor_control_port = tor_control_port
        self._tor_password = tor_password
        self._tor_socks_port = tor_socks_port
        self.tor_manager: TorManager | None = None
        self._enable_upnp = enable_upnp
        self.upnp_manager: UpnpManager | None = None
        self._upnp_port: int | None = None
        self._shutdown_event = None

        p2p_dir = data_dir / ".p2p"
        p2p_dir.mkdir(parents=True, exist_ok=True)
        tor_proxy = (tor_control_ip, tor_socks_port) if enable_tor else None
        self.file_server = FileServer(p2p_dir, tcp_port=tcp_port, ws_port=ws_port, tor_socks_proxy=tor_proxy)
        self.site_manager = SiteManager(data_dir)
        self.user_manager = UserManager(data_dir, multiuser=multiuser)
        # UiServer shares SiteManager's own sites dict by reference, so
        # anything added/removed via site_manager (load(), add(), delete())
        # is immediately visible to the UI/websocket layer with no separate
        # sync step needed.
        self.ui_server = UiServer(
            self.site_manager.sites, host=ui_host, port=ui_port, allowed_hosts=ui_allowed_hosts,
            site_manager=self.site_manager, user_manager=self.user_manager, file_server=self.file_server,
            announcers=self.announcers, homepage=homepage, on_missing_site=self.addSite,
            auto_download_timeout=auto_download_timeout, data_dir=data_dir,
            shutdown_callback=self.requestShutdown,
            # None (not self._setupUpnp) when --no-upnp was passed -- a
            # manual "re-check port" click shouldn't silently re-attempt
            # UPnP for someone who deliberately disabled it.
            port_recheck_callback=self._setupUpnp if enable_upnp else None,
            ui_password=ui_password,
        )
        self.ui_server.app.upnp_port = None
        self.ui_server.app.ip_external = None
        # A peer pushing us a fresh content.json (protocols/update.py) is
        # genuinely network-driven, unlike UiApp.broadcast()'s other four
        # call sites (sitePublish/sitePause/siteResume/siteUpdate, all
        # user-initiated from this same process) -- see update.py's own
        # docstring on why this threads through as a late-bound attribute
        # rather than a FileServer constructor param.
        self.file_server.on_update_applied = lambda site, inner_path: self.ui_server.app.broadcast(
            "siteChanged", site, {"event": "updated"}
        )
        self.dht_discovery = None
        if enable_dht:
            kwargs = {} if dht_protocol_prefix is None else {"protocol_prefix": dht_protocol_prefix}
            self.dht_discovery = KadDHTDiscovery(self.file_server.host, **kwargs)
        # session.app in P2P/Ui/commands.py is ui_server.app (the UiApp
        # instance), not ui_server itself -- this used to set the wrong
        # object, so every dht*-family command always saw dht_discovery as
        # None (UiApp's own __init__ default) even with DHT running.
        self.ui_server.app.dht_discovery = self.dht_discovery

        self.local_announcer = None
        if enable_local_discovery:
            # Shares site_manager.sites by reference, same "no separate
            # sync step" reasoning as UiServer's own sites dict above --
            # LocalAnnouncer.discover() always sees whatever's currently
            # loaded, no matter when a site is added/removed.
            self.local_announcer = LocalAnnouncer(self.file_server.host, self.site_manager.sites)

    @property
    def sites(self) -> dict[str, Site]:
        return self.site_manager.sites

    def _wireSite(self, site: Site) -> None:
        self.file_server.addSite(site)
        self.announcers[site.address] = SiteAnnouncer(
            site, self.file_server, dht_discovery=self.dht_discovery, local_announcer=self.local_announcer,
        )

    async def loadSites(self) -> None:
        """Loads every site listed in data_dir/sites.json via SiteManager
        and wires each one into the file server + announcers. Not called
        automatically by run() -- calling it after manually add()-ing a
        site would cleanup-delete that site if sites.json doesn't already
        list it, so this stays an explicit, separate step."""
        await self.site_manager.load()
        for site in self.site_manager.sites.values():
            self._wireSite(site)

    def addSite(self, address: str, own: bool = False):
        site = self.site_manager.add(address, own=own)
        if site:
            self._wireSite(site)
        return site

    def deleteSite(self, address: str) -> None:
        """Remove a site from persistence and every live P2P wiring table."""
        self.site_manager.delete(address)
        self.file_server.removeSite(address)
        self.announcers.pop(address, None)

    async def loadUsers(self) -> None:
        await self.user_manager.load()

    async def getOrCreateUser(self):
        """Single-user-mode convenience matching Actions.siteCreate's own
        UserManager.get()-or-create() pattern."""
        user = await self.user_manager.get()
        if user is None:
            user = self.user_manager.create()
        return user

    async def _announceLoop(self, address: str) -> None:
        announcer = self.announcers[address]
        while True:
            try:
                await announcer.announce(force=True)
            except Exception:
                log.exception("Announce failed for %s", address)
            await trio.sleep(self.announce_interval)

    async def _announceOnce(self, address: str) -> None:
        announcer = self.announcers.get(address)
        if announcer is None:
            return
        try:
            await announcer.announce(force=True)
        except Exception:
            log.exception("Initial announce failed for %s", address)

    def requestShutdown(self) -> None:
        """Request a graceful exit from the native app run loop."""
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    async def _saveLoop(self) -> None:
        while True:
            await trio.sleep(self.save_interval)
            try:
                await self.site_manager.save()
            except Exception:
                log.exception("Saving sites.json failed")

    async def _connectTor(self) -> None:
        """Connects the Tor control port after the real fileserver TCP
        port is known (tcp_port=0 at construction means an OS-assigned
        ephemeral port, only resolvable once the host has actually bound
        -- see P2P.Host.get_addrs()). Best-effort: a failed connect
        disables tor_manager.enabled and logs a warning, same graceful
        degradation as the original TorManager.start()'s own fallback,
        rather than crashing the whole app over an unreachable/absent
        Tor daemon."""
        tcp_addrs = [addr for addr in self.file_server.host.get_addrs() if "/ws" not in str(addr)]
        fileserver_port = int(tcp_addrs[0].value_for_protocol("tcp")) if tcp_addrs else 0
        self.tor_manager = TorManager(
            control_ip=self._tor_control_ip, control_port=self._tor_control_port,
            fileserver_port=fileserver_port, password=self._tor_password,
        )
        if not await self.tor_manager.connect():
            log.warning("Tor control port connect failed (%s) -- continuing without Tor", self.tor_manager.status)
        self.ui_server.app.tor_manager = self.tor_manager

    async def _setupUpnp(self) -> None:
        """Maps the real fileserver TCP port on the LAN gateway via UPnP,
        same "resolve the real bound port before using it" reasoning as
        _connectTor() (tcp_port=0 at construction is only resolvable once
        the host has actually bound). Unlike _connectTor(), this runs as a
        background task inside run()'s own nursery rather than being
        awaited before it -- real SSDP discovery can take a couple of
        seconds, and gating "P2P app running" (and the very first announce)
        on it would slow down startup for a mapping that's a pure
        convenience. Best-effort throughout regardless: no UPnP-capable
        gateway on the network (the common case in CI/sandboxed/cloud
        environments) is not an error -- discover() itself already returns
        False rather than raising in that case, and a failed/skipped
        mapping just means peers reach this node the same way they would
        without UPnP at all (manual port forward, or simply being
        reachable directly)."""
        tcp_addrs = [addr for addr in self.file_server.host.get_addrs() if "/ws" not in str(addr)]
        if not tcp_addrs:
            self.ui_server.app.ip_external = False
            return
        port = int(tcp_addrs[0].value_for_protocol("tcp"))

        self.upnp_manager = UpnpManager()
        if not await self.upnp_manager.discover():
            log.warning("UPnP gateway discovery failed -- continuing without a port mapping")
            self.ui_server.app.ip_external = False
            return
        if await self.upnp_manager.add_port_mapping(port, "TCP"):
            self._upnp_port = port
            # Surfaced through serverInfo as ip_external/port_opened -- see
            # formatServerInfo()'s own docstring in P2P/Ui/commands.py for
            # why a successful UPnP mapping is the only reachability signal
            # this stack has (no self-test-via-peer check exists here).
            #
            # ip_external is what the real ZeroHello dashboard.js's header
            # PORT badge actually reads (Dashboard.render(), line ~2305),
            # and it does a *strict* `=== true`/`=== null` check there --
            # `null` means "still checking" (the initial value, set at
            # __init__), `true` means opened, anything else (including a
            # real IP string, which is truthy but not `=== true`) reads as
            # closed. So this has to be the literal boolean, not
            # get_external_ip()'s actual IP string, even though a real IP
            # would be more informative -- found live, the badge stayed on
            # "Closed" with a genuinely successful mapping until this was
            # narrowed to bool. port_opened only feeds the port-badge
            # dropdown's separate IPv4/IPv6 detail line (handlePortClick(),
            # line ~2088), which does use ip_external's *truthiness*, so it
            # stays correct either way.
            self.ui_server.app.upnp_port = port
            self.ui_server.app.ip_external = True
        else:
            log.warning("UPnP port mapping for port %d failed -- continuing without one", port)
            self.ui_server.app.ip_external = False

    async def _teardownUpnp(self) -> None:
        if self.upnp_manager is not None and self._upnp_port is not None:
            await self.upnp_manager.remove_port_mapping(self._upnp_port, "TCP")

    async def run(self) -> None:
        """Runs forever (until cancelled) -- boots the host, UI server, and
        (if enabled) DHT discovery, Tor, and UPnP, then keeps one announce
        loop alive per loaded site plus a periodic sites.json save loop."""
        self._shutdown_event = trio.Event()
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(self.file_server.run())
            await stack.enter_async_context(self.ui_server.run())
            if self.dht_discovery is not None:
                await stack.enter_async_context(self.dht_discovery.run())
            if self.local_announcer is not None:
                await stack.enter_async_context(self.local_announcer.run())
            if self._enable_tor:
                await self._connectTor()
            if self._enable_upnp:
                stack.push_async_callback(self._teardownUpnp)
            else:
                self.ui_server.app.ip_external = False

            log.info(
                "P2P app running: peer_id=%s sites=%d ui=%s",
                self.file_server.host.peer_id, len(self.sites), self.ui_server.bound_addresses,
            )

            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._saveLoop)
                if self._enable_upnp:
                    nursery.start_soon(self._setupUpnp)
                for address in list(self.sites):
                    nursery.start_soon(self._announceLoop, address)
                await self._shutdown_event.wait()
        self._shutdown_event = None


async def _main(args) -> None:
    app = App(
        args.data_dir,
        tcp_port=args.tcp_port,
        ws_port=args.ws_port,
        ui_host=args.ui_host,
        ui_port=args.ui_port,
        enable_dht=not args.no_dht,
        enable_local_discovery=not args.no_local_discovery,
        enable_tor=args.tor,
        tor_control_port=args.tor_control_port,
        tor_password=args.tor_password,
        enable_upnp=not args.no_upnp,
        ui_password=args.ui_password,
        multiuser=args.multiuser,
    )
    await app.loadSites()
    await app.loadUsers()
    await app.run()


def main() -> None:
    """Prefer `python -m P2P app --data-dir ...` (see P2P/__main__.py) --
    that loads plugins before this module's own top-level imports run,
    which calling this function directly can't do. `python -m P2P.app
    --data-dir ...` still works, just without any plugins active."""
    import argparse

    parser = argparse.ArgumentParser(description="zeronet-conservancy trio-native P2P app")
    parser.add_argument("--data-dir", type=pathlib.Path, required=True)
    parser.add_argument("--tcp-port", type=int, default=0)
    parser.add_argument("--ws-port", type=int, default=0)
    parser.add_argument("--ui-host", default="127.0.0.1")
    parser.add_argument("--ui-port", type=int, default=43110)
    parser.add_argument("--no-dht", action="store_true")
    parser.add_argument("--no-local-discovery", action="store_true")
    parser.add_argument("--tor", action="store_true", help="Connect to a local Tor control port and run an onion service")
    parser.add_argument("--tor-control-port", type=int, default=9051)
    parser.add_argument("--tor-socks-port", type=int, default=9050)
    parser.add_argument("--tor-password", default=None)
    parser.add_argument("--no-upnp", action="store_true", help="Don't try to map the fileserver port on the LAN gateway via UPnP")
    parser.add_argument("--ui-password", default=None, help="Password to access the web UI")
    parser.add_argument("--multiuser", action="store_true", help="Each visiting browser gets its own account")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    trio.run(_main, args)


if __name__ == "__main__":
    main()
