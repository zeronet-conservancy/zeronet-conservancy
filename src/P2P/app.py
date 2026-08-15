"""Trio-native application entrypoint -- wires the ported P2P stack
(Host/FileServer/UiServer/SiteAnnouncer/DHT) into one running process.
This is the "everything wires together into one trio-native main.py in a
single cutover step" milestone the plan held open pending Phase 7's UI
work -- but scoped honestly, not a wholesale replacement of src/main.py.

Deliberately NOT a replacement for src/main.py + Actions.py: those still
own everything this stack hasn't absorbed yet -- SiteManager (multi-site
bookkeeping beyond a flat address list: added/downloaded tracking, size
limits, favorites), User/UserManager (auth, certificates, multi-user
sessions), Db.py-backed querying, the ~20 CLI actions (siteCreate/
siteSign/siteVerify/dbRebuild/etc.), and Tor/plugin loading. Running this
alongside the legacy entrypoint in the SAME process is not supported: this
module never imports gevent, and per P2P/compat.py's own docstring, trio
and a gevent-monkey-patched process can't coexist reliably for anything
but brief, tightly-bracketed calls -- so this runs as its OWN process
(a separate `python -m P2P.app` invocation), not embedded inside
src/main.py's.

Site loading here is intentionally minimal: a flat list of addresses read
from private/sites.json's keys (the same file SiteManager reads), each
mapped to data_dir/<address> as its site_root, exactly like the original's
own convention. No per-site settings/tracking beyond what P2P.Site.Site
itself already holds (permissions, wrapper_key/ajax_key, peer table).

Per-site announce loops are simple fixed-interval polling (default 30
minutes, matching the original's ANNOUNCE_INTERVAL default order of
magnitude) -- not the original's event-driven "announce on new site add /
peer count drop / needFile miss" triggers, which need WorkerManager and
UI-event plumbing this module doesn't own.
"""
import json
import logging
import pathlib
from contextlib import AsyncExitStack

import trio

from .FileServer import FileServer
from .Site import Site
from .SiteAnnouncer import SiteAnnouncer
from .Ui.UiServer import UiServer
from .discovery.kaddht import KadDHTDiscovery

log = logging.getLogger(__name__)

DEFAULT_ANNOUNCE_INTERVAL = 30 * 60.0


def loadSiteAddresses(data_dir: pathlib.Path) -> list[str]:
    sites_json = data_dir / "sites.json"
    try:
        with sites_json.open() as f:
            return list(json.load(f).keys())
    except FileNotFoundError:
        return []


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
    ):
        self.data_dir = data_dir
        self.announce_interval = announce_interval
        self.sites: dict[str, Site] = {}
        self.announcers: dict[str, SiteAnnouncer] = {}

        p2p_dir = data_dir / ".p2p"
        p2p_dir.mkdir(parents=True, exist_ok=True)
        self.file_server = FileServer(p2p_dir, tcp_port=tcp_port, ws_port=ws_port)
        self.ui_server = UiServer(self.sites, host=ui_host, port=ui_port, allowed_hosts=ui_allowed_hosts)
        self.dht_discovery = None
        if enable_dht:
            kwargs = {} if dht_protocol_prefix is None else {"protocol_prefix": dht_protocol_prefix}
            self.dht_discovery = KadDHTDiscovery(self.file_server.host, **kwargs)

    def loadSites(self) -> None:
        for address in loadSiteAddresses(self.data_dir):
            self.addSite(address)

    def addSite(self, address: str) -> Site:
        site = Site(address, self.data_dir / address)
        self.sites[address] = site
        self.file_server.addSite(site)
        self.announcers[address] = SiteAnnouncer(site, self.file_server, dht_discovery=self.dht_discovery)
        return site

    async def _announceLoop(self, address: str) -> None:
        announcer = self.announcers[address]
        while True:
            try:
                await announcer.announce(force=True)
            except Exception:
                log.exception("Announce failed for %s", address)
            await trio.sleep(self.announce_interval)

    async def run(self) -> None:
        """Runs forever (until cancelled) -- boots the host, UI server, and
        (if enabled) DHT discovery, then keeps one announce loop alive per
        loaded site."""
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
                for address in list(self.sites):
                    nursery.start_soon(self._announceLoop, address)
                await trio.sleep_forever()


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

    app = App(
        args.data_dir,
        tcp_port=args.tcp_port,
        ws_port=args.ws_port,
        ui_host=args.ui_host,
        ui_port=args.ui_port,
        enable_dht=not args.no_dht,
    )
    app.loadSites()
    trio.run(app.run)


if __name__ == "__main__":
    main()
