"""Trio port of a scoped slice of plugins/OptionalManager/UiWebsocketPlugin.py --
optionalFileList/Info/Pin/Unpin/Delete and optionalLimitStats/Set. Same
"add new commands" pattern P2P/plugins/CryptMessage established -- no
registerTo() overrides needed, so no import-ordering ceremony either.

The original's optional-file tracking is a real SQL table
(`file_optional`, keyed by site_id/hash_id/inner_path) that a whole
chain of infrastructure keeps in sync: ContentManager.optionalDownloaded()/
optionalRemoved() write to it as files actually complete downloading or
get deleted, and it also tracks bigfile piece-level download progress,
per-file peer seed/leech counts, and cross-site aggregation (`address=
"all"`). None of that write-path infrastructure exists in this stack --
there's no on-download-complete hook to write into, and no such SQL
table. Faithfully porting the table without the writers that keep it
accurate would just be a lie in a different shape.

Instead, "downloaded" here is answered directly from disk
(site.storage.isFile()) at query time, not from a persisted flag --
real, always-accurate, but can't distinguish "never downloaded" from
"downloaded then externally deleted" the way a tracked flag could, and
can't report progress mid-download (there is no mid-download state to
report; a file exists on disk once it exists, full stop). storage.py's
sidecar only holds what can't be derived from disk alone: pin state, a
size limit, and a first-seen download timestamp (backfilled lazily the
first time a downloaded-but-untracked file is listed/inspected, rather
than needing a write-time hook). Cross-site aggregation (address="all")
and bigfile piece/peer-seed-leech stats are not ported.

optionalHelpList/OptionalHelp/OptionalHelpRemove/OptionalHelpAll (the
"distribute help" seeding-priority feature) are ported now too, found
live auditing every bundled site's own Page.cmd() calls against this
stack's registered commands (the same investigation that found
fileRules missing for ZeroMail): the real dashboard site's own optional-
files manager calls these under their original, capitalized names
(OptionalHelp, not optionalHelp), unlike every other command here.
site.settings["optional_help"]/["autodownloadoptional"] (a Site-level
settings dict this stack's Site doesn't have) become two more fields
in OptionalFilesStorage's own sidecar instead -- same choice this
module already made for pin state/size limit, for the same reason.

Narrower than the original two ways, both matching this module's own
existing scope: no cross-site `address` param (the original lets an
ADMIN dashboard manage a DIFFERENT site's optional files remotely;
none of optionalFileList/Info/Pin/etc. support that either, so this
doesn't introduce a new gap, just stays consistent). And OptionalHelpAll
skips the original's confirm-dialog round trip for a non-ADMIN
connection before enabling autodownload -- this stack has no server-
initiated request/response continuation mechanism yet (same gap
corsPermission's own docstring notes) -- so turning it on always takes
effect immediately. Not a bug: the original's confirm() was a UX nicety,
not an actual permission check (the connected session could already
read/write this site's own settings either way).
"""
import html
import shutil

from P2P.ContentManager import _getDirname
from P2P.Bigfile import piece_count, piece_range
from P2P.Ui.commands import _param, _requireAdmin, _requireSite, command

from .storage import OptionalFilesStorage

_storages: dict[str, OptionalFilesStorage] = {}


def _storageFor(site) -> OptionalFilesStorage:
    storage = _storages.get(site.address)
    if storage is None:
        storage = OptionalFilesStorage(site.storage.getPath(".optional_files.json"))
        _storages[site.address] = storage
    return storage


def _listOptionalFiles(site):
    """Every files_optional entry declared across this site's currently
    loaded content.json files, with each entry's own content_dir prefix
    applied -- same pattern P2P.Ui.commands' siteListModifiedFiles uses
    for "files"."""
    back = []
    for content_inner_path, content in site.content_manager.contents.items():
        content_dir = _getDirname(content_inner_path)
        for relative_path, file_info in content.get("files_optional", {}).items():
            back.append((content_dir + relative_path, file_info.get("size", 0)))
    return back


def _fileInfo(site, inner_path):
    return site.content_manager.getFileInfo(inner_path) or {}


async def _progress(site, inner_path, size, file_info):
    piece_size = file_info.get("piece_size")
    if not piece_size:
        downloaded = site.storage.isFile(inner_path)
        return {
            "pieces_downloaded": 1 if downloaded else 0,
            "piece_count": 1,
            "bytes_downloaded": size if downloaded else 0,
        }

    count = piece_count(size, int(piece_size))
    file_hash = file_info.get("sha512", "")
    field = await site.storage.loadPiecefield(file_hash, count)
    sidecar_exists = site.storage._piecefieldPath(file_hash).is_file()
    if not sidecar_exists and site.storage.isFile(inner_path) and site.storage.getSize(inner_path) == size:
        # Files downloaded by the legacy stack have no native sidecar but are
        # complete when their declared size matches.
        completed = count
    else:
        completed = field.completed()
    if not sidecar_exists and completed == count:
        bytes_downloaded = size
    else:
        bytes_downloaded = sum(
            piece_range(size, int(piece_size), piece_index)[1]
            - piece_range(size, int(piece_size), piece_index)[0]
            for piece_index in range(count) if field[piece_index]
        )
    return {
        "pieces_downloaded": completed,
        "piece_count": count,
        "bytes_downloaded": bytes_downloaded,
    }


def _asList(value):
    return value if isinstance(value, list) else [value]


