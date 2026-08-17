"""Trio-native replacement for Ui/UiServer.py + Ui/UiRequest.py's routing,
served via Hypercorn's trio worker instead of gevent.pywsgi.WSGIServer +
the custom src/lib/gevent_ws WebSocketHandler.

Routing/dispatch itself is now Starlette, not a hand-rolled ASGI
callable: Starlette sits on the same ASGI/Hypercorn foundation already
chosen and gives real, tested replacements for pieces the original
hand-rolled --

  - TrustedHostMiddleware replaces isHostAllowed()'s manual Host-header
    check (still defaults to 127.0.0.1/localhost, the original's own safe
    default for local-only installs).
  - CORSMiddleware is the real place cross-origin rules belong, in place
    of hasCorsPermission()/isCrossOriginRequest()'s hand-rolled logic --
    locked down (no cross-origin allowed) until the original's per-site
    permission model is ported.
  - StaticFiles mounts src/Ui/media/ at /uimedia/ directly -- the actual
    production CSS/JS/images, not copies, so nothing to keep in sync.
  - Route/WebSocketRoute replace the manual scope["type"] dispatch this
    module used before Starlette.

Wrapper HTML rendering (Wrapper.py, Jinja2-based) covers the common case:
an HTML page (or the site root) gets wrapped, anything else is served
raw from SiteStorage. NOT the original's isWrapperNecessary() Accept-
header sniffing -- extension-based here, which covers the common
navigations but not every edge case that logic handled.

The websocket command API (UiWebsocket.py's ~30 actionX methods) is
ported command-by-command in commands.py, same pattern as protocols/*.py
on the P2P side -- see that module's own docstring for which commands and
why. A connection resolves to a specific Site via ?wrapper_key=, matching
the original's "Find site by wrapper_key" in UiRequest.actionWebsocket;
still NOT ported: auth/cookies (wrapper_key alone gates nothing beyond
site *selection* here, unlike the original's full nonce/cookie session
model), UiMedia's dynamic pieces (this mounts the static assets directory,
not the original's more elaborate content-negotiation for it).

The websocket route lives at /ZeroNet-Internal/Websocket, not /Ui as an
earlier version of this module had it -- a real bug, found live: the
actual production wrapper.js (served byte-identical from src/Ui/media/,
per this module's own docstring elsewhere) hardcodes that exact path
(see its `ws_url = ... + "/ZeroNet-Internal/Websocket?wrapper_key=" +
...` construction), so every websocket connection attempt from a real
browser 404'd silently against the old path -- no site info, no
notifications, nothing that depends on the websocket ever worked,
with only a quiet reconnect-and-fail loop in the console to show for it.

Homepage redirect + auto-add-and-download (added once real users started
hitting this after the Phase 10 default flip): `/` redirects to
`/{homepage}/` (homepage threaded from config.homepage, same default
address the original ships); visiting an address that isn't in
self.sites yet -- the common case for a fresh --p2p install, since
SiteManager.add() deliberately doesn't auto-fetch -- now auto-adds it
(via the on_missing_site callback, App.addSite()) and attempts a real,
bounded (default 15s) announce+download before responding, instead of
an immediate 404. If no peers are found in time, or the address never
existed to begin with, the response is 503 ("downloading, try reloading
shortly") or 404 respectively, not a wrapper page with a progress bar --
this stack has no client-side polling/loading-screen mechanism yet, so
the request itself is what blocks.

Server push (added alongside the Sidebar plugin's consoleLogStream):
every command handler up to this point was plain request-in/response-out,
so `UiSession.push()` fills the gap the original's `ui_websocket.cmd()`
covered -- sending a message to an already-connected client outside any
request/response cycle. All outbound traffic for a connection, both real
responses and pushes, now funnels through one per-session trio memory
channel drained by a single writer task, so concurrent senders (the
reader loop answering a request, a background task pushing) never
interleave writes on the same websocket. `UiSession.nursery` is the
same nursery the connection's reader/writer loops run in, exposed so a
command handler can spawn a background task (e.g. a logging.Handler
that streams new log lines) that outlives its own single request/response
turn -- it's cancelled automatically when the connection closes, since
closing tears down that whole nursery. `UiSession.state`, a plain dict,
is scratch space for a plugin's own per-connection bookkeeping (e.g.
stream_id -> cancel scope, so a specific background push task can be
torn down early without closing the whole connection) -- deliberately
generic here rather than something like Sidebar's own log_streamers
dict living in the core session class.

UiApp.broadcast() is the second push consumer: a port of the original's
UiWebsocket.event(), pushing setSiteInfo/setServerInfo/setAnnouncerInfo
to every session joined to the relevant channel (channelJoin already
existed in commands.py; nothing previously called the other half).
sitePublish/sitePause/siteResume/siteUpdate/fileNeed all call it now,
after their own user-initiated change -- the original calls Site.py's
updateWebsocket() (which drives this) from several more places (peer
count changes, etc.) that still don't have equivalents in this stack.
One genuinely network-driven trigger IS wired now, though, not just
UI-command ones: FileServer.on_update_applied (set by App.__init__)
fires broadcast("siteChanged", ..., {"event": "updated"}) when a peer
pushes us a fresh content.json over protocols/update.py -- see that
module's own docstring. Each additional trigger is its own small,
separate addition as the corresponding machinery lands, not something to
force in one pass.
"""
import json
import logging
import pathlib
import time
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import trio
from Crypt import CryptHash
from Translate import translate
from hypercorn.config import Config
from hypercorn.trio import serve
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..SiteStorage import AccessError
from .Wrapper import renderWrapper
from .Dashboard import renderDashboard
from .UiPassword import PasswordGateMiddleware, SESSION_COOKIE, SessionStore, renderLogin
from .Stats import renderStats, renderAbout, renderDumpobj, renderListobj

