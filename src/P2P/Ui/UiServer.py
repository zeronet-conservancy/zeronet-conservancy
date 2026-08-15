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
"""
import json
import pathlib
from contextlib import asynccontextmanager

import trio
from hypercorn.config import Config
from hypercorn.trio import serve
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from ..SiteStorage import AccessError
from .Wrapper import renderWrapper

UI_MEDIA_DIR = pathlib.Path(__file__).resolve().parents[2] / "Ui" / "media"

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
    explicitly."""
    def __init__(self, app: "UiApp", site=None):
        self.app = app
        self.site = site
        self.channels: list = []


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
    def __init__(self, sites: dict, allowed_hosts: list | None = None):
        self.sites = sites  # site address -> P2P.Site
        self.wrapper_nonces: list = []

        routes = [
            Route("/{address}/{inner_path:path}", self._handleSite, methods=["GET"]),
            Route("/{address}", self._handleSite, methods=["GET"]),
            WebSocketRoute("/Ui", self._handleWebsocket),
        ]
        if UI_MEDIA_DIR.is_dir():
            routes.insert(0, Mount("/uimedia", app=StaticFiles(directory=str(UI_MEDIA_DIR)), name="uimedia"))

        middleware = [
            Middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ["127.0.0.1", "localhost"]),
            Middleware(CORSMiddleware, allow_origins=[], allow_credentials=False),
        ]

        self._asgi = Starlette(routes=routes, middleware=middleware)

    async def __call__(self, scope, receive, send) -> None:
        await self._asgi(scope, receive, send)

    async def _handleSite(self, request: Request) -> Response:
        address = request.path_params["address"]
        inner_path = request.path_params.get("inner_path", "")

        site = self.sites.get(address)
        if site is None or not site.isServing():
            return Response(b"Unknown site", status_code=404)

        is_html_page = inner_path in ("", "/") or inner_path.endswith("/") or inner_path.endswith(".html")
        wants_wrapper = request.query_params.get("wrapper") != "0"

        if is_html_page and wants_wrapper:
            body = renderWrapper(
                site,
                scheme=request.url.scheme,
                host=request.url.hostname or "127.0.0.1",
                site_file_server_port=request.url.port or 80,
                address=address,
                inner_path=inner_path or "index.html",
                title=address,
            )
            return Response(body, media_type="text/html")

        target_path = inner_path or "content.json"
        try:
            if not site.storage.isFile(target_path):
                return Response(b"File not found", status_code=404)
            data = await site.storage.read(target_path)
        except AccessError:
            return Response(b"Invalid path", status_code=403)

        return Response(data, media_type=_guessContentType(target_path))

    async def _handleWebsocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        wrapper_key = websocket.query_params.get("wrapper_key")
        site = self._resolveSiteByWrapperKey(wrapper_key) if wrapper_key else None
        session = UiSession(self, site=site)
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    request = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                response = await self._handleCommand(session, request)
                await websocket.send_text(json.dumps(response))
        except WebSocketDisconnect:
            return

    def _resolveSiteByWrapperKey(self, wrapper_key: str):
        for site in self.sites.values():
            if getattr(site, "wrapper_key", None) == wrapper_key:
                return site
        return None

    async def _handleCommand(self, session: "UiSession", request: dict) -> dict:
        cmd = request.get("cmd")
        handler = COMMAND_HANDLERS.get(cmd)
        if handler is None:
            return {"cmd": "response", "to": request.get("id"), "error": "Unknown command: %s" % cmd}
        try:
            result = await handler(session, request.get("params", {}))
        except Exception as err:
            return {"cmd": "response", "to": request.get("id"), "error": str(err)}
        return {"cmd": "response", "to": request.get("id"), "result": result}


class UiServer:
    def __init__(self, sites: dict, host: str = "127.0.0.1", port: int = 0, allowed_hosts: list | None = None):
        self.app = UiApp(sites, allowed_hosts=allowed_hosts)
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
