"""Trio port of a scoped slice of plugins/Sidebar/ConsolePlugin.py --
just consoleLogRead, a one-shot tail of the debug log file. Same
"add new websocket commands" pattern P2P/plugins/CryptMessage and
P2P/plugins/Newsfeed established -- see CryptMessage's own module
docstring for why no special import-ordering is needed for this.

Deliberately NOT ported: consoleLogStream/consoleLogStreamRemove --
the original streams new log lines to the client unprompted, by
registering a logging.Handler that calls ui_websocket.cmd(...) whenever
a new record is emitted. That's a server-initiated push to an arbitrary,
already-connected session outside of any request/response cycle --
UiApp/UiSession here have no such mechanism (every other command is a
plain request-in, response-out handler). Building that push path is a
real, separate piece of infrastructure, not a small addition on top of
what's here.

Also not ported: the rest of plugins/Sidebar/SidebarPlugin.py (HTML
sidebar tag rendering, peer info panels, owned-site/privatekey
management, DB reload/rebuild) -- a much larger surface, out of scope
for this pass, which is specifically about proving simple new-command
plugins keep landing cleanly.
"""
import re

from Config import config
from util import SafeRe

from P2P.Ui.commands import CommandError, _param, _requireAdmin, command


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
