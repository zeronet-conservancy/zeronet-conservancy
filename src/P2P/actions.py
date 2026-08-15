"""Trio port of Actions.py's CLI commands: both the local-state-only slice
(SiteManager/UserManager/ContentManager/SiteStorage, no networking) and
the networking-dependent ones (siteAnnounce/siteDownload/siteNeedFile/
peerPing/peerGetFile/peerCmd/siteCmd), each opening its own short-lived
networking session rather than requiring a separately-running P2P.app.App
-- matching the original's own "open a simple connection server per
invocation" CLI shape, just on this stack's Host/FileServer/SiteAnnouncer
instead of a raw ConnectionServer.

Local-state commands: siteCreate, siteSign, siteVerify, dbRebuild,
dbQuery, plus the four crypto commands (cryptPrivatekeyToAddress/
cryptSign/cryptVerify/cryptGetPrivatekey, trivial CryptBitcoin wrappers
with no site/network dependency at all).

Networking commands, each via a short-lived _networkSession() (a
FileServer + optional DHT discovery, identity persisted under
data_dir/.p2p so repeated CLI invocations reuse the same peer_id) or
_ephemeralHost() (bare Host, for peer* commands that address a specific
peer directly, not a whole site's swarm):
  - siteAnnounce: announce() (DHT + pex) and report how many peers were
    found.
  - siteDownload: announce(), then WorkerManager.syncSite() -- content.json
    plus every file it lists, fetched and verified from discovered peers.
  - siteNeedFile: announce(), then WorkerManager.Scheduler.needFile() for
    one specific file, written to local storage.
  - peerPing/peerGetFile/peerCmd: connect directly to one already-known
    peer (peer_id + multiaddr -- libp2p addressing needs both, unlike the
    original's bare ip:port) and ping/fetch/send a raw command.
  - siteCmd: connects to an ALREADY-RUNNING App's UI websocket
    (P2P.Ui.UiServer) and sends it a raw command, same as the original.
    Requires wrapper_key as an explicit argument, though -- unlike the
    original (which reads site.settings["wrapper_key"] out of shared
    sites.json), P2P.Site generates a fresh random wrapper_key per
    process and SiteManager doesn't persist it, so a separate CLI process
    has no way to discover a running App's wrapper_key on its own. This
    is a real, currently-unclosed gap between processes, not a design
    choice -- closing it would mean either persisting wrapper_key to
    sites.json (a security-relevant change to what that file exposes) or
    adding an out-of-band discovery channel, neither done here.

Deliberately NOT ported: sitePublish. The original's real path proactively
pushes an "update" notification to already-connected peers (its fallback
path, when it can't reach a local running UI, calls site.publish() which
does this over the wire) -- there is no "update" broadcast protocol in
P2P/protocols/ yet (only getfile/pex/ping), so there's nothing to push
through even with a live networking session. This needs that protocol
built first, not just CLI wiring. Also not ported: importBundle,
getConfig, test, ipythonThread/main (main is P2P.app.main() already).

siteVerify() re-derives its own equivalent of the original's
site.storage.verifyFiles() inline (a hash-check pass over every file
every loaded content.json lists) rather than adding that to
SiteStorage.py -- SiteStorage.py already documents that verifyFiles()
needs ContentManager pieces (hashfield) not ported, and this narrower
version (using ContentManager.verifyFile() directly, no hashfield
bookkeeping) is all a CLI verify command actually needs.
"""
import io
import json
import logging
import pathlib
import time
from contextlib import AsyncExitStack, asynccontextmanager

import trio
import trio_websocket
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from multiaddr import Multiaddr

from Crypt import CryptBitcoin

from .ConnectionPolicy import ConnectionPolicy
from .ContentManager import _getDirname
from .FileServer import FileServer
from .Host import Host
from .Peer import Peer
from .SiteAnnouncer import SiteAnnouncer
from .SiteManager import SiteManager
from .UserManager import UserManager
from .WorkerManager import Scheduler, downloadContentJson, syncSite
from .discovery.kaddht import KadDHTDiscovery

log = logging.getLogger("P2P.actions")


class ActionError(Exception):
    pass