UI_MEDIA_DIR = pathlib.Path(__file__).resolve().parents[2] / "Ui" / "media"
if not UI_MEDIA_DIR.is_dir():
    UI_MEDIA_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "Ui" / "media"

# Legacy repo-root plugins/ (one level above src/) -- see _handleUiMediaExtra's
# own docstring for why this stack reaches into it for a couple of plugins'
# pure client-side JS/CSS.
LEGACY_PLUGINS_DIR = pathlib.Path(__file__).resolve().parents[3] / "plugins"
if not LEGACY_PLUGINS_DIR.is_dir():
    LEGACY_PLUGINS_DIR = pathlib.Path(__file__).resolve().parents[2] / "plugins"

# Plugin name -> extra client media this stack injects onto /uimedia/all.js
# and /uimedia/all.css, IF that plugin is currently loaded (checked against
# P2P.PluginManager.plugin_manager.plugin_names). Only plugins with real,
# gevent-free client JS/CSS worth reusing verbatim belong here -- see
# _handleUiMediaExtra's docstring.
_UIMEDIA_EXTRA_PLUGINS = ["Sidebar"]

# Cookie name carrying a browser's own master_address in multiuser mode --
# see _ensureMultiuserCookie()'s and UiSession's own docstrings.
MULTIUSER_COOKIE = "master_address"

log = logging.getLogger(__name__)

COMMAND_HANDLERS = {}


def command(name):
    def decorator(fn):
        COMMAND_HANDLERS[name] = fn
        return fn
    return decorator


class UiSession:
    """Per-websocket-connection state: which site this connection is
    scoped to (resolved from ?wrapper_key=, matching the original's
    "Find site by wrapper_key" in UiRequest.actionWebsocket) and which
    event channels it has joined. Passed to every command handler in
    place of the original's `self` (a whole UiWebsocket instance) --
    handlers here are plain functions, not methods, so they need this
    explicitly. session.app carries through to site_manager/user_manager
    for commands that need them (siteAdd/siteDelete/certAdd/etc.).

    master_address is the multiuser cookie-to-session wiring this whole
    class was previously missing (see UserManager.py's own docstring for
    the get()-by-address primitive this resolves against): read from the
    websocket handshake's own cookies -- an ordinary same-origin HTTP
    request, so the browser sends whatever cookie _ensureMultiuserCookie
    set when the wrapper page itself was served, no extra round trip or
    URL-param threading needed. None in single-user mode (the default),
    or if this particular connection genuinely has no cookie yet."""
    def __init__(self, app: "UiApp", site=None, master_address: str | None = None):
        self.app = app
        self.site = site
        self.master_address = master_address
        self.channels: list = []
        self.state: dict = {}  # Scratch space for a plugin's own per-connection bookkeeping
        self.nursery: trio.Nursery | None = None  # Set once the connection's loops start
        self._send_channel, self._recv_channel = trio.open_memory_channel(256)
        self._after_response: list[dict] = []

    def push(self, cmd: str, params=None) -> None:
        """Queue an unprompted message to this session's client, outside
        any request/response cycle (e.g. a background log-streaming
        task). Fire-and-forget and non-blocking, matching the original
        stack's own best-effort ui_websocket.cmd() semantics: if the
        session's outbound queue is full or the connection has already
        closed, the push is silently dropped rather than blocking or
        raising. Safe to call from a synchronous context too (e.g. a
        logging.Handler.emit()), since it never awaits."""
        try:
            self._send_channel.send_nowait({"cmd": cmd, "params": params or {}})
        except (trio.WouldBlock, trio.BrokenResourceError, trio.ClosedResourceError):
            pass

    def pushAfterResponse(self, cmd: str, params=None) -> None:
        """Queue a state push after the current command response.

        Legacy callers expect the response callback first, notably certSet.
        """
        self._after_response.append({"cmd": cmd, "params": params or {}})


def _guessContentType(inner_path: str) -> str:
    if inner_path.endswith(".json"):
        return "application/json"
    if inner_path.endswith(".html"):
        return "text/html"
    if inner_path.endswith(".css"):
        return "text/css"
    if inner_path.endswith(".js"):
        return "application/javascript"
    return "application/octet-stream"


