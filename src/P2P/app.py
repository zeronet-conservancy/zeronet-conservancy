"""Trio-native application entrypoint -- wires the ported P2P stack
(Host/FileServer/UiServer/SiteAnnouncer/DHT/SiteManager) into one running
process. This is the "everything wires together into one trio-native
main.py in a single cutover step" milestone the plan held open pending
Phase 7's UI work -- but scoped honestly, not a wholesale replacement of
src/main.py.

Deliberately NOT a replacement for src/main.py + Actions.py: those still
own everything this stack hasn't absorbed yet -- User/UserManager (auth,
certificates, multi-user sessions), Db.py-backed querying, the ~20 CLI
actions (siteCreate/siteSign/siteVerify/dbRebuild/etc.), and Tor/plugin
loading. Running this alongside the legacy entrypoint in the SAME process
is not supported: this module never imports gevent, and per
P2P/compat.py's own docstring, trio and a gevent-monkey-patched process
can't coexist reliably for anything but brief, tightly-bracketed calls --
so this runs as its OWN process (a separate `python -m P2P.app`
invocation), not embedded inside src/main.py's.

Site loading/persistence is now real (P2P.SiteManager), not the flat
address-list stub this module used before that existed -- see
SiteManager.py's own docstring for what it in turn still doesn't cover
(size-limit enforcement, download-on-add, domain resolution).

Per-site announce loops are simple fixed-interval polling (default 30
minutes, matching the original's ANNOUNCE_INTERVAL default order of
magnitude) -- not the original's event-driven "announce on new site add /
peer count drop / needFile miss" triggers, which need WorkerManager and
UI-event plumbing this module doesn't own.
"""
import logging
import pathlib
from contextlib import AsyncExitStack

import trio

from .FileServer import FileServer
from .Site import Site
from .SiteAnnouncer import SiteAnnouncer
from .SiteManager import SiteManager
from .Ui.UiServer import UiServer
from .discovery.kaddht import KadDHTDiscovery

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
        announce_interval: float = DEFAULT_ANNOUNCE_INTERVAL,
        save_interval: float = DEFAULT_SAVE_INTERVAL,
    ):
        self.data_dir = data_dir
        self.announce_interval = announce_interval
        self.save_interval = save_interval
        self.announcers: dict[str, SiteAnnouncer] = {}

        p2p_dir = data_dir / ".p2p"
        p2p_dir.mkdir(parents=True, exist_ok=True)
        self.file_server = FileServer(p2p_dir, tcp_port=tcp_port, ws_port=ws_port)
        self.site_manager = SiteManager(data_dir)
        # UiServer shares SiteManager's own sites dict by reference, so
        # anything added/removed via site_manager (load(), add(), delete())
        # is immediately visible to the UI/websocket layer with no separate
        # sync step needed.
        self.ui_server = UiServer(self.site_manager.sites, host=ui_host, port=ui_port, allowed_hosts=ui_allowed_hosts)
        self.dht_discovery = None
        if enable_dht:
            kwargs = {} if dht_protocol_prefix is None else {"protocol_prefix": dht_protocol_prefix}
            self.dht_discovery = KadDHTDiscovery(self.file_server.host, **kwargs)

    @property
    def sites(self) -> dict[str, Site]:
        return self.site_manager.sites

    def _wireSite(self, site: Site) -> None:
        self.file_server.addSite(site)
        self.announcers[site.address] = SiteAnnouncer(site, self.file_server, dht_discovery=self.dht_discovery)

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

    async def _announceLoop(self, address: str) -> None:
        announcer = self.announcers[address]
        while True:
            try:
                await announcer.announce(force=True)
            except Exception:
                log.exception("Announce failed for %s", address)
            await trio.sleep(self.announce_interval)

    async def _saveLoop(self) -> None:
        while True:
            await trio.sleep(self.save_interval)
            try:
                await self.site_manager.save()
            except Exception:
                log.exception("Saving sites.json failed")

    async def run(self) -> None:
        """Runs forever (until cancelled) -- boots the host, UI server, and
        (if enabled) DHT discovery, then keeps one announce loop alive per
        loaded site plus a periodic sites.json save loop."""
        async with AsyncExitStack() as stack:
            await stack.enter_async_context(self.file_server.run())
            await stack.enter_async_context(self.ui_server.run())
            if self.dht_discovery is not None:
                await stack.enter_async_context(self.dht_discovery.run())

            log.info(
                "P2P app running: peer_id=%s sites=%d ui=%s",
                self.file_server.host.peer_id, len(self.sites), self.ui_server.bound_addresses,
            )

            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._saveLoop)
                for address in list(self.sites):
                    nursery.start_soon(self._announceLoop, address)
                await trio.sleep_forever()


async def _main(args) -> None:
    app = App(
        args.data_dir,
        tcp_port=args.tcp_port,
        ws_port=args.ws_port,
        ui_host=args.ui_host,
        ui_port=args.ui_port,
        enable_dht=not args.no_dht,
    )
    await app.loadSites()
    await app.run()


def main() -> None:
    """`python -m P2P.app --data-dir ...` -- a standalone process, not
    something src/main.py imports (see module docstring)."""
    import argparse

    parser = argparse.ArgumentParser(description="zeronet-conservancy trio-native P2P app")
    parser.add_argument("--data-dir", type=pathlib.Path, required=True)
    parser.add_argument("--tcp-port", type=int, default=0)
    parser.add_argument("--ws-port", type=int, default=0)
    parser.add_argument("--ui-host", default="127.0.0.1")
    parser.add_argument("--ui-port", type=int, default=43110)
    parser.add_argument("--no-dht", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    trio.run(_main, args)


if __name__ == "__main__":
    main()