class Actions:
    def __init__(self, data_dir: pathlib.Path):
        self.data_dir = data_dir
        self.site_manager = SiteManager(data_dir)
        self.user_manager = UserManager(data_dir)

    async def _getSite(self, address: str):
        if not self.site_manager.loaded:
            await self.site_manager.load()
        site = await self.site_manager.get(address)
        if site is None:
            raise ActionError("Site not found: %s" % address)
        return site

    async def _getOrCreateUser(self):
        user = await self.user_manager.get()
        if user is None:
            user = self.user_manager.create()
        return user

    @asynccontextmanager
    async def _networkSession(self, site, enable_dht: bool = True):
        p2p_dir = self.data_dir / ".p2p"
        p2p_dir.mkdir(parents=True, exist_ok=True)
        file_server = FileServer(p2p_dir, ws_port=None)
        file_server.addSite(site)
        dht_discovery = KadDHTDiscovery(file_server.host) if enable_dht else None
        announcer = SiteAnnouncer(site, file_server, dht_discovery=dht_discovery)

        async with AsyncExitStack() as stack:
            await stack.enter_async_context(file_server.run())
            if dht_discovery is not None:
                await stack.enter_async_context(dht_discovery.run())
            yield file_server, announcer

    @asynccontextmanager
    async def _ephemeralHost(self):
        p2p_dir = self.data_dir / ".p2p"
        p2p_dir.mkdir(parents=True, exist_ok=True)
        host = Host(p2p_dir, ws_port=None)
        async with host.run():
            yield host

    def _sitePeers(self, site, file_server, need_num: int = 5) -> list:
        """Builds real, dialable Peer objects from site.getConnectablePeers().
        Registers each record's ip/port (when known -- e.g. from pex) into
        the host's peerstore as a dialable multiaddr first: nothing else in
        this stack does that today (SiteAnnouncer.onDhtPeers() drops the
        multiaddrs kad-dht returns, keeping only peer_id; pex-discovered
        records carry ip/port but nothing turns that into a peerstore
        entry either), so without this, Peer.request()/getFile() would
        have no route to a peer this CLI hasn't already connected to via
        DHT-cached routing-table addresses."""
        records = site.getConnectablePeers(need_num=need_num)
        peerstore = file_server.host.get_peerstore()
        peers = []
        for record in records:
            if record.ip and record.port:
                try:
                    peerstore.add_addrs(record.peer_id, [Multiaddr("/ip4/%s/tcp/%s" % (record.ip, record.port))], 3600)
                except Exception:
                    pass
            peers.append(Peer(record.peer_id, file_server.host, file_server.connection_policy))
        return peers

    # -- Site commands --

    async def siteCreate(self, use_master_seed: bool = True) -> dict:
        log.info("Generating new privatekey (use_master_seed: %s)...", use_master_seed)
        if use_master_seed:
            user = await self._getOrCreateUser()
            address, address_index, site_data = await user.getNewSiteData()
            privatekey = site_data["privatekey"]
            log.info("Generated using master seed from users.json, site index: %s", address_index)
        else:
            privatekey = CryptBitcoin.newPrivatekey()
            address = CryptBitcoin.privatekeyToAddress(privatekey)
            address_index = None

        log.info("Site private key: %s", privatekey)
        log.info("                  !!! ^ Save it now, required to modify the site ^ !!!")
        log.info("Site address:     %s", address)

        if not self.site_manager.loaded:
            await self.site_manager.load()
        site = self.site_manager.add(address, own=True)
        await site.storage.write("index.html", ("Hello %s!" % address).encode("utf8"))

        extend = {"postmessage_nonce_security": True}
        if address_index is not None:
            extend["address_index"] = address_index
        await site.content_manager.sign(privatekey, extend=extend)
        await self.site_manager.save()

        log.info("Site created!")
        return {"address": address, "privatekey": privatekey}

    async def siteSign(self, address: str, privatekey: str | None = None, publish: bool = False) -> bool:
        site = await self._getSite(address)
        log.info("Signing site: %s...", address)

        if not privatekey:
            user = await self.user_manager.get()
            if user:
                privatekey = user.getSiteData(address, create=False).get("privatekey")
            if not privatekey:
                raise ActionError("No privatekey given and none stored in users.json for %s" % address)

        await site.content_manager.sign(privatekey)
        log.info("Site signed!")

        if publish:
            log.info("publish=True requires a running networking session (P2P.app.App) -- not started here.")
        return True

    async def siteVerify(self, address: str) -> dict:
        site = await self._getSite(address)
        log.info("Verifying site: %s...", address)
        cm = site.content_manager
        if "content.json" not in cm.contents:
            await cm.loadContent("content.json")

        bad_files = []
        for content_inner_path, content in list(cm.contents.items()):
            try:
                raw = await site.storage.read(content_inner_path)
                cm._verifySignature(content_inner_path, json.loads(raw))
                log.info("[OK] %s", content_inner_path)
            except Exception as err:
                log.error("[ERROR] %s: invalid file: %s!", content_inner_path, err)
                bad_files.append(content_inner_path)

            content_dir = _getDirname(content_inner_path)
            for file_relative_path in content.get("files", {}):
                file_inner_path = (content_dir + file_relative_path).strip("/")
                try:
                    raw = await site.storage.read(file_inner_path)
                    cm.verifyFile(file_inner_path, io.BytesIO(raw), ignore_same=False)
                except Exception as err:
                    log.error("[ERROR] %s: invalid file: %s!", file_inner_path, err)
                    bad_files.append(file_inner_path)

        if not bad_files:
            log.info("[OK] All files verified!")
        else:
            log.error("[ERROR] %s bad file(s) found!", len(bad_files))
        return {"bad_files": bad_files}

    async def dbRebuild(self, address: str) -> bool:
        site = await self._getSite(address)
        log.info("Rebuilding site sql cache: %s...", address)
        applied = await site.storage.rebuildDb(site.content_manager, reason="CLI dbRebuild")
        log.info("Done.")
        return applied

    async def dbQuery(self, address: str, query: str) -> list:
        site = await self._getSite(address)
        res = await site.storage.query(query)
        return [dict(row) for row in res.fetchall()]

    # -- Networking commands --

    async def siteAnnounce(self, address: str, enable_dht: bool = True) -> dict:
        site = await self._getSite(address)
        log.info("Announcing site %s...", address)
        async with self._networkSession(site, enable_dht=enable_dht) as (file_server, announcer):
            s = time.time()
            await announcer.announce(force=True)
            elapsed = time.time() - s
        log.info("Response time: %.3fs, peers: %s", elapsed, len(site.peers))
        return {"elapsed": elapsed, "peers": len(site.peers)}

    async def siteDownload(self, address: str, enable_dht: bool = True) -> dict:
        # "No peers" is raised OUTSIDE the `async with` below, not inside
        # it: file_server.run() opens a trio nursery under the hood, and
        # an exception raised while that nursery's body is still open gets
        # wrapped in a BaseExceptionGroup by the time it reaches the
        # caller -- `except ActionError` wouldn't catch it directly. So
        # this captures a plain "no peers found" flag inside the session
        # and only raises once it has cleanly exited.
        site = await self._getSite(address)
        log.info("Downloading site %s...", address)
        no_peers = False
        updated = None
        elapsed = None
        async with self._networkSession(site, enable_dht=enable_dht) as (file_server, announcer):
            log.info("Announcing...")
            await announcer.announce(force=True)
            peers = self._sitePeers(site, file_server)
            if not peers:
                no_peers = True
            else:
                s = time.time()
                log.info("Downloading...")
                updated = await syncSite(site, peers)
                elapsed = time.time() - s

        if no_peers:
            raise ActionError("No peers found for %s" % address)
        log.info("Downloaded in %.3fs (%s file(s) updated)", elapsed, len(updated))
        return {"elapsed": elapsed, "updated": updated}

    async def siteNeedFile(self, address: str, inner_path: str, timeout: float = 60, enable_dht: bool = True) -> dict:
        # See siteDownload()'s comment on why "no peers" is raised outside
        # the `async with` block below.
        site = await self._getSite(address)
        no_peers = False
        data = None
        async with self._networkSession(site, enable_dht=enable_dht) as (file_server, announcer):
            await announcer.announce(force=True)
            peers = self._sitePeers(site, file_server)
            if not peers:
                no_peers = True
            else:
                if "content.json" not in site.content_manager.contents:
                    if site.storage.isFile("content.json"):
                        await site.content_manager.loadContent("content.json")
                    else:
                        await downloadContentJson(site, peers)

                scheduler = Scheduler(site)
                data = await scheduler.needFile(inner_path, peers, timeout=timeout)
                await site.storage.write(inner_path, data)

        if no_peers:
            raise ActionError("No peers found for %s" % address)
        return {"inner_path": inner_path, "size": len(data)}

    async def peerPing(self, peer_id: str, multiaddr: str, count: int = 5) -> dict:
        target_id = ID.from_base58(peer_id)
        log.info("Pinging %s times peer: %s...", count, peer_id)
        async with self._ephemeralHost() as host:
            await host.connect(PeerInfo(target_id, [Multiaddr(multiaddr)]))
            peer = Peer(target_id, host, ConnectionPolicy(host))
            results = []
            for _ in range(count):
                s = time.time()
                ok = await peer.ping()
                elapsed = time.time() - s
                log.info("Response time: %.3fs", elapsed)
                results.append({"ok": ok, "elapsed": elapsed})
        return {"results": results}

    async def peerGetFile(self, peer_id: str, multiaddr: str, site: str, inner_path: str) -> dict:
        target_id = ID.from_base58(peer_id)
        log.info("Getting %s/%s from peer: %s...", site, inner_path, peer_id)
        async with self._ephemeralHost() as host:
            await host.connect(PeerInfo(target_id, [Multiaddr(multiaddr)]))
            peer = Peer(target_id, host, ConnectionPolicy(host))
            buff = await peer.getFile(site, inner_path)
            data = buff.read()
        return {"size": len(data), "content": data.decode("utf8", errors="replace")}

    async def peerCmd(self, peer_id: str, multiaddr: str, cmd: str, params: dict | None = None) -> dict:
        target_id = ID.from_base58(peer_id)
        async with self._ephemeralHost() as host:
            await host.connect(PeerInfo(target_id, [Multiaddr(multiaddr)]))
            peer = Peer(target_id, host, ConnectionPolicy(host))
            return await peer.request(cmd, params or {})

    async def siteCmd(
        self, cmd: str, wrapper_key: str, params: dict | None = None,
        ui_host: str = "127.0.0.1", ui_port: int = 43110,
    ) -> dict:
        """Talks to an ALREADY-RUNNING App's UI websocket -- see module
        docstring for why wrapper_key has to be supplied explicitly."""
        url = "ws://%s:%s/Ui?wrapper_key=%s" % (ui_host, ui_port, wrapper_key)
        async with trio_websocket.open_websocket_url(url) as ws:
            await ws.send_message(json.dumps({"cmd": cmd, "params": params or {}, "id": 1}))
            reply = json.loads(await ws.get_message())
        return reply

    # -- Crypto commands (no site/network dependency) --

    def cryptPrivatekeyToAddress(self, privatekey: str) -> str:
        return CryptBitcoin.privatekeyToAddress(privatekey)

    def cryptSign(self, message: str, privatekey: str) -> str:
        return CryptBitcoin.sign(message, privatekey)

    def cryptVerify(self, message: str, sign: str, address: str) -> bool:
        return CryptBitcoin.verify(message, address, sign)

    def cryptGetPrivatekey(self, master_seed: str, site_address_index: int | None = None):
        if len(master_seed) != 64:
            raise ActionError("Invalid master seed length: %s (required: 64)" % len(master_seed))
        return CryptBitcoin.hdPrivatekey(master_seed, site_address_index)


async def _dispatch(args) -> None:
    actions = Actions(args.data_dir)
    method = getattr(actions, args.command, None)
    if method is None:
        raise SystemExit("Unknown command: %s" % args.command)

    kwargs = json.loads(args.kwargs) if args.kwargs else {}
    result = method(**kwargs)
    if hasattr(result, "__await__"):
        result = await result
    if result is not None:
        print(json.dumps(result, indent=2, default=str))


def main() -> None:
    """`python -m P2P.actions <command> --data-dir ... [--kwargs '{"address": "..."}']`"""
    import argparse

    parser = argparse.ArgumentParser(description="zeronet-conservancy trio-native CLI actions")
    parser.add_argument("command")
    parser.add_argument("--data-dir", type=pathlib.Path, required=True)
    parser.add_argument("--kwargs", help="JSON object of keyword arguments for the command")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    trio.run(_dispatch, args)


if __name__ == "__main__":
    main()
