"""Trio port of a scoped slice of plugins/Sidebar/ConsolePlugin.py --
consoleLogRead, consoleLogStream, and consoleLogStreamRemove. Same
"add new websocket commands" pattern P2P/plugins/CryptMessage and
P2P/plugins/Newsfeed established -- see CryptMessage's own module
docstring for why no special import-ordering is needed for this.

consoleLogStream/consoleLogStreamRemove are the first commands in this
stack to use UiSession.push()/UiSession.nursery -- see UiServer.py's own
module docstring for that infrastructure. A logging.Handler registered
process-wide calls session.push() synchronously from inside emit()
(push() never awaits, so this is safe from a plain callback); the handler
itself lives inside a background task spawned on session.nursery via
nursery.start(), which blocks until the handler is actually registered
before consoleLogStream returns its response -- matching the original's
own synchronous addLogStreamer() call before responding, so no log lines
between response and next log call are lost. The stream_id the original
reused from the request's own message `to` isn't available to a plain
(session, params) handler here, so a random one is minted instead and
returned in the response; consoleLogStreamRemove takes it back to cancel
just that one background task via a stashed trio.CancelScope in
session.state, without touching the rest of the connection. Disconnecting
without an explicit consoleLogStreamRemove still cleans up correctly --
closing the connection cancels session.nursery, which cancels every
background task it holds, including any live log streams.

sidebarGetHtmlTag (added later, see render.py's own module docstring for
scope) is what actually turned out to be needed for the fixbutton's
drag-to-open-sidebar gesture to render anything -- found live, driving
the real ZeroHello dashboard, chasing a user report that the drag
gesture ("pull down for log, pull left for sidebar") used to work.
That investigation also found the real root cause of why the gesture's
JS didn't even run: the legacy plugin-media-injection mechanism
(UiRequestPlugin.actionUiMedia appending a plugin's own media/all.js
onto /uimedia/all.js) was never ported at all -- see UiServer.py's
_handleUiMediaExtra for that half of the fix.

Still NOT ported: privatekey management (siteRecoverPrivatekey/
userSetSitePrivatekey -- bip32 per-site key derivation, a separate
concern from just displaying the sidebar), fileRules, and
dbReload/dbRebuild as sidebar-triggerable actions (dbRebuild exists
as a CLI-only action in P2P/actions.py, same
"destructive, not a great fit for an unauthenticated-beyond-wrapper_key
websocket command" reasoning P2P/Ui/commands.py's own module docstring
already gives for it).
"""
import logging
import re
import uuid

import trio

from Config import config
from util import SafeRe

from P2P.Ui.commands import CommandError, _param, _requireAdmin, _requireSite, _requireSiteManager, command, formatSiteInfo

from .render import renderSidebarHtml


@command("consoleLogRead")
async def _cmdConsoleLogRead(session, params):
    _requireAdmin(session)

    filter_pattern = _param(params, "filter", 0)
    read_size = _param(params, "read_size", 1, 32 * 1024)
    limit = _param(params, "limit", 2, 500)

    log_file_path = "%s/debug.log" % config.log_dir
    try:
        log_file = open(log_file_path, encoding="utf-8")
    except OSError as err:
        raise CommandError("Could not open log file: %s" % err)

    with log_file:
        log_file.seek(0, 2)
        end_pos = log_file.tell()
        log_file.seek(max(0, end_pos - read_size))
        if log_file.tell() != 0:
            log_file.readline()  # Partial line junk

        pos_start = log_file.tell()
        lines = []
        filter_re = None
        if filter_pattern:
            SafeRe.guard(filter_pattern)
            filter_re = re.compile(".*" + filter_pattern)

        last_match = False
        for line in log_file:
            if not line.startswith("[") and last_match:  # Multi-line log entry
                lines.append(line.replace(" ", "&nbsp;"))
                continue

            if filter_re and not filter_re.match(line):
                last_match = False
                continue
            last_match = True
            lines.append(line)

        num_found = len(lines)
        lines = lines[-limit:]

        return {"lines": lines, "pos_end": log_file.tell(), "pos_start": pos_start, "num_found": num_found}


class _WsLogStreamer(logging.Handler):
    def __init__(self, session, stream_id, filter_pattern):
        super().__init__()
        self.session = session
        self.stream_id = stream_id
        self.filter_re = None
        if filter_pattern:
            SafeRe.guard(filter_pattern)
            self.filter_re = re.compile(".*" + filter_pattern)
        self.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s %(name)s %(message)s"))

    def emit(self, record):
        try:
            line = self.format(record)
        except Exception:
            return
        if self.filter_re and not self.filter_re.match(line):
            return
        self.session.push("logLineAdd", {"stream_id": self.stream_id, "lines": [line]})


async def _runLogStream(session, stream_id, filter_pattern, cancel_scope, streamers,
                         *, task_status=trio.TASK_STATUS_IGNORED):
    handler = _WsLogStreamer(session, stream_id, filter_pattern)
    root_logger = logging.getLogger("")
    with cancel_scope:
        root_logger.addHandler(handler)
        task_status.started()
        try:
            await trio.sleep_forever()
        finally:
            root_logger.removeHandler(handler)
    streamers.pop(stream_id, None)


@command("consoleLogStream")
async def _cmdConsoleLogStream(session, params):
    _requireAdmin(session)
    if session.nursery is None:
        raise CommandError("This session has no background task nursery")

    filter_pattern = _param(params, "filter", 0)
    stream_id = uuid.uuid4().hex
    cancel_scope = trio.CancelScope()
    streamers = session.state.setdefault("log_streamers", {})
    streamers[stream_id] = cancel_scope

    await session.nursery.start(_runLogStream, session, stream_id, filter_pattern, cancel_scope, streamers)
    return {"stream_id": stream_id}


@command("consoleLogStreamRemove")
async def _cmdConsoleLogStreamRemove(session, params):
    _requireAdmin(session)
    stream_id = _param(params, "stream_id", 0)
    streamers = session.state.get("log_streamers", {})
    cancel_scope = streamers.pop(stream_id, None)
    if cancel_scope is None:
        return {"error": "Unknown stream_id"}
    cancel_scope.cancel()
    return "ok"


@command("sidebarGetHtmlTag")
async def _cmdSidebarGetHtmlTag(session, params):
    """Not admin-gated in the original either (any connected site can open
    its own sidebar; individual actions inside it, like siteSetOwned/
    siteSetLimit, are the ones gated on ADMIN) -- render.py itself hides
    the own-site/controls sections when the connection isn't ADMIN."""
    site = _requireSite(session)
    site_manager = getattr(session.app, "site_manager", None)
    is_admin = "ADMIN" in site.permissions
    is_own = site_manager.isOwn(site.address) if site_manager else False
    formatted_info = formatSiteInfo(site, site_manager)
    return renderSidebarHtml(site, formatted_info, is_own, is_admin)
