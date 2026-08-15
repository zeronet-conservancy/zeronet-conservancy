import io
import pathlib
import tempfile

import pytest

from Crypt import CryptHash
from P2P.SiteStorage import SiteStorage
from P2P.ContentManager import ContentManager, VerifyError
from P2P import compat


class TestP2PContentManager:
    def testLoadContentParsesAndCaches(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.writeJson("content.json", {"modified": 123, "files": {}})
                cm = ContentManager(storage)
                loaded = await cm.loadContent()
                return loaded, cm.contents

        loaded, contents = compat.run(scenario)
        assert loaded == {"modified": 123, "files": {}}
        assert contents["content.json"] == {"modified": 123, "files": {}}

    def testGetFileInfoFindsRegularFile(self):
        cm = ContentManager(storage=None)
        cm.contents["content.json"] = {
            "files": {"data.json": {"sha512": "abc", "size": 10}},
        }
        info = cm.getFileInfo("data.json")
        assert info["sha512"] == "abc"
        assert info["optional"] is False
        assert info["content_inner_path"] == "content.json"

    def testGetFileInfoFindsOptionalFile(self):
        cm = ContentManager(storage=None)
        cm.contents["content.json"] = {
            "files_optional": {"big.bin": {"sha512": "def", "size": 999}},
        }
        info = cm.getFileInfo("big.bin")
        assert info["optional"] is True

    def testGetFileInfoNestedContentJson(self):
        cm = ContentManager(storage=None)
        cm.contents["users/content.json"] = {
            "files": {"data.json": {"sha512": "xyz", "size": 5}},
        }
        info = cm.getFileInfo("users/data.json")
        assert info["content_inner_path"] == "users/content.json"
        assert info["relative_path"] == "data.json"

    def testGetFileInfoNotFound(self):
        cm = ContentManager(storage=None)
        cm.contents["content.json"] = {"files": {}}
        assert cm.getFileInfo("missing.json") is False

    def testVerifyFileValidHashAndSize(self):
        cm = ContentManager(storage=None)
        content = b"hello world"
        cm.contents["content.json"] = {
            "files": {"data.txt": {"sha512": CryptHash.sha512sum(io.BytesIO(content)), "size": len(content)}},
        }
        # sha512sum() reads from the current position to EOF, and verifyFile
        # checks file.tell() *after* that read for the size -- so the file
        # object passed in starts at 0, not pre-seeked to the end.
        assert cm.verifyFile("data.txt", io.BytesIO(content)) is True

    def testVerifyFileWrongHashRaises(self):
        cm = ContentManager(storage=None)
        content = b"hello world"
        cm.contents["content.json"] = {
            "files": {"data.txt": {"sha512": "0" * 128, "size": len(content)}},
        }
        with pytest.raises(VerifyError, match="Invalid hash"):
            cm.verifyFile("data.txt", io.BytesIO(content))

    def testVerifyFileNotInContentJsonRaises(self):
        cm = ContentManager(storage=None)
        cm.contents["content.json"] = {"files": {}}
        with pytest.raises(VerifyError, match="not in content.json"):
            cm.verifyFile("nope.txt", io.BytesIO(b"x"))

    def testVerifyFileContentJsonItselfIsNotImplemented(self):
        cm = ContentManager(storage=None)
        with pytest.raises(NotImplementedError):
            cm.verifyFile("content.json", io.BytesIO(b"{}"))

    def testListModifiedFiltersAfterAndBefore(self):
        cm = ContentManager(storage=None)
        cm.contents = {
            "a/content.json": {"modified": 100},
            "b/content.json": {"modified": 200},
            "c/content.json": {"modified": 300},
        }
        assert cm.listModified(after=100) == {"b/content.json": 200, "c/content.json": 300}
        assert cm.listModified(before=300) == {"a/content.json": 100, "b/content.json": 200}
        assert cm.listModified(after=100, before=300) == {"b/content.json": 200}
