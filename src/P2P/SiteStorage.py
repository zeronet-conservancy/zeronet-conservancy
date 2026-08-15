"""Trio port of Site/SiteStorage.py -- scoped to the pure file I/O layer
(getPath and friends, open/read/write/delete/rename/walk/list/loadJson/
writeJson). The DB-backed methods (getDb/rebuildDb/query, onUpdated's SQL
sync, verifyFiles, deleteFiles) all need ContentManager (contents dict,
hashfield, verifyFile) and Db, neither ported yet -- deferred, same
reasoning as the rest of Site.py.

Blocking disk I/O is offloaded to a P2P.ThreadPool (matching the
original's thread_pool_fs_read/thread_pool_fs_write wrapping) so it
doesn't stall the trio event loop.
"""
import json
import os
import shutil
from pathlib import Path

from .ThreadPool import ThreadPool


class AccessError(Exception):
    pass


class SiteStorage:
    def __init__(self, directory: Path, allow_create: bool = True,
                 threads_read: int = 4, threads_write: int = 4):
        self.directory = directory
        self._pool_read = ThreadPool(threads_read)
        self._pool_write = ThreadPool(threads_write)

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