class UiApp:
    WRAPPER_NONCE_TTL = 300.0
    MAX_WRAPPER_NONCES = 4096

    def __init__(self, sites: dict, allowed_hosts: list | None = None, site_manager=None, user_manager=None,
                 file_server=None, announcers: dict | None = None, tor_manager=None,
                 homepage: str | None = None, on_missing_site=None, auto_download_timeout: float = 15.0,
                 data_dir=None, shutdown_callback=None, dht_discovery=None,
                 allowed_ws_origins: set[str] | None = None, ui_password: str | None = None):
        self.sites = sites  # site address -> P2P.Site
        self.site_manager = site_manager  # P2P.SiteManager, for siteAdd/siteDelete/sitePause/siteResume/siteList
        self.user_manager = user_manager  # P2P.UserManager, for cert*/user* commands
        self.file_server = file_server  # P2P.FileServer, for sitePublish's peer push
        self.announcers = announcers  # site address -> P2P.SiteAnnouncer, for announcerInfo
        self.tor_manager = tor_manager  # P2P.Tor.TorManager, for serverInfo's tor_enabled/tor_status
        self.homepage = homepage  # Site address `/` redirects to, e.g. config.homepage
        self.data_dir = data_dir
        self.shutdown_callback = shutdown_callback
        self.dht_discovery = dht_discovery
        self.on_missing_site = on_missing_site  # (address) -> Site | None, e.g. App.addSite; adds + wires a new site
        self.auto_download_timeout = auto_download_timeout
        self.allowed_ws_origins = set(allowed_ws_origins or ())
        # nonce -> monotonic expiry. Browser back/forward can replay the
        # wrapper iframe URL, so a nonce must remain valid for its short
        # lifetime rather than being consumed by the first raw file request.
        self.wrapper_nonces: dict[str, float] = {}
        self.sessions: set["UiSession"] = set()
        # See UiPassword.py's own module docstring -- off by default,
        # matching plugins/disabled-UiPassword/'s own default.
        self.ui_password = ui_password
        self._password_sessions = SessionStore() if ui_password else None

        routes = [
            Route("/", self._handleHomepage, methods=["GET"]),
            Route("/Config", self._handleConfig, methods=["GET"]),
            Route("/Config/", self._handleConfig, methods=["GET"]),
            Route("/Plugins", self._handlePlugins, methods=["GET"]),
            Route("/Plugins/", self._handlePlugins, methods=["GET"]),
            Route("/Console", self._handleConsole, methods=["GET"]),
            Route("/Console/", self._handleConsole, methods=["GET"]),
            Route("/Stats", self._handleStats, methods=["GET"]),
            Route("/About", self._handleAbout, methods=["GET"]),
            Route("/Dumpobj", self._handleDumpobj, methods=["GET"]),
            Route("/Listobj", self._handleListobj, methods=["GET"]),
            Route("/GcCollect", self._handleGcCollect, methods=["GET"]),
            Route("/list/{address}/{inner_path:path}", self._handleFileManager, methods=["GET"]),
            Route("/list/{address}", self._handleFileManager, methods=["GET"]),
            Route("/ZeroNet-Internal/BigfileUpload", self._handleBigfileUpload, methods=["POST"]),
            Route("/{address}/{inner_path:path}", self._handleSite, methods=["GET"]),
            Route("/{address}", self._handleSite, methods=["GET"]),
            WebSocketRoute("/ZeroNet-Internal/Websocket", self._handleWebsocket),
        ]
        if ui_password:
            routes.insert(0, Route("/Login", self._handleLogin, methods=["GET", "POST"]))
            routes.insert(0, Route("/Logout", self._handleLogout, methods=["GET"]))
        if UI_MEDIA_DIR.is_dir():
            # all.js/all.css get their own routes (plugin-media injection --
            # see _handleUiMediaExtra), matched before the generic mount
            # below so Starlette prefers them over StaticFiles for exactly
            # those two paths; everything else (images, fonts, ...) still
            # falls through to the plain static mount. Insertion order
            # matters: each insert(0, ...) pushes to the front, so the
            # Mount must go in FIRST for the two specific Routes to end up
            # ahead of it in the final list (Starlette matches in order).
            routes.insert(0, Mount("/uimedia", app=StaticFiles(directory=str(UI_MEDIA_DIR)), name="uimedia"))
            routes.insert(0, Route("/uimedia/all.css", self._handleUiMediaCss, methods=["GET"]))
            routes.insert(0, Route("/uimedia/all.js", self._handleUiMediaJs, methods=["GET"]))

        middleware = [
            Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost"]),
            Middleware(CORSMiddleware, allow_origins=[], allow_credentials=False),
        ]
        if ui_password:
            middleware.insert(0, Middleware(PasswordGateMiddleware, sessions=self._password_sessions))

        self._asgi = Starlette(routes=routes, middleware=middleware)

    async def __call__(self, scope, receive, send) -> None:
        await self._asgi(scope, receive, send)

    async def _handleHomepage(self, request: Request) -> Response:
        if not self.homepage:
            return Response(b"No homepage configured", status_code=404)
        return RedirectResponse(url="/%s/" % self.homepage)

    async def _handleLogin(self, request: Request) -> Response:
        """GET shows the form; POST validates it. Parses the urlencoded
        body by hand (urllib.parse.parse_qs) rather than Starlette's own
        request.form(), which needs the optional python-multipart
        dependency this stack doesn't otherwise use -- the login form's
        two fields (password, an optional keep checkbox) don't need a
        real multipart parser."""
        if request.method == "GET":
            return Response(renderLogin(), media_type="text/html")

        from urllib.parse import parse_qs
        body = await request.body()
        posted = parse_qs(body.decode("utf8", errors="replace"))
        password = (posted.get("password") or [""])[0]
        if password != self.ui_password:
            return Response(renderLogin(bad_password=True), media_type="text/html")

        keep = bool((posted.get("keep") or [""])[0])
        session_id, max_age = self._password_sessions.create(keep)
        next_url = request.query_params.get("next") or ("/%s/" % self.homepage if self.homepage else "/")
        response = RedirectResponse(url=next_url, status_code=303)
        response.set_cookie(SESSION_COOKIE, session_id, max_age=max_age, path="/", httponly=True, samesite="lax")
        return response

    async def _handleLogout(self, request: Request) -> Response:
        self._password_sessions.delete(request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse(url="/", status_code=303)
        response.delete_cookie(SESSION_COOKIE, path="/")
        return response

    async def _ensureMultiuserCookie(self, request: Request) -> str | None:
        """No-op (returns None) unless user_manager is configured AND in
        multiuser mode -- the overwhelmingly common case, so every other
        HTTP handler stays a single cheap attribute check away from
        today's single-user behavior. Otherwise: honor an existing valid
        master_address cookie, or create a brand new account and return
        its address for the caller to set as the response's own cookie.
        This is the HTTP-side half of the multiuser wiring -- by the time
        a wrapper page's own JS opens the websocket, the cookie this sets
        is already in the browser, so _handleWebsocket's cookie read
        (same-origin, ordinary HTTP request) needs no extra round trip."""
        if self.user_manager is None or not self.user_manager.multiuser:
            return None
        master_address = request.cookies.get(MULTIUSER_COOKIE)
        if master_address and await self.user_manager.get(master_address):
            return master_address
        user = self.user_manager.create()
        user.markDirty()
        await user.save()
        return user.master_address

    def _dashboardSite(self):
        """Return the site whose wrapper key scopes dashboard websocket calls."""
        if self.homepage and self.homepage in self.sites:
            return self.sites[self.homepage]
        return next(iter(self.sites.values()), None)

    async def _handleDashboard(self, request: Request, page: str) -> Response:
        site = self._dashboardSite()
        if site is None:
            return Response(b"No dashboard site configured", status_code=404)
        scheme = "wss" if request.url.scheme == "https" else "ws"
        host = request.headers.get("host") or request.url.netloc
        websocket_url = "%s://%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
            scheme, host, site.wrapper_key
        )
        response = Response(renderDashboard(page, websocket_url, address=site.address), media_type="text/html")
        master_address = await self._ensureMultiuserCookie(request)
        if master_address:
            response.set_cookie(MULTIUSER_COOKIE, master_address, max_age=60 * 60 * 24 * 365, path="/", httponly=True, samesite="lax")
        return response

    async def _handleConfig(self, request: Request) -> Response:
        return await self._handleDashboard(request, "config")

    async def _handlePlugins(self, request: Request) -> Response:
        return await self._handleDashboard(request, "plugins")

    async def _handleConsole(self, request: Request) -> Response:
        return await self._handleDashboard(request, "console")

    async def _handleStats(self, request: Request) -> Response:
        """Unlike /Config/Plugins/Console, not a websocket-driven page --
        see Stats.py's own module docstring for why a live diagnostics
        dump doesn't fit the bucket-3 command surface. Plain server-
        rendered HTML, computed fresh on every request."""
        return Response(renderStats(self), media_type="text/html")

    async def _handleAbout(self, request: Request) -> Response:
        return Response(renderAbout(), media_type="text/html")

    async def _handleDumpobj(self, request: Request) -> Response:
        """Port of StatsPlugin.actionDumpobj() -- debug-only (config.debug),
        same gate the original uses; not multiuser-proxy-gated, matching
        /Stats and /About's own gap notes on that."""
        from Config import config
        if not config.debug:
            return Response("Not in debug mode", media_type="text/html")
        class_filter = request.query_params.get("class", "")
        return Response(renderDumpobj(class_filter), media_type="text/html")

    async def _handleListobj(self, request: Request) -> Response:
        """Port of StatsPlugin.actionListobj() -- same debug-only gate."""
        from Config import config
        if not config.debug:
            return Response("Not in debug mode", media_type="text/html")
        type_filter = request.query_params.get("type", "")
        return Response(renderListobj(type_filter), media_type="text/html")

    async def _handleGcCollect(self, request: Request) -> Response:
        """Port of StatsPlugin.actionGcCollect() -- unlike Dumpobj/Listobj,
        the original doesn't gate this behind config.debug either, so this
        stays available unconditionally too."""
        import gc
        return Response(str(gc.collect()), media_type="text/plain")

    async def _handleBigfileUpload(self, request: Request) -> Response:
        """Raw-body counterpart to commands.py's bigfileUploadInit() --
        receives the actual bytes for a nonce minted there, streaming
        them straight to a sparse file via SiteStorage.writeRange()
        (Bigfile Layer A) rather than buffering the whole upload in
        memory, hashing each piece as it completes
        (Bigfile.digest_piece()) the same way the original's own
        single-pass hashBigfile() read loop does.

        A single-piece upload (small enough to fit in one piece) is left
        as a plain file on disk with no content.json change at all --
        same as fileWrite's own behavior; the next real siteSign's
        hashFiles() picks it up like any other file, no special
        bookkeeping needed. A genuine multi-piece file gets its own
        msgpack piecemap plus a files_optional entry (piecemap/
        piece_size), exactly the shape WorkerManager.downloadBigfile()'s
        own loadBigfileInfo() already expects to read back -- and its
        piecefield is marked fully complete immediately, since every
        piece we just wrote came from this upload, not a partial
        download in progress."""
        from . import commands
        from ..Bigfile import Piecefield, digest_piece, merkle_root
        from util import Msgpack

        nonce = request.query_params.get("upload_nonce")
        upload = commands.UPLOAD_NONCES.pop(nonce, None) if nonce else None
        if upload is None:
            return Response("Upload nonce error.", status_code=403)

        site = upload["site"]
        inner_path = upload["inner_path"]
        size = upload["size"]
        piece_size = upload["piece_size"]

        site.storage.createSparseFile(inner_path, size)
        piece_hashes: list[bytes] = []
        position = 0
        buffer = b""
        async for chunk in request.stream():
            buffer += chunk
            while len(buffer) >= piece_size:
                piece, buffer = buffer[:piece_size], buffer[piece_size:]
                await site.storage.writeRange(inner_path, position, piece)
                piece_hashes.append(digest_piece(piece))
                position += len(piece)
        if buffer:
            await site.storage.writeRange(inner_path, position, buffer)
            piece_hashes.append(digest_piece(buffer))

        root = merkle_root(piece_hashes)

        if len(piece_hashes) > 1:
            file_name = pathlib.PurePosixPath(inner_path).name
            piecemap_body = Msgpack.pack({file_name: {"sha512_pieces": piece_hashes, "piece_size": piece_size}})
            await site.storage.write(upload["piecemap_inner_path"], piecemap_body)

            content_inner_path = upload["content_inner_path"]
            if site.storage.isFile(content_inner_path):
                content = await site.storage.loadJson(content_inner_path)
            else:
                content = {}
            content.setdefault("files_optional", {})
            content["files_optional"][upload["file_relative_path"]] = {
                "sha512": root, "size": size,
                "piecemap": upload["piecemap_relative_path"], "piece_size": piece_size,
            }
            await site.storage.writeJson(content_inner_path, content)
            await site.content_manager.loadContent(content_inner_path)

            piecefield = Piecefield(len(piece_hashes))
            for piece_index in range(len(piece_hashes)):
                piecefield[piece_index] = True
            await site.storage.savePiecefield(root, piecefield)

        return Response(
            json.dumps({
                "merkle_root": root, "piece_num": len(piece_hashes),
                "piece_size": piece_size, "inner_path": inner_path,
            }),
            media_type="application/json",
        )

    async def _handleFileManager(self, request: Request) -> Response:
        address = request.path_params["address"]
        site = self.sites.get(address)
        if site is None and self.site_manager is not None:
            site = await self.site_manager.get(address)
            if site is None:
                resolved = await self.site_manager.resolveDomain(address)
                if resolved:
                    address = resolved
                    site = self.sites.get(address)
        if site is None:
            return Response(b"Unknown site", status_code=404)
        scheme = "wss" if request.url.scheme == "https" else "ws"
        host = request.headers.get("host") or request.url.netloc
        websocket_url = "%s://%s/ZeroNet-Internal/Websocket?wrapper_key=%s" % (
            scheme, host, site.wrapper_key
        )
        return Response(renderDashboard(
            "files", websocket_url, address=site.address,
            inner_path=request.path_params.get("inner_path", "").strip("/"),
        ), media_type="text/html")

    async def _handleUiMediaExtra(self, filename: str) -> bytes:
        """Found live: the legacy Plugin.PluginManager's own UiRequestPlugin
        .actionUiMedia() appends a plugin's client media (plugins/<name>/
        media/all.js or all.css) onto the end of /uimedia/all.js|all.css --
        that's how e.g. the Sidebar plugin's drag-to-open-sidebar gesture
        and console-log panel actually get into the page; this stack's
        /uimedia mount just served the bare core file with no such
        mechanism, so plugins with client-side media never loaded it.

        Reuses the LEGACY plugin's media file directly rather than copying
        it under P2P/plugins/ -- it's pure client JS/CSS with no gevent
        dependency (same "verbatim real asset" precedent as UI_MEDIA_DIR
        itself), and P2P/plugins/Sidebar has no media of its own yet.
        Gated on the plugin actually being loaded (checked against
        P2P.PluginManager's plugin_names, the same registry loadPlugins()
        populates) so this doesn't silently inject a legacy plugin's JS
        when that plugin was disabled or failed to load on the P2P side."""
        from ..PluginManager import plugin_manager

        extra = b""
        for name in _UIMEDIA_EXTRA_PLUGINS:
            if name not in plugin_manager.plugin_names:
                continue
            path = LEGACY_PLUGINS_DIR / name / "media" / filename
            if path.is_file():
                extra += b"\n" + path.read_bytes()
        return extra

    async def _handleUiMediaJs(self, request: Request) -> Response:
        body = (UI_MEDIA_DIR / "all.js").read_bytes() + await self._handleUiMediaExtra("all.js")
        return Response(body, media_type="application/javascript")

    async def _handleUiMediaCss(self, request: Request) -> Response:
        body = (UI_MEDIA_DIR / "all.css").read_bytes() + await self._handleUiMediaExtra("all.css")
        return Response(body, media_type="text/css")

    async def _handleSite(self, request: Request) -> Response:
        address = request.path_params["address"]
        inner_path = request.path_params.get("inner_path", "")

        site = self.sites.get(address)
        if site is None and self.site_manager is not None:
            # SiteManager plugins (notably Zeroname) resolve virtual domains
            # asynchronously; use the same lookup for HTTP as the UI/API
            # layer instead of treating a domain as an unknown site.
            site = await self.site_manager.get(address)
            if site is None:
                resolved = await self.site_manager.resolveDomain(address)
                if resolved:
                    address = resolved
                    site = self.sites.get(address)
        just_added = False
        if site is None:
            site = await self._tryAutoAddSite(address)
            just_added = site is not None
        if site is None:
            return Response(b"Unknown site", status_code=404)

        if just_added:
            if not site.storage.isFile("content.json"):
                await self._tryDownloadSite(site)
                if not site.storage.isFile("content.json"):
                    return Response(
                        b"Site not downloaded yet -- no peers found within %ss. Try reloading shortly."
                        % str(self.auto_download_timeout).encode(),
                        status_code=503,
                    )
            if "content.json" not in site.content_manager.contents:
                # SiteManager.add() (unlike load(), fixed earlier) is sync
                # and can't load content itself -- found live, activating
                # a site auto-added mid-process (ZeroTalk, already fully
                # downloaded on disk from an earlier session): its
                # content.json existed on disk the whole time, so the
                # branch above never ran, and nothing else ever loaded it
                # either. Every site.content_manager.contents.get(...)
                # read elsewhere (formatSiteInfo, the sidebar, ZeroTalk's
                # own site_info.content.settings) stayed None/crashed
                # exactly like the already-fixed SiteManager.load() case.
                try:
                    await site.content_manager.loadContent()
                except Exception:
                    log.exception("Failed to load content.json for auto-added site %s", address)
                    return Response(
                        b"Site content could not be loaded; try reloading shortly.",
                        status_code=503,
                    )

        if not site.isServing():
            return Response(b"Unknown site", status_code=404)

        is_html_page = inner_path in ("", "/") or inner_path.endswith("/") or inner_path.endswith(".html")
        wants_wrapper = request.query_params.get("wrapper") != "0"

        if is_html_page and wants_wrapper:
            wrapper_nonce = self._issueWrapperNonce()
            body = renderWrapper(
                site,
                scheme=request.url.scheme,
                host=request.url.hostname or "127.0.0.1",
                site_file_server_port=request.url.port or 80,
                address=address,
                inner_path=inner_path or "index.html",
                title=address,
                homepage=("/" + self.homepage) if self.homepage else "/",
                wrapper_nonce=wrapper_nonce,
            )
            response = Response(body, media_type="text/html")
            master_address = await self._ensureMultiuserCookie(request)
            if master_address:
                response.set_cookie(MULTIUSER_COOKIE, master_address, max_age=60 * 60 * 24 * 365, path="/", httponly=True, samesite="lax")
            return response

        wrapper_nonce = request.query_params.get("wrapper_nonce")
        if wrapper_nonce and not self._consumeWrapperNonce(wrapper_nonce):
            # Fail open: this nonce only exists for the site's own ZeroFrame
            # postMessage matching (see Wrapper.py's docstring), not as an
            # auth gate on serving public site content. A stale/expired
            # nonce here just means the browser reloaded a cached wrapper
            # page (e.g. back-navigation) -- rejecting the request left the
            # iframe blank with no way to recover.
            log.warning("Invalid or expired wrapper nonce for %s: %s", address, wrapper_nonce)

        target_path = inner_path or "content.json"
        try:
            if not site.storage.isFile(target_path):
                return Response(b"File not found", status_code=404)
            data = await site.storage.read(target_path)
        except AccessError:
            return Response(b"Invalid path", status_code=403)

        data = await self._maybeTranslate(site, target_path, data)

        return Response(data, media_type=_guessContentType(target_path))

    async def _maybeTranslate(self, site, inner_path: str, data: bytes) -> bytes:
        """Real port of plugins/TranslateSite/TranslateSitePlugin.py's own
        actionSiteMedia()/actionPatchFile(). Reuses src/Translate/
        Translate.py directly rather than reimplementing it -- found,
        while scoping this, to have zero gevent dependency at all: pure
        regex-based string substitution driven by config.language, and
        `from Translate import translate` is already the exact
        module-level singleton the original itself imports and shares
        across every site request, not a new instance to keep in sync.

        Every .html response gets the harmless part unconditionally, even
        when config.language is "en" (the default): translateData()'s own
        html branch replaces the literal token "lang={lang}" in the
        source with the real configured language, the same GET-parameter
        cache-buster trick the original always applies so a browser
        doesn't keep serving a stale non-English all.js after a language
        switch. A .js response only gets touched at all when
        config.language isn't English, matching the original's own
        `elif extension == "js" and translate.lang != "en"` condition
        exactly -- no reason to touch every JS response by default.

        Real per-string translation (not just the lang= tag) only kicks
        in when the site itself opts in: content.json's own "translate"
        list names inner_path AND the site actually has (i.e. has
        downloaded) its own data/languages/<lang>.json. Neither existing
        without the other means "not translatable this way" -- same
        original semantics -- and this stays honest about what's
        genuinely available locally rather than guessing."""
        lower = inner_path.lower()
        if lower.endswith(".html"):
            mode = "html"
        elif lower.endswith(".js") and translate.lang != "en":
            mode = "js"
        else:
            return data

        content = site.content_manager.contents.get("content.json") or {}
        lang_file = "languages/%s.json" % translate.lang
        eligible = site.storage.isFile(lang_file) and inner_path in (content.get("translate") or [])

        text = data.decode("utf8", errors="replace")
        if not eligible:
            if mode == "html":
                text = text.replace("lang={lang}", "lang=%s" % translate.lang)
            return text.encode("utf8")

        try:
            lang_table = await site.storage.loadJson(lang_file)
        except Exception:
            return data
        return translate.translateData(text, lang_table, mode).encode("utf8")

    def _issueWrapperNonce(self) -> str:
        nonce = CryptHash.random()
        now = time.monotonic()
        self._pruneWrapperNonces(now)
        if len(self.wrapper_nonces) >= self.MAX_WRAPPER_NONCES:
            oldest = min(self.wrapper_nonces, key=self.wrapper_nonces.get)
            del self.wrapper_nonces[oldest]
        self.wrapper_nonces[nonce] = now + self.WRAPPER_NONCE_TTL
        return nonce

    def _consumeWrapperNonce(self, nonce: str) -> bool:
        now = time.monotonic()
        expiry = self.wrapper_nonces.get(nonce)
        self._pruneWrapperNonces(now)
        return expiry is not None and expiry >= now

    def _pruneWrapperNonces(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for nonce, expiry in list(self.wrapper_nonces.items()):
            if expiry < now:
                del self.wrapper_nonces[nonce]

    async def _tryAutoAddSite(self, address: str):
        """Adds+wires a site the first time it's visited, matching the
        original's own auto-add-on-visit UX -- SiteManager.add() itself
        deliberately doesn't do this (see its own docstring), so without
        this every fresh --p2p install 404s on every address until
        something explicitly calls siteAdd/siteDownload first."""
        if self.site_manager is None or self.on_missing_site is None:
            return None
        if not self.site_manager.isAddress(address):
            return None
        return self.on_missing_site(address)

    async def _tryDownloadSite(self, site) -> None:
        """Best-effort, bounded (auto_download_timeout) real announce +
        download for a site with no content.json yet -- same
        announce-then-syncSite shape as P2P.actions.Actions.siteDownload(),
        just inlined here since there's no websocket/CLI caller driving
        it for a plain HTTP page load. No client-side loading-screen
        polling exists in this stack yet, so the request itself blocks
        for up to auto_download_timeout rather than returning immediately
        with a page that'd refresh itself."""
        if self.file_server is None:
            return
        announcer = self.announcers.get(site.address) if self.announcers else None
        with trio.move_on_after(self.auto_download_timeout):
            if announcer is not None:
                try:
                    await announcer.announce(force=True)
                except Exception:
                    pass

            from multiaddr import Multiaddr

            from ..Peer import Peer
            from ..WorkerManager import downloadContentJson

            records = site.getConnectablePeers(need_num=5)
            if not records:
                return
            peerstore = self.file_server.host.get_peerstore()
            peers = []
            for record in records:
                if record.ip and record.port:
                    try:
                        peerstore.add_addrs(record.peer_id, [Multiaddr("/ip4/%s/tcp/%s" % (record.ip, record.port))], 3600)
                    except Exception:
                        pass
                peers.append(Peer(record.peer_id, self.file_server.host, self.file_server.connection_policy))

            try:
                await downloadContentJson(site, peers)
            except Exception:
                pass

    async def _handleWebsocket(self, websocket: WebSocket) -> None:
        origin = websocket.headers.get("origin")
        if origin and not self._isAllowedWebSocketOrigin(origin, websocket.headers.get("host", "")):
            log.warning("Rejected WebSocket origin %s for host %s", origin, websocket.headers.get("host", ""))
            await websocket.close(code=1008)
            return
        await websocket.accept()
        wrapper_key = websocket.query_params.get("wrapper_key")
        site = self._resolveSiteByWrapperKey(wrapper_key) if wrapper_key else None
        master_address = websocket.cookies.get(MULTIUSER_COOKIE)
        session = UiSession(self, site=site, master_address=master_address)
        self.sessions.add(session)
        try:
            async with trio.open_nursery() as nursery:
                session.nursery = nursery
                nursery.start_soon(self._writeLoop, websocket, session)
                try:
                    while True:
                        raw = await websocket.receive_text()
                        try:
                            request = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        response = await self._handleCommand(session, request)
                        try:
                            session._send_channel.send_nowait(response)
                            for message in session._after_response:
                                session._send_channel.send_nowait(message)
                        except trio.WouldBlock:
                            # Outbound queue is backed up (slow/throttled
                            # client) -- drop this response rather than
                            # tearing down the whole session, matching
                            # UiSession.push()'s own best-effort semantics.
                            log.warning(
                                "UI websocket outbound queue full, dropping response (site=%s)",
                                getattr(site, "address", None),
                            )
                        session._after_response.clear()
                except WebSocketDisconnect as err:
                    log.info(
                        "UI websocket disconnected (site=%s, code=%s)",
                        getattr(site, "address", None), getattr(err, "code", None),
                    )
                except Exception:
                    log.exception("UI websocket session failed (site=%s)", getattr(site, "address", None))
                    raise
                finally:
                    # Tear down the write loop and any background push tasks
                    # a command spawned on session.nursery (e.g. Sidebar's
                    # consoleLogStream) -- nobody's listening past this point.
                    nursery.cancel_scope.cancel()
        finally:
            self.sessions.discard(session)

    async def _writeLoop(self, websocket: WebSocket, session: "UiSession") -> None:
        try:
            async for message in session._recv_channel:
                await websocket.send_text(json.dumps(message))
        except WebSocketDisconnect as err:
            log.info(
                "UI websocket send failed (site=%s, code=%s)",
                getattr(session.site, "address", None), getattr(err, "code", None),
            )
            raise
        except Exception:
            log.exception("UI websocket writer failed (site=%s)", getattr(session.site, "address", None))
            raise

    def _resolveSiteByWrapperKey(self, wrapper_key: str):
        for site in self.sites.values():
            if getattr(site, "wrapper_key", None) == wrapper_key:
                return site
        return None

    def deleteSite(self, address: str) -> None:
        """Remove a site from the manager and all UI/P2P live registries."""
        if self.site_manager is not None:
            self.site_manager.delete(address)
        if self.file_server is not None:
            self.file_server.removeSite(address)
        if self.announcers is not None:
            self.announcers.pop(address, None)

    def _isAllowedWebSocketOrigin(self, origin: str, host: str) -> bool:
        """Match the legacy same-origin WebSocket guard.

        Explicit origins are used for deployments behind a trusted proxy;
        otherwise the browser Origin's network location must match Host.
        """
        if origin in self.allowed_ws_origins:
            return True
        try:
            return urlsplit(origin).netloc == host
        except ValueError:
            return False

    def broadcast(self, channel: str, *args) -> None:
        """Port of UiWebsocket.event() -- push a "set*Info" update to
        every currently-connected session that's joined `channel` (via
        the channelJoin command), instead of just answering the one
        session that triggered the change. siteChanged/announcerChanged
        are site-scoped: only sessions connected to that same site get
        the push, matching the original (there, one UiWebsocket instance
        IS one site connection; here, self.sessions can span sites, so
        that scoping has to be explicit). Late import to avoid a circular
        import at module load time -- commands.py imports `command` from
        this module already, at the bottom of this file."""
        from . import commands

        for session in list(self.sessions):
            if channel not in session.channels:
                continue
            if channel == "siteChanged":
                site = args[0]
                if session.site is not site:
                    continue
                info = commands.formatSiteInfo(site)
                if len(args) > 1 and args[1]:
                    info.update(args[1])
                session.push("setSiteInfo", info)
            elif channel == "serverChanged":
                info = commands.formatServerInfo(session)
                if args and args[0]:
                    info.update(args[0])
                session.push("setServerInfo", info)
            elif channel == "announcerChanged":
                site = args[0]
                if session.site is not site:
                    continue
                info = commands.formatAnnouncerInfo(session, site)
                if len(args) > 1 and args[1]:
                    info.update(args[1])
                session.push("setAnnouncerInfo", info)

    async def _handleCommand(self, session: "UiSession", request: dict) -> dict:
        cmd = request.get("cmd")
        handler = COMMAND_HANDLERS.get(cmd)
        if handler is None:
            error = "Unknown command: %s" % cmd
            return {
                "cmd": "response", "to": request.get("id"),
                "error": error, "result": {"error": error},
            }
        try:
            result = await handler(session, request.get("params", {}))
        except Exception as err:
            error = str(err)
            return {
                "cmd": "response", "to": request.get("id"),
                "error": error, "result": {"error": error},
            }
        return {"cmd": "response", "to": request.get("id"), "result": result}


class UiServer:
    def __init__(self, sites: dict, host: str = "127.0.0.1", port: int = 0, allowed_hosts: list | None = None,
                 site_manager=None, user_manager=None, file_server=None, announcers: dict | None = None,
                 tor_manager=None, homepage: str | None = None, on_missing_site=None,
                 auto_download_timeout: float = 15.0, allowed_ws_origins: set[str] | None = None,
                 data_dir=None, shutdown_callback=None, ui_password: str | None = None):
        self.app = UiApp(
            sites, allowed_hosts=allowed_hosts, site_manager=site_manager, user_manager=user_manager,
            file_server=file_server, announcers=announcers, tor_manager=tor_manager,
            homepage=homepage, on_missing_site=on_missing_site, auto_download_timeout=auto_download_timeout,
            allowed_ws_origins=allowed_ws_origins, data_dir=data_dir, shutdown_callback=shutdown_callback,
            ui_password=ui_password,
        )
        self._host = host
        self._port = port
        self.bound_addresses: list[str] = []

    @asynccontextmanager
    async def run(self):
        """Async context manager: `async with ui_server.run(): ...` --
        matches P2P.Host.run()'s shape."""
        config = Config()
        config.bind = ["%s:%s" % (self._host, self._port)]
        async with trio.open_nursery() as nursery:
            self.bound_addresses = await nursery.start(serve, self.app, config)
            try:
                yield self
            finally:
                nursery.cancel_scope.cancel()


# Imported for its @command registrations (populates COMMAND_HANDLERS) --
# after UiSession/command/COMMAND_HANDLERS above, since commands.py imports
# `command` back from this module.
from . import commands  # noqa: E402,F401
