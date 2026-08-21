import pathlib
import tarfile
import tempfile
import zipfile

from P2P.SiteStorage import SiteStorage
from P2P import compat


def _writeZip(storage: SiteStorage, inner_path: str, files: dict) -> None:
    """Writes an explicit directory entry for every parent dir a file
    implies, matching what real-world zip tools (and the original
    FilePack plugin's own real usage) actually produce -- Python's
    zipfile.writestr() alone does NOT synthesize one, so a namelist-only
    reader (this port, faithfully matching the original's own
    namelist()-based walk/list) would never see an empty or
    only-just-created directory without one."""
    zip_path = storage.getPath(inner_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as archive:
        written_dirs = set()
        for name, data in files.items():
            if "/" in name:
                dir_name = name.rsplit("/", 1)[0] + "/"
                if dir_name not in written_dirs:
                    archive.writestr(dir_name, b"")
                    written_dirs.add(dir_name)
            archive.writestr(name, data)


def _writeTarGz(storage: SiteStorage, inner_path: str, files: dict) -> None:
    import io
    tar_path = storage.getPath(inner_path)
    tar_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "w:gz") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


class TestP2PSiteStorageArchive:
    def testIsFileAndReadInsideZip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                _writeZip(storage, "data.zip", {"hello.txt": b"hello from zip", "sub/nested.txt": b"nested"})
                return (
                    storage.isFile("data.zip/hello.txt"),
                    storage.isFile("data.zip/missing.txt"),
                    storage.isFile("data.zip"),  # The archive file itself, not redirected
                    await storage.read("data.zip/hello.txt"),
                    await storage.read("data.zip/sub/nested.txt"),
                )

        has_hello, has_missing, has_archive_itself, hello_data, nested_data = compat.run(scenario)
        assert has_hello is True
        assert has_missing is False
        assert has_archive_itself is True
        assert hello_data == b"hello from zip"
        assert nested_data == b"nested"

    def testIsFileAndReadInsideTarGz(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                _writeTarGz(storage, "data.tar.gz", {"hello.txt": b"hello from tar"})
                return storage.isFile("data.tar.gz/hello.txt"), await storage.read("data.tar.gz/hello.txt")

        has_hello, hello_data = compat.run(scenario)
        assert has_hello is True
        assert hello_data == b"hello from tar"

    def testReadTextModeDecodesArchiveContent(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                _writeZip(storage, "data.zip", {"note.txt": "hello é".encode("utf8")})
                return await storage.read("data.zip/note.txt", mode="r")

        assert compat.run(scenario) == "hello é"

    def testListArchiveRootAndSubdir(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                _writeZip(storage, "data.zip", {
                    "a.txt": b"a", "b.txt": b"b", "sub/c.txt": b"c",
                })
                root_bare = await storage.list("data.zip")  # No trailing slash -- still lists the root
                root_slash = await storage.list("data.zip/")
                sub = await storage.list("data.zip/sub")
                return root_bare, root_slash, sub

        root_bare, root_slash, sub = compat.run(scenario)
        assert sorted(root_bare) == ["a.txt", "b.txt", "sub"]
        assert sorted(root_slash) == ["a.txt", "b.txt", "sub"]
        assert sub == ["c.txt"]

    def testWalkArchiveReturnsAllFilesRecursively(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                _writeZip(storage, "data.zip", {
                    "a.txt": b"a", "sub/b.txt": b"b", "sub/deeper/c.txt": b"c",
                })
                return await storage.walk("data.zip")

        found = compat.run(scenario)
        assert sorted(found) == ["a.txt", "sub/b.txt", "sub/deeper/c.txt"]

    def testHttpRawServingPathWorksTransparentlyThroughArchive(self):
        """No UiServer.py changes were needed for this -- _handleSite's raw
        (non-wrapper) branch already calls storage.isFile()/storage.read()
        directly, so making those archive-aware was the whole port."""
        async def scenario():
            with tempfile.TemporaryDirectory() as root:
                import pathlib as pl
                from P2P.Site import Site
                from P2P.Ui.UiServer import UiServer
                import httpx

                site = Site("1TestFilePackSiteAAAAAAAAAAA1", pl.Path(root))
                _writeZip(site.storage, "assets.zip", {"page.html": b"<b>packed</b>"})
                server = UiServer(sites={site.address: site})
                async with server.run():
                    base_url = server.bound_addresses[0]
                    async with httpx.AsyncClient() as client:
                        return await client.get(
                            "%s/%s/assets.zip/page.html?wrapper=0" % (base_url, site.address)
                        )

        response = compat.run(scenario)
        assert response.status_code == 200
        assert response.content == b"<b>packed</b>"
