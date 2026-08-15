"""Trio-native replacement for Ui/UiServer.py + Ui/UiRequest.py's routing,
served via Hypercorn's trio worker instead of gevent.pywsgi.WSGIServer +
the custom src/lib/gevent_ws WebSocketHandler. Hypercorn is a maintained
ASGI server with native trio support and built-in WebSocket handling, so
this is an ASGI-app rewrite of routing/serving rather than a from-scratch
HTTP/WS protocol implementation -- the whole point of picking it over
hand-rolling h11/trio-websocket directly.

Scoped to the actual technical risk this phase needs to retire: does
Hypercorn's trio worker correctly serve HTTP and WebSocket, wired to the
trio-native Site/SiteStorage stack built in Phase 6? Ported: basic HTTP
routing, serving a real file out of a site's SiteStorage (the core of
actionSiteMedia), and a WebSocket upgrade + minimal command round-trip
(the core of actionWebsocket). NOT ported: wrapper HTML rendering (Jinja2
templating), the ~1400-line websocket command API (UiWebsocket.py --
siteInfo/sitePublish/fileGet/etc., one command at a time in later
sessions, same pattern as protocols/*.py), CORS/host-allowlist security,
auth/cookies, UiMedia (the UI's own static assets).
"""
import json
from contextlib import asynccontextmanager

import trio
from hypercorn.config import Config
from hypercorn.trio import serve

from ..SiteStorage import AccessError

COMMAND_HANDLERS = {}


def command(name):
    def decorator(fn):
        COMMAND_HANDLERS[name] = fn
        return fn
    return decorator


@command("ping")
async def _cmdPing(app, params):
    return "pong"


class UiApp:
    """The ASGI application itself -- a callable(scope, receive, send),
    same shape any ASGI server (Hypercorn, uvicorn, etc.) expects."""

    def __init__(self, sites: dict):
        self.sites = sites  # site address -> P2P.Site

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http":
            await self._handleHttp(scope, send)
        elif scope["type"] == "websocket":
            await self._handleWebsocket(receive, send)
        elif scope["type"] == "lifespan":
            await self._handleLifespan(receive, send)

    async def _handleLifespan(self, receive, send) -> None:
        """ASGI lifespan protocol: hypercorn waits for an explicit
        startup/shutdown handshake before nursery.start() considers the
        server ready -- skipping this isn't optional, the app hangs (or
        the channel closes early) without it."""
        while True:
            event = await receive()
            if event["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif event["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    async def _handleHttp(self, scope, send) -> None:
        parts = scope["path"].strip("/").split("/", 1)
        site_address = parts[0] if parts else ""
        inner_path = parts[1] if len(parts) > 1 and parts[1] else "content.json"

        site = self.sites.get(site_address)
        if site is None or not site.isServing():
            await self._respond(send, 404, b"Unknown site")
            return

        try:
            if not site.storage.isFile(inner_path):
                await self._respond(send, 404, b"File not found")
                return
            data = await site.storage.read(inner_path)
        except AccessError:
            await self._respond(send, 403, b"Invalid path")
            return

        await self._respond(send, 200, data, content_type=_guessContentType(inner_path))

    async def _respond(self, send, status: int, body: bytes, content_type: str = "text/plain") -> None:
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", content_type.encode())],
        })
        await send({"type": "http.response.body", "body": body})

    async def _handleWebsocket(self, receive, send) -> None:
        event = await receive()
        if event["type"] != "websocket.connect":
            return
        await send({"type": "websocket.accept"})

        while True:
            event = await receive()
            if event["type"] == "websocket.disconnect":
                return
            if event["type"] != "websocket.receive":
                continue

            raw = event.get("text")
            if raw is None:
                raw = (event.get("bytes") or b"").decode("utf8", "ignore")
            try:
                request = json.loads(raw)
            except (ValueError, TypeError):
                continue

            response = await self._handleCommand(request)
            await send({"type": "websocket.send", "text": json.dumps(response)})

    async def _handleCommand(self, request: dict) -> dict:
        cmd = request.get("cmd")
        handler = COMMAND_HANDLERS.get(cmd)
        if handler is None:
            return {"cmd": "response", "to": request.get("id"), "error": "Unknown command: %s" % cmd}
        try:
            result = await handler(self, request.get("params", {}))
        except Exception as err:
            return {"cmd": "response", "to": request.get("id"), "error": str(err)}
        return {"cmd": "response", "to": request.get("id"), "result": result}


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


class UiServer:
    def __init__(self, sites: dict, host: str = "127.0.0.1", port: int = 0):
        self.app = UiApp(sites)
        self.config = Config()
        self.config.bind = ["%s:%s" % (host, port)]
        self.bound_addresses: list[str] = []

    @asynccontextmanager
    async def run(self):
        """Async context manager: `async with ui_server.run(): ...` --
        matches P2P.Host.run()'s shape. Uses @asynccontextmanager rather
        than manually driving a nursery's __aenter__/__aexit__ (trio
        explicitly disallows that outside of with/async-with -- it
        corrupts the nursery's internal state)."""
        async with trio.open_nursery() as nursery:
            self.bound_addresses = await nursery.start(serve, self.app, self.config)
            try:
                yield self
            finally:
                nursery.cancel_scope.cancel()
