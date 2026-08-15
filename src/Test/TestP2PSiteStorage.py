import pathlib
import tempfile

import pytest

from P2P.SiteStorage import SiteStorage, AccessError
from P2P import compat


class TestP2PSiteStorage:
    def testGetPathRejectsTraversal(self):
        with tempfile.TemporaryDirectory() as d:
            storage = SiteStorage(pathlib.Path(d))
            assert storage.getPath("data.json") == pathlib.Path(d) / "data.json"
            with pytest.raises(AccessError):
                storage.getPath("../../etc/passwd")
            # A leading "/" is treated as site-root-relative, not
            # filesystem-root -- matches the original's behavior of
            # stripping the anchor rather than rejecting it outright.
            assert storage.getPath("/etc/passwd") == pathlib.Path(d) / "etc/passwd"

    def testGetInnerPath(self):
        with tempfile.TemporaryDirectory() as d:
            storage = SiteStorage(pathlib.Path(d))
            full = storage.getPath("sub/data.json")
            assert storage.getInnerPath(full) == pathlib.Path("sub/data.json")
            with pytest.raises(AccessError):
                storage.getInnerPath(pathlib.Path("/somewhere/else"))

    def testWriteThenReadRoundTrip(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("data.json", b'{"hello": "world"}')
                return await storage.read("data.json")

        assert compat.run(scenario) == b'{"hello": "world"}'

    def testWriteCreatesParentDirs(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("deep/nested/file.txt", b"content")
                return storage.isFile("deep/nested/file.txt")

        assert compat.run(scenario) is True

    def testWriteFromFileLikeObject(self):
        import io

        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("streamed.bin", io.BytesIO(b"streamed content"))
                return await storage.read("streamed.bin")

        assert compat.run(scenario) == b"streamed content"

    def testLoadWriteJson(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.writeJson("content.json", {"b": 2, "a": 1})
                return await storage.loadJson("content.json")

        assert compat.run(scenario) == {"a": 1, "b": 2}

    def testDeleteRemovesFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("temp.txt", b"x")
                assert storage.isFile("temp.txt")
                await storage.delete("temp.txt")
                return storage.isFile("temp.txt")

        assert compat.run(scenario) is False

    def testRename(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("old.txt", b"content")
                await storage.rename("old.txt", "new.txt")
                return storage.isFile("old.txt"), storage.isFile("new.txt")

        old_exists, new_exists = compat.run(scenario)
        assert old_exists is False
        assert new_exists is True

    def testWalkFindsNestedFilesAndRespectsIgnore(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("a.txt", b"1")
                await storage.write("sub/b.txt", b"2")
                await storage.write("sub/skip.tmp", b"3")
                return await storage.walk("", ignore=r".*\.tmp")

        found = compat.run(scenario)
        assert sorted(found) == ["a.txt", "sub/b.txt"]

    def testListReturnsTopLevelEntries(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("a.txt", b"1")
                await storage.write("sub/b.txt", b"2")
                return sorted(await storage.list(""))

        assert compat.run(scenario) == ["a.txt", "sub"]

    def testGetSizeAndIsDir(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("data.json", b"12345")
                return storage.getSize("data.json"), storage.getSize("missing.json"), storage.isDir("")

        size, missing_size, is_dir = compat.run(scenario)
        assert size == 5
        assert missing_size == 0
        assert is_dir is True

    def testOpenForStreamingRead(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("stream.txt", b"streamed")
                with storage.open("stream.txt", "rb") as f:
                    return f.read()

        assert compat.run(scenario) == b"streamed"

    def testDirectoryCreatedOnInitIfMissing(self):
        with tempfile.TemporaryDirectory() as d:
            target = pathlib.Path(d) / "newsite"
            assert not target.exists()
            SiteStorage(target)
            assert target.is_dir()

    def testDirectoryNotCreatedRaisesWithoutAllowCreate(self):
        with tempfile.TemporaryDirectory() as d:
            target = pathlib.Path(d) / "missing"
            with pytest.raises(Exception):
                SiteStorage(target, allow_create=False)