@command("optionalFileList")
async def _cmdOptionalFileList(session, params):
    site = _requireSite(session)
    filter_value = _param(params, "filter", 0, "downloaded")
    filter_inner_path = _param(params, "filter_inner_path", 1)
    limit = _param(params, "limit", 2, 10)

    storage = _storageFor(site)
    back = []
    for inner_path, size in _listOptionalFiles(site):
        if filter_inner_path and filter_inner_path not in inner_path:
            continue
        is_downloaded = site.storage.isFile(inner_path)
        entry = storage.getEntry(inner_path)
        file_info = _fileInfo(site, inner_path)
        progress = await _progress(site, inner_path, size, file_info)
        is_downloaded = progress["pieces_downloaded"] == progress["piece_count"]
        is_pinned = entry.get("is_pinned", False)
        if "downloaded" in filter_value and not (is_downloaded or is_pinned):
            continue
        if "pinned" in filter_value and not is_pinned:
            continue
        if is_downloaded and "time_downloaded" not in entry:
            storage.markDownloaded(inner_path, size)
            entry = storage.getEntry(inner_path)
        back.append({
            "inner_path": inner_path,
            "size": size,
            "is_downloaded": is_downloaded,
            "is_pinned": is_pinned,
            "time_downloaded": entry.get("time_downloaded"),
            **progress,
        })
    back.sort(key=lambda row: row.get("time_downloaded") or 0, reverse=True)
    return back[:limit]


@command("optionalFileInfo")
async def _cmdOptionalFileInfo(session, params):
    site = _requireSite(session)
    inner_path = _param(params, "inner_path", 0)
    storage = _storageFor(site)
    entry = storage.getEntry(inner_path)
    is_downloaded = site.storage.isFile(inner_path)
    if not is_downloaded and not entry:
        return None
    file_info = _fileInfo(site, inner_path)
    size = file_info.get("size", site.storage.getSize(inner_path) if is_downloaded else entry.get("size", 0))
    progress = await _progress(site, inner_path, size, file_info)
    is_downloaded = progress["pieces_downloaded"] == progress["piece_count"]
    return {
        "inner_path": inner_path,
        "size": size,
        "is_downloaded": is_downloaded,
        "is_pinned": entry.get("is_pinned", False),
        "time_downloaded": entry.get("time_downloaded"),
        **progress,
    }


@command("optionalFilePin")
async def _cmdOptionalFilePin(session, params):
    site = _requireSite(session)
    storage = _storageFor(site)
    for inner_path in _asList(_param(params, "inner_path", 0)):
        storage.setPinned(inner_path, True)
    return "ok"


@command("optionalFileUnpin")
async def _cmdOptionalFileUnpin(session, params):
    site = _requireSite(session)
    storage = _storageFor(site)
    for inner_path in _asList(_param(params, "inner_path", 0)):
        storage.setPinned(inner_path, False)
    return "ok"


@command("optionalFileDelete")
async def _cmdOptionalFileDelete(session, params):
    site = _requireSite(session)
    inner_path = _param(params, "inner_path", 0)
    if not site.storage.isFile(inner_path):
        return {"error": "File not found"}
    await site.storage.delete(inner_path)
    _storageFor(site).forget(inner_path)
    return "ok"


_DEFAULT_LIMIT = "10%"  # Matches the original's own --optional-limit default


@command("optionalLimitStats")
async def _cmdOptionalLimitStats(session, params):
    """limit falls back to _DEFAULT_LIMIT, not storage.getLimit()'s raw
    None -- found live: the real wrapper.js's PageFiles.updateOptionalStats()
    calls res.limit.endsWith("%") unconditionally, and a site that never
    called optionalLimitSet (i.e. every fresh site) crashed on page load
    the moment this command started actually responding (it was itself
    "Unknown command" until the plugin-loading collision fix, which had
    been masking this)."""
    site = _requireAdmin(session)
    storage = _storageFor(site)
    used = sum(
        site.storage.getSize(inner_path)
        for inner_path, _size in _listOptionalFiles(site)
        if site.storage.isFile(inner_path)
    )
    free = shutil.disk_usage(site.storage.getPath("")).free
    return {"limit": storage.getLimit() or _DEFAULT_LIMIT, "used": used, "free": free}


@command("optionalLimitSet")
async def _cmdOptionalLimitSet(session, params):
    site = _requireAdmin(session)
    limit = _param(params, "limit", 0)
    _storageFor(site).setLimit(limit)
    return "ok"


@command("optionalHelpList")
async def _cmdOptionalHelpList(session, params):
    site = _requireSite(session)
    return _storageFor(site).getOptionalHelp()


@command("OptionalHelp")
async def _cmdOptionalHelp(session, params):
    """Marks `directory` as one this node actively helps seed and returns
    how many currently-known optional files (and total bytes) fall under
    it -- the original's own SQL COUNT/SUM over its file_optional table,
    replaced here with the same _listOptionalFiles() scan every other
    command in this file already uses instead of that table (see this
    module's own docstring)."""
    site = _requireSite(session)
    directory = _param(params, "directory", 0)
    title = _param(params, "title", 1)
    storage = _storageFor(site)
    storage.setOptionalHelp(directory, title)

    num = 0
    size = 0
    for inner_path, file_size in _listOptionalFiles(site):
        if inner_path.startswith(directory):
            num += 1
            size += file_size

    session.push("notification", [
        "done",
        "You started to help distribute <b>%s</b>.<br><small>Directory: %s</small>"
        % (html.escape(title), html.escape(directory)),
        10000,
    ])
    return {"num": num, "size": size}


@command("OptionalHelpRemove")
async def _cmdOptionalHelpRemove(session, params):
    site = _requireSite(session)
    directory = _param(params, "directory", 0)
    if _storageFor(site).removeOptionalHelp(directory):
        return "ok"
    return {"error": "Not found"}


@command("OptionalHelpAll")
async def _cmdOptionalHelpAll(session, params):
    site = _requireSite(session)
    value = bool(_param(params, "value", 0))
    _storageFor(site).setAutodownloadOptional(value)
    return value
