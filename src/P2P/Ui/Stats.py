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
  - gc-introspection debug tools: renderMemory (folded into /Stats when
    config.debug), /Listobj, /Dumpobj, and /GcCollect. Pure gc.get_objects()
    /sys.getsizeof() introspection with no legacy-specific dependency, so
    ported close to verbatim -- only the original's per-legacy-class
    itemized dumps (Connection/Worker/Peer/UiRequest/socket/msgpack.
    Unpacker/greenlet/Site.Site instances) were dropped, replaced with one
    native equivalent (this stack's own P2P.Site instances via app.sites)
    rather than faking gevent-era types that don't exist here.

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
  - Per-peer Bigfile piecefield introspection (the original's own
    renderBigfiles(): which known peer has which pieces of a given
    bigfile). Correction to an earlier draft of this docstring, which
    wrongly claimed Bigfile piece hashing/piecefield bookkeeping weren't
    built at all -- they are (Bigfile.py, SiteStorage.loadPiecefield/
    savePiecefield, protocols/piecefields.py, WorkerManager's real
    piece-by-piece download loop): downloading/serving/storing a
    bigfile's own pieces works end to end. What's specifically missing is
    a place to READ another peer's piecefield back out for display: the
    original reads it off its own long-lived Peer objects' cached
    .piecefields attribute, populated as a side effect of ordinary
    protocol traffic. This stack's site.peers holds lightweight
    PeerRecord metadata, not a connected session, and Peer.getPiecefields()
    is a live RPC with no cache -- so a faithful "already-known, no new
    I/O" introspection page has nothing to read yet; adding one would mean
    either triggering fresh network calls on every /Stats load (different
    cost/semantics than the original) or building real peer-piecefield
    caching first. Real, separate follow-up.
  - The original's Multiuser-proxy gate (actionStats refuses entirely
    when a public multiuser instance doesn't allow it) -- this stack's
    other diagnostic pages (/Config, /Plugins, /Console) have no such
    gating either yet; consistent with them, not a regression specific
    to this page.
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

    from Config import config
    if config.debug:
        parts.append(renderMemory(app))

    return "".join(parts)


def renderMemory(app) -> str:
    """Port of StatsPlugin.renderMemory()'s object/class/module census --
    pure gc.get_objects()/sys.getsizeof() introspection, nothing legacy-
    specific, so genuinely portable as-is. Only gated behind config.debug,
    same as the original.

    Dropped: the original's per-legacy-class itemized dumps (Connection,
    Worker, Peer, UiRequest, socket, msgpack.Unpacker, greenlet, Site.Site
    instances) -- gevent/msgpack/greenlet-specific types this stack simply
    doesn't have. Replaced with one native equivalent that IS a fair
    comparison: this stack's own P2P.Site instances via app.sites, the
    same object this page's own Sites table already reports on.
    """
    import gc

    parts = ["<h3>Memory</h3>"]

    obj_count: dict = {}
    for obj in gc.get_objects():
        key = str(type(obj))
        entry = obj_count.setdefault(key, [0, 0.0])
        entry[0] += 1
        entry[1] += sys.getsizeof(obj) / 1024

    parts.append("<p>Objects in memory (types: %s, total: %s, %.2fkb):</p>" % (
        len(obj_count), sum(v[0] for v in obj_count.values()), sum(v[1] for v in obj_count.values()),
    ))
    for obj_type, (count, size) in sorted(obj_count.items(), key=lambda i: i[1][0], reverse=True)[:50]:
        parts.append("%.1fkb = %s x <a href='/Listobj?type=%s'>%s</a><br>" % (
            size, count, html_module.escape(obj_type, quote=True), html_module.escape(obj_type),
        ))

    class_count: dict = {}
    for obj in gc.get_objects():
        if type(obj) is not object and hasattr(obj, "__class__") and hasattr(obj, "__dict__"):
            name = obj.__class__.__name__
            entry = class_count.setdefault(name, [0, 0.0])
            entry[0] += 1
            entry[1] += sys.getsizeof(obj) / 1024

    parts.append("<p>Classes in memory (types: %s, total: %s, %.2fkb):</p>" % (
        len(class_count), sum(v[0] for v in class_count.values()), sum(v[1] for v in class_count.values()),
    ))
    for class_name, (count, size) in sorted(class_count.items(), key=lambda i: i[1][0], reverse=True)[:50]:
        parts.append("%.1fkb = %s x <a href='/Dumpobj?class=%s'>%s</a><br>" % (
            size, count, html_module.escape(class_name, quote=True), html_module.escape(class_name),
        ))

    from ..Site import Site
    sites = [obj for obj in gc.get_objects() if isinstance(obj, Site)]
    parts.append("<p>P2P.Site instances (%s):</p>" % len(sites))
    for site in sites:
        parts.append("%.1fkb: %s<br>" % (sys.getsizeof(site) / 1024, html_module.escape(repr(site))))

    modules = sorted((name, mod) for name, mod in sys.modules.items() if mod is not None)
    parts.append("<p>Modules (%s):</p>" % len(modules))
    for name, mod in modules:
        parts.append("%.3fkb: %s %s<br>" % (sys.getsizeof(mod) / 1024, html_module.escape(name), html_module.escape(repr(mod))))

    return "".join(parts)


def renderDumpobj(class_filter: str) -> str:
    """Port of actionDumpobj(): every live instance of one class name
    (matched by __class__.__name__, same as the original), with its full
    attribute dump. Debug-only, same gate as renderMemory()."""
    import gc

    parts = ["<!doctype html><title>Dumpobj</title>", STYLE]
    for obj in gc.get_objects():
        if not hasattr(obj, "__class__") or not hasattr(obj, "__dict__") or obj.__class__.__name__ != class_filter:
            continue
        parts.append("<p>%.1fkb %s...</p>" % (sys.getsizeof(obj) / 1024, html_module.escape(str(obj))))
        for attr in dir(obj):
            try:
                value = getattr(obj, attr)
            except Exception as err:
                value = "! Error reading attribute: %r" % err
            parts.append("- %s: %s<br>" % (html_module.escape(attr), html_module.escape(str(value))))
    return "".join(parts)


def renderListobj(type_filter: str) -> str:
    """Port of actionListobj(): every live object of one exact str(type(obj))
    value, with its non-container referrers -- same "who's holding this
    alive" diagnostic as the original, same debug-only gate."""
    import gc

    parts = ["<!doctype html><title>Listobj</title>", STYLE]
    parts.append("<p>Listing all %s objects in memory...</p>" % html_module.escape(type_filter))

    ref_count: dict = {}
    for obj in gc.get_objects():
        if str(type(obj)) != type_filter:
            continue
        refs = [
            ref for ref in gc.get_referrers(obj)
            if hasattr(ref, "__class__") and
            ref.__class__.__name__ not in ("list", "dict", "function", "type", "frame", "WeakSet", "tuple")
        ]
        if not refs:
            continue
        try:
            parts.append("%.1fkb <span title='%s'>%s</span>... " % (
                sys.getsizeof(obj) / 1024, html_module.escape(str(obj), quote=True), html_module.escape(str(obj)[:100]),
            ))
        except Exception:
            continue
        for ref in refs:
            ref_type = ref.__class__.__name__
            label = ref_type if ("object at" in str(ref) or len(str(ref)) > 100) else "%s:%s" % (ref_type, ref)
            parts.append("[%s] " % html_module.escape(label))
            entry = ref_count.setdefault(ref_type, [0, 0.0])
            entry[0] += 1
            entry[1] += sys.getsizeof(obj) / 1024
        parts.append("<br>")

    parts.append("<p>Object referrers (total: %s, %.2fkb):</p>" % (
        len(ref_count), sum(v[1] for v in ref_count.values()),
    ))
    for ref_type, (count, size) in sorted(ref_count.items(), key=lambda i: i[1][0], reverse=True)[:30]:
        parts.append(" - %.1fkb = %s x %s<br>" % (size, count, html_module.escape(ref_type)))

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
