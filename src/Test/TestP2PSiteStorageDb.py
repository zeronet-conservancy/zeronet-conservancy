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

    def testWriteAutoIndexesJsonIntoDb(self):
        """write()'s own real caller (WorkerManager.syncSite(), fileWrite,
        protocols/update.py) never calls updateDbFile() itself -- this is
        the fix that makes indexing happen automatically, matching the
        original's own onUpdated()."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)  # dbschema.json only
                await storage.write("data.json", json.dumps({"title": "auto-indexed"}).encode())
                res = await storage.query("SELECT * FROM keyvalue WHERE key = 'title'")
                return res.fetchone()

        row = compat.run(scenario)
        assert row["value"] == "auto-indexed"

    def testWriteWithoutSchemaDoesNothing(self):
        """No dbschema.json at all -- the common case for most sites --
        stays a fast no-op, no db ever opened."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await storage.write("data.json", json.dumps({"title": "no db here"}).encode())
                return storage.db

        assert compat.run(scenario) is None

    def testDeleteClearsIndexedRow(self):
        """Db.updateJson(file_bytes=None) clears the keyvalue row's own
        VALUE to null (matching Db.py's real update-in-place semantics,
        not a DELETE) -- confirming _onUpdated() reaches updateDbFile()
        with content_bytes=None on delete, same as the original passing
        file=False through onUpdated()."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)
                await storage.write("data.json", json.dumps({"title": "will be deleted"}).encode())
                await storage.delete("data.json")
                res = await storage.query("SELECT * FROM keyvalue WHERE key = 'title'")
                return res.fetchone()

        row = compat.run(scenario)
        assert row["value"] is None

    def testWritingDbschemaReopensLiveDb(self):
        """Writing a NEW dbschema.json (a different db_file) while a Db is
        already open closes the stale one -- the next getDb() call re-reads
        the new schema instead of continuing to serve the old db_file,
        matching the original's own onUpdated() dbschema.json special case."""
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                storage = SiteStorage(pathlib.Path(d))
                await _writeSchemaAndData(storage)
                db1 = await storage.getDb()

                new_schema = dict(DB_SCHEMA)
                new_schema["db_file"] = "site2.db"
                await storage.writeJson("dbschema.json", new_schema)

                assert storage.db is None  # Closed as a side effect of the dbschema.json write
                db2 = await storage.getDb()
                return db1.db_path, db2.db_path

        db1_path, db2_path = compat.run(scenario)
        assert db1_path != db2_path
        assert db2_path.name == "site2.db"
