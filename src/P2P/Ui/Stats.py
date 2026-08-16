"""Real, but narrow, port of plugins/Stats/StatsPlugin.py's own
actionStats()/testEnv() -- a live diagnostics page, not a websocket
command surface, so it doesn't fit the bucket-3 command-by-command
discipline P2P/Ui/commands.py follows; rendered straight to HTML server-
side instead, the same "plain HTML string, no client-side JS driving it"
shape sitePublish's own confirm dialogs use.

Ported for real, using this stack's own real data:
  - Head summary: peer_id, listen addresses, site count.
  - Trackers: discovery.tracker.global_tracker_stats -- the same shared
    instance SiteAnnouncer.announce() itself checks for reliability, not
    a stub. Matches the original's own self.stats/global_stats split
    (see that module's own docstring): this is the global one.
  - Tor: tor_manager.status, when a TorManager is configured.
  - Sites: address, known-peer count, content.json load count.
  - /About (renderAbout): real installed-library versions for the
    packages this stack's own async core actually depends on (trio,
    libp2p, hypercorn, starlette, jinja2) plus Python/platform/SQLite
    info -- the original's own list (gevent, msgpack, merkletools, ...)
    describes a different runtime and isn't this stack's dependency set.

Deliberately NOT ported, because the thing it needs doesn't exist in
this stack (or isn't a good match), same "narrow but real" discipline as
the rest of this package:
  - Per-connection table (crypto cipher, ping, buffers, bytes in/out,
    last command) -- the original reads rich attributes off its own
    Connection objects (crypt, handshake, bad_actions, waiting_requests)
    that a libp2p Swarm's connection/stream objects don't expose in the
    same shape at all; real, separate introspection work.
  - Db stats (Db.opened_dbs) -- P2P.Db doesn't track a process-wide
    opened-database registry the way the original's Db.py does (see
    SiteStorage.py's own module docstring on what's NOT wired up there).
  - Per-site bytes_sent/bytes_recv and sent/received command byte
    tallies -- never tracked anywhere in this stack (see
    Sidebar/render.py's own docstring making the identical point about
    the sidebar's transfer-stats section); faking a number here would be
    a lie, not a simplification.
  - Bigfile piecefield introspection -- Bigfile Layers B-D (piece
    hashing, piecefield bookkeeping) aren't built, so there's nothing to
    introspect.
  - The original's Multiuser-proxy gate (actionStats refuses entirely
    when a public multiuser instance doesn't allow it) -- this stack's
    other diagnostic pages (/Config, /Plugins, /Console) have no such
    gating either yet; consistent with them, not a regression specific
    to this page.
  - gc-introspection debug tools (renderMemory/actionDumpobj/
    actionListobj/actionGcCollect) -- pure Python object-graph
    inspection with no legacy-specific dependencies, so genuinely
    portable, just not scoped into this pass; a plausible small
    follow-up.
"""
import html as html_module
import platform
import sqlite3
import sys
import time

STYLE = "<style>* { font-family: monospace } table td, table th { text-align: right; padding: 0 10px }</style>"


def _row(cells) -> str:
    return "<tr>" + "".join("<td>%s</td>" % c for c in cells) + "</tr>"


def renderStats(app) -> str:
    parts = ["<!doctype html><title>Stats</title>", STYLE]

    file_server = getattr(app, "file_server", None)
    if file_server is not None:
        addrs = ", ".join(html_module.escape(str(a)) for a in file_server.host.get_addrs())
        parts.append(
            "<p>Peer ID: %s<br>Listening: %s<br>Sites: %s</p>"
            % (html_module.escape(str(file_server.host.peer_id)), addrs, len(app.sites))
        )
    else:
        parts.append("<p>No file server configured.</p>")

    tor_manager = getattr(app, "tor_manager", None)
    if tor_manager is not None:
        parts.append("<p>Tor: %s</p>" % html_module.escape(str(tor_manager.status)))

    from ..discovery.tracker import global_tracker_stats
    parts.append("<h3>Trackers</h3><table><tr><th>address</th><th>requests</th><th>errors</th><th>last request</th></tr>")
    for tracker, stat in sorted(global_tracker_stats.all().items()):
        since = ("%.0fs ago" % (time.time() - stat["time_request"])) if stat["time_request"] else "n/a"
        parts.append(_row([html_module.escape(tracker), stat["num_request"], stat["num_error"], since]))
    parts.append("</table>")

    parts.append("<h3>Sites</h3><table><tr><th>address</th><th>known peers</th><th>content.json loaded</th></tr>")
    for site in app.sites.values():
        contents = site.content_manager.contents
        loaded = len([v for v in contents.values() if v])
        parts.append(_row([
            html_module.escape(site.address),
            len(site.peers),
            "%s/%s" % (loaded, len(contents)),
        ]))
    parts.append("</table>")

    return "".join(parts)


def renderAbout() -> str:
    import importlib
    from Config import config

    parts = ["<!doctype html><title>About</title>", STYLE, "<h3>Environment</h3><table>"]
    parts.append(_row(["zeronet-conservancy version:", html_module.escape(str(config.version_full))]))
    parts.append(_row(["Python:", html_module.escape(sys.version)]))
    parts.append(_row(["Platform:", html_module.escape(platform.platform())]))
    parts.append(_row(["SQLite:", "%s, API: %s" % (sqlite3.sqlite_version, sqlite3.version)]))
    parts.append("</table><h3>Libraries</h3><table>")
    for lib_name in ("trio", "libp2p", "hypercorn", "starlette", "jinja2", "multiaddr"):
        try:
            module = importlib.import_module(lib_name)
            version = getattr(module, "__version__", None) or getattr(module, "version", "unknown version")
            parts.append(_row(["- %s:" % lib_name, html_module.escape(str(version))]))
        except Exception as err:
            parts.append(_row(["! Error importing %s:" % lib_name, html_module.escape(repr(err))]))
    parts.append("</table>")

    return "".join(parts)
