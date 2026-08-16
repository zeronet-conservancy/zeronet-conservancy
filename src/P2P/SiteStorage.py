"""Trio port of Site/SiteStorage.py -- the pure file I/O layer (getPath
and friends, open/read/write/delete/rename/walk/list/loadJson/writeJson)
plus the DB-backed methods (getDb/loadDb/rebuildDb/query/updateDbFile),
now that P2P.Db exists. verifyFiles/deleteFiles still need ContentManager
pieces (hashfield) not ported yet.

Blocking disk I/O is offloaded to a P2P.ThreadPool (matching the
original's thread_pool_fs_read/thread_pool_fs_write wrapping) so it
doesn't stall the trio event loop.

DB methods stay decoupled from ContentManager, unlike the original (which
reaches through self.site.content_manager.contents): this SiteStorage
has no back-reference to a Site or ContentManager at all (constructed
before ContentManager, per Site.py's __init__), so getDbFiles()/
rebuildDb() take content_manager as an explicit parameter instead of an
implicit one -- the caller (whatever eventually drives a rebuild: a
FileWrite command handler, a "dbschema.json changed" hook, etc.) already
has both objects at hand.

createSparseFile()/writeRange() (added alongside the Bigfile scoping pass)
are the storage-side half of "Layer A" for range-addressed downloads:
plugins/Bigfile's original built this as plugin-only functionality, but
there's no plugin-specific logic in a sparse-file-plus-positional-write
primitive -- and the wire protocol's read side (protocols/getfile.py's
location/read_bytes params, Peer.getFile()'s pos_from/pos_to) already
supports arbitrary byte ranges from earlier phases, so this closes the
one real gap (the write/storage side) as core capability rather than a
plugin. Piece hashing, piecefields, peer-piecefield exchange, and
WorkerManager scheduling integration (the plan's own Layers B-D) are
still NOT done -- this is the one storage primitive they'd all build on,
not the rest of big-file support.

Also NOT wired up here, deliberately: write()/delete() don't auto-trigger
updateDbFile() the way the original's onUpdated() does on every file
write. Doing that would mean threading a content_manager reference into
every write() call (or storing one on SiteStorage itself, which would
break the "constructed before ContentManager exists" ordering in
Site.py) for a sync path nothing in this stack exercises yet -- no
FileWrite-equivalent command drives writes through here today. The
building blocks (updateDbFile(), rebuildDb()) are real and tested; wiring
them into the write path is separate follow-up work once there's an
actual caller. query()'s auto-rebuild-on-corrupt-db fallback (the
original's query() catches sqlite3.DatabaseError and retries after a
rebuildDb()) is dropped for the same content_manager-availability reason
-- query() here just raises, and it's the caller's job to rebuildDb()
explicitly if it wants to recover.
"""
import json
import os
import shutil
import sqlite3
from pathlib import Path

import trio

from .Db import Db
from .ThreadPool import ThreadPool


def _getDirname(path: str) -> str:
    if "/" in path:
        return path[:path.rfind("/") + 1].lstrip("/")
    return ""


class AccessError(Exception):
    pass


