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

Also NOT ported: optionalHelpList/Help/HelpRemove/HelpAll (the
"distribute help" seeding-priority feature) -- depends on
site.settings["optional_help"], a settings dict this stack's Site
doesn't have; a genuinely separate concern from file tracking itself,
not a small addition on top of what's here.
"""
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
