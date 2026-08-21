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

    def testCreateSparseFilePreallocatesUpToFiveMbCap(self):
        with tempfile.TemporaryDirectory() as d:
            storage = SiteStorage(pathlib.Path(d))
            storage.createSparseFile("small.bin", 1024)
            assert storage.getSize("small.bin") == 1024

            storage.createSparseFile("big.bin", 20 * 1024 * 1024)
            assert storage.getSize("big.bin") == 5 * 1024 * 1024  # Capped, not the full 20MB

    def testWriteRangeWritesAtOffsetWithoutDisturbingRestOfFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                storage.createSparseFile("piece.bin", 30)
                await storage.writeRange("piece.bin", 10, b"0123456789")
                await storage.writeRange("piece.bin", 0, b"HELLO")
                return await storage.read("piece.bin")

        data = compat.run(scenario)
        assert data[:5] == b"HELLO"
        assert data[10:20] == b"0123456789"
        assert len(data) == 30

    def testWriteRangeOutOfOrderPiecesLandCorrectly(self):
        """The actual piece-download shape: pieces arrive in arbitrary
        order (different peers, different completion times) and each
        must land in its own final position regardless of what's
        arrived so far."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                storage.createSparseFile("multi.bin", 15)
                await storage.writeRange("multi.bin", 10, b"CCCCC")
                await storage.writeRange("multi.bin", 0, b"AAAAA")
                await storage.writeRange("multi.bin", 5, b"BBBBB")
                return await storage.read("multi.bin")

        assert compat.run(scenario) == b"AAAAABBBBBCCCCC"

    def testWriteRangeCreatesFileWhenNotPreallocated(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.writeRange("nopreallocate.bin", 4, b"tail")
                return await storage.read("nopreallocate.bin")

        data = compat.run(scenario)
        assert data == b"\x00\x00\x00\x00tail"