class SiteStorage:
    def __init__(self, directory: Path, allow_create: bool = True,
                 threads_read: int = 4, threads_write: int = 4):
        self.directory = directory
        self._pool_read = ThreadPool(threads_read)
        self._pool_write = ThreadPool(threads_write)
        self.db: Db | None = None
        self._db_lock = trio.Lock()

        if not self.directory.is_dir():
            if allow_create:
                self.directory.mkdir(parents=True)
            else:
                raise Exception("Directory not exists: %s" % self.directory)

    def getPath(self, inner_path) -> Path:
        """Security check and return path of site's file"""
        inner_path = str(inner_path).replace("\\", "/")  # Windows separator fix
        if not inner_path:
            return self.directory
        inner_path = Path(inner_path)
        if ".." in inner_path.parts:
            raise AccessError("Paths with '..' are not allowed: %s" % inner_path)
        if inner_path.is_absolute():
            inner_path = inner_path.relative_to(inner_path.anchor)
        if inner_path.is_absolute():  # ugh, just making sure there's nothing funky going on
            raise AccessError("Paths shouldn't be absolute: %s" % inner_path)
        return self.directory / inner_path

    def getInnerPath(self, path: Path) -> Path:
        """Get site dir relative path"""
        try:
            return path.relative_to(self.directory)
        except ValueError:
            raise AccessError("File path not allowed: %s" % path)

    def ensureDir(self, inner_path) -> bool:
        try:
            self.getPath(inner_path).mkdir(parents=True)
        except FileExistsError:
            return False
        return True

    def isFile(self, inner_path) -> bool:
        return self.getPath(inner_path).is_file()

    def isExists(self, inner_path) -> bool:
        return self.getPath(inner_path).exists()

    def isDir(self, inner_path) -> bool:
        return self.getPath(inner_path).is_dir()

    def getSize(self, inner_path) -> int:
        try:
            return self.getPath(inner_path).stat().st_size
        except OSError:
            return 0

    def open(self, inner_path, mode: str = "rb", create_dirs: bool = False, **kwargs):
        """Open file object (sync -- for streaming reads where an offloaded
        one-shot read()/write() doesn't fit)."""
        file_path = self.getPath(inner_path)
        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        return file_path.open(mode, **kwargs)

    async def read(self, inner_path, mode: str = "rb"):
        def _read():
            with self.getPath(inner_path).open(mode) as f:
                return f.read()
        return await self._pool_read.apply(_read)

    async def write(self, inner_path, content) -> None:
        def _write():
            file_path = self.getPath(inner_path)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(content, "read"):  # File-like object
                with file_path.open("wb") as f:
                    shutil.copyfileobj(content, f)
            else:
                with file_path.open("wb") as f:
                    f.write(content)
        await self._pool_write.apply(_write)

    def createSparseFile(self, inner_path, size: int) -> None:
        """Pre-allocates inner_path so writeRange() can seek+write into it
        before the whole file exists -- the storage primitive a
        piece-based downloader needs (pieces can arrive out of order,
        from different peers, each landing directly in its final
        position). Only pre-allocates up to 5MB, matching the original:
        writing at a not-yet-materialized offset beyond that still works
        because POSIX write() past EOF zero-fills the gap, so there's no
        need to actually reserve the full size up front."""
        file_path = self.getPath(inner_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("wb") as f:
            f.truncate(min(1024 * 1024 * 5, size))

    async def writeRange(self, inner_path, pos_from: int, content: bytes) -> None:
        """Write `content` at byte offset pos_from without touching the
        rest of the file. Creates the file first via createSparseFile()
        if it doesn't exist yet (with size=pos_from+len(content) as a
        fallback estimate) -- callers that know the real eventual size
        should call createSparseFile() themselves first instead."""
        def _write():
            file_path = self.getPath(inner_path)
            if not file_path.is_file():
                self.createSparseFile(inner_path, pos_from + len(content))
            with file_path.open("rb+") as f:
                f.seek(pos_from)
                f.write(content)
        await self._pool_write.apply(_write)

    def _piecefieldPath(self, file_hash: str):
        if not file_hash or "/" in file_hash or "\\" in file_hash:
            raise AccessError("Invalid piecefield key")
        return self.directory / ".p2p-piecefields" / (file_hash + ".json")

    async def loadPiecefield(self, file_hash: str, piece_count: int):
        """Load resumable Bigfile state, treating missing/corrupt state as empty."""
        from .Bigfile import Piecefield

        path = self._piecefieldPath(file_hash)
        try:
            raw = await self._pool_read.apply(path.read_text)
            return Piecefield.from_json(json.loads(raw))
        except (FileNotFoundError, OSError, ValueError, KeyError):
            return Piecefield(piece_count)

    async def savePiecefield(self, file_hash: str, piecefield) -> None:
        path = self._piecefieldPath(file_hash)

        def _save():
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".tmp")
            temp.write_text(json.dumps(piecefield.to_json(), sort_keys=True))
            os.replace(temp, path)

        await self._pool_write.apply(_save)

    async def deletePiecefield(self, file_hash: str) -> None:
        path = self._piecefieldPath(file_hash)
        try:
            await self._pool_write.apply(path.unlink)
        except FileNotFoundError:
            pass

    async def delete(self, inner_path) -> None:
        await self._pool_write.apply(lambda: self.getPath(inner_path).unlink())

    def deleteDir(self, inner_path) -> None:
        self.getPath(inner_path).rmdir()

    async def rename(self, inner_path_before, inner_path_after) -> None:
        def _rename():
            os.rename(self.getPath(inner_path_before), self.getPath(inner_path_after))
        await self._pool_write.apply(_rename)

    async def walk(self, dir_inner_path, ignore: str | None = None) -> list:
        """Returns a materialized list, not a generator like the original --
        the walk itself runs inside the offloaded thread, so it can't yield
        back into the trio task piecemeal."""
        import re
        from util import SafeRe

        def _walk():
            directory = self.getPath(dir_inner_path)
            found = []
            for root, dirs, files in os.walk(directory):
                root = root.replace("\\", "/")
                root_relative_path = re.sub("^%s" % re.escape(str(directory)), "", root).lstrip("/")
                for file_name in files:
                    file_relative_path = (root_relative_path + "/" + file_name) if root_relative_path else file_name
                    if ignore and SafeRe.match(ignore, file_relative_path):
                        continue
                    found.append(file_relative_path)

                if ignore:
                    dirs_filtered = []
                    for dir_name in dirs:
                        dir_relative_path = (root_relative_path + "/" + dir_name) if root_relative_path else dir_name
                        if ignore == ".*" or re.match(".*([|(]|^)%s([|)]|$)" % re.escape(dir_relative_path + "/.*"), ignore):
                            continue
                        dirs_filtered.append(dir_name)
                    dirs[:] = dirs_filtered
            return found

        return await self._pool_read.apply(_walk)

    async def readChunk(self, inner_path, location: int, max_bytes: int) -> tuple[bytes, int]:
        """Read up to max_bytes starting at location. Returns (chunk, file_size).
        Used by protocols/getfile.py for the location/read_bytes chunked-read
        pattern, kept here rather than in the protocol handler so the actual
        file descriptor work stays behind SiteStorage's security boundary
        (getPath()) and offloaded thread pool, same as every other read."""
        def _read_chunk():
            file_path = self.getPath(inner_path)
            with file_path.open("rb") as f:
                file_size = os.fstat(f.fileno()).st_size
                f.seek(location)
                send_size = max(0, min(max_bytes, file_size - location))
                return f.read(send_size), file_size

        return await self._pool_read.apply(_read_chunk)

    async def list(self, dir_inner_path) -> list:
        return await self._pool_read.apply(lambda: os.listdir(self.getPath(dir_inner_path)))

    async def loadJson(self, inner_path) -> dict:
        data = await self.read(inner_path, mode="r")
        return json.loads(data)

    async def writeJson(self, inner_path, data) -> None:
        await self.write(inner_path, json.dumps(data, indent=1, sort_keys=True).encode("utf8"))

    # -- DB (P2P.Db) --

    def hasDbSchema(self) -> bool:
        return self.isFile("dbschema.json")

    async def getDbSchema(self) -> dict:
        try:
            return await self.loadJson("dbschema.json")
        except Exception as err:
            raise Exception("dbschema.json is not a valid JSON: %s" % err)

    async def openDb(self) -> Db:
        schema = await self.getDbSchema()
        db_path = self.getPath(schema["db_file"])
        return Db(schema, db_path)

    async def closeDb(self, reason: str = "Unknown (SiteStorage)") -> None:
        if self.db:
            await self.db.close(reason)
        self.db = None

    async def loadDb(self) -> None:
        """Opens (creating if needed) a connectable DB with tables ready.
        Does NOT populate it from content_manager's data -- unlike the
        original's loadDb(), which calls rebuildDb() itself when the DB
        file is missing/empty, this has no content_manager reference to
        rebuild against (see module docstring). A caller that needs a
        freshly-populated DB should call rebuildDb(content_manager)
        explicitly; this just guarantees getDb() always returns something
        connectable with the schema's tables in place."""
        if not self.hasDbSchema():
            return

        if self.db:
            await self.db.close("Getting new db for SiteStorage")
        self.db = await self.openDb()
        try:
            await self.db.checkTables()
        except sqlite3.OperationalError:
            pass

    async def getDb(self) -> Db | None:
        async with self._db_lock:
            if not self.hasDbSchema():
                return None
            if not self.db:
                await self.loadDb()
            return self.db

    async def updateDbFile(self, inner_path, content: bytes | None = None) -> bool:
        db = await self.getDb()
        if db is None:
            return False
        return await db.updateJson(self.getPath(inner_path), content)

    def getDbFiles(self, content_manager) -> list:
        """Every file content_manager currently knows about that's a JSON
        (or JSON-ish, .json/.json.gz) file eligible for DB indexing --
        the content.json files themselves plus every JSON file they list.
        Takes content_manager explicitly -- see module docstring."""
        found = []
        for content_inner_path, content in content_manager.contents.items():
            if self.isFile(content_inner_path):
                found.append((content_inner_path, self.getPath(content_inner_path)))

            content_dir = _getDirname(content_inner_path)
            file_names = list(content.get("files", {}).keys()) + list(content.get("files_optional", {}).keys())
            for file_relative_path in file_names:
                if not (file_relative_path.endswith(".json") or file_relative_path.endswith(".json.gz")):
                    continue
                file_inner_path = (content_dir + file_relative_path).strip("/")
                if self.isFile(file_inner_path):
                    found.append((file_inner_path, self.getPath(file_inner_path)))
        return found

    async def rebuildDb(self, content_manager, delete_db: bool = True, reason: str = "Unknown") -> bool:
        if not self.hasDbSchema():
            return False

        schema = await self.getDbSchema()
        db_path = self.getPath(schema["db_file"])
        if delete_db and db_path.is_file():
            if self.db:
                await self.closeDb("rebuilding")
            try:
                db_path.unlink()
            except Exception:
                pass

        if not self.db:
            self.db = await self.openDb()
        await self.db.checkTables()

        num_imported = 0
        for file_inner_path, _file_path in self.getDbFiles(content_manager):
            try:
                content_bytes = await self.read(file_inner_path)
                if await self.updateDbFile(file_inner_path, content_bytes):
                    num_imported += 1
            except Exception:
                pass

        await self.db.commit("Rebuilt (reason: %s, imported: %s)" % (reason, num_imported))
        return True

    async def query(self, query: str, params=None) -> "sqlite3.Cursor":
        if not query.strip().upper().startswith("SELECT"):
            raise ValueError("Only SELECT query supported")
        db = await self.getDb()
        if db is None:
            raise Exception("Site has no database (no dbschema.json)")
        return await db.execute(query, params)
