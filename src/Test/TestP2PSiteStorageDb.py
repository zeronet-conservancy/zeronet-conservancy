import json
import pathlib
import tempfile

from P2P.SiteStorage import SiteStorage
from P2P.ContentManager import ContentManager
from P2P import compat


DB_SCHEMA = {
    "db_name": "TestSite",
    "db_file": "%SITE_DATA%/site.db",
    "version": 1,  # Plain single-site schema -- version 3's site/subdir split is merger-sites only
    "maps": {
        "(.*/)?data\\.json$": {
            "to_keyvalue": ["title"],
        }
    },
}


async def _writeSchemaAndData(storage, extra_data_files=()):
    schema = dict(DB_SCHEMA)
    schema["db_file"] = "site.db"
    await storage.writeJson("dbschema.json", schema)
    for inner_path, data in extra_data_files:
        await storage.writeJson(inner_path, data)
    return schema


class TestP2PSiteStorageDb:
    def testHasDbSchemaFalseWithoutFile(self):
        with tempfile.TemporaryDirectory() as d:
            storage = SiteStorage(pathlib.Path(d))
            assert storage.hasDbSchema() is False

    def testGetDbNoneWithoutSchema(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                return await storage.getDb()

        assert compat.run(scenario) is None

    def testOpenDbUsesSchemaDbFile(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)
                db = await storage.openDb()
                return db.db_path, storage.getPath("site.db")

        db_path, expected = compat.run(scenario)
        assert db_path == expected

    def testLoadDbCreatesConnectableDbWithTables(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)
                db = await storage.getDb()
                # checkTables() itself writes table.*.version bookkeeping
                # rows into keyvalue -- confirm no *application* data yet
                # (no "title" key), not that the table is literally empty.
                res = await db.execute("SELECT * FROM keyvalue WHERE key = 'title'")
                return db is not None, res.fetchall()

        got_db, rows = compat.run(scenario)
        assert got_db is True
        assert rows == []

    def testGetDbFilesFindsContentJsonAndDataFiles(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, "1Test")
                await storage.write("content.json", b'{"files": {"data.json": {}}}')
                await storage.write("data.json", b'{"title": "hi"}')
                cm.contents["content.json"] = {"files": {"data.json": {}}}
                return storage.getDbFiles(cm)

        files = compat.run(scenario)
        found_paths = {inner_path for inner_path, _ in files}
        assert found_paths == {"content.json", "data.json"}

    def testGetDbFilesSkipsMissingFiles(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, "1Test")
                # content.json exists, but the file it lists doesn't
                await storage.write("content.json", b'{"files": {"missing.json": {}}}')
                cm.contents["content.json"] = {"files": {"missing.json": {}}}
                return storage.getDbFiles(cm)

        files = compat.run(scenario)
        found_paths = {inner_path for inner_path, _ in files}
        assert found_paths == {"content.json"}

    def testRebuildDbImportsDataIntoKeyvalue(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)
                cm = ContentManager(storage, "1Test")
                await storage.write("content.json", b'{"files": {"data.json": {}}}')
                await storage.write("data.json", json.dumps({"title": "hello db"}).encode())
                cm.contents["content.json"] = {"files": {"data.json": {}}}

                applied = await storage.rebuildDb(cm, reason="test")
                res = await storage.query("SELECT * FROM keyvalue WHERE key = 'title'")
                return applied, res.fetchone()

        applied, row = compat.run(scenario)
        assert applied is True
        assert row["value"] == "hello db"

    def testRebuildDbFalseWithoutSchema(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                cm = ContentManager(storage, "1Test")
                return await storage.rebuildDb(cm)

        assert compat.run(scenario) is False

    def testQueryRejectsNonSelect(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)
                await storage.getDb()
                try:
                    await storage.query("DELETE FROM keyvalue")
                    return "no-error"
                except ValueError:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testQueryWithoutSchemaRaises(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                try:
                    await storage.query("SELECT * FROM keyvalue")
                    return "no-error"
                except Exception:
                    return "raised"

        assert compat.run(scenario) == "raised"

    def testCloseDbThenGetDbReconnects(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)
                db1 = await storage.getDb()
                await storage.closeDb("test")
                db2 = await storage.getDb()
                return db1 is not db2, storage.db is db2

        different_instance, matches_stored = compat.run(scenario)
        assert different_instance is True
        assert matches_stored is True

    def testUpdateDbFileWithoutSchemaReturnsFalse(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                return await storage.updateDbFile("data.json", b"{}")

        assert compat.run(scenario) is False
