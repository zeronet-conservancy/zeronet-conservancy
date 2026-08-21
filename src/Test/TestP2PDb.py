import json
import pathlib
import tempfile

from P2P.Db import Db, parseQuery
from P2P import compat


SCHEMA = {
    "db_name": "TestDb",
    "version": 3,
    "maps": {
        ".*/data\\.json$": {
            "to_keyvalue": ["title"],
            "to_table": [
                {"table": "post", "node": "posts", "key_col": "post_id"},
            ],
        }
    },
    "tables": {
        "post": {
            "cols": [
                ["post_id", "INTEGER"],
                ["json_id", "INTEGER"],
                ["body", "TEXT"],
            ],
            "schema_changed": 1,
        }
    },
}


class TestP2PDbParseQuery:
    def testDictParamsExpandToWhereClause(self):
        query, params = parseQuery("SELECT * FROM site WHERE ?", {"address": "1Test", "size>": 100})
        assert "address = ?" in query
        assert "size > ?" in query
        assert params == ["1Test", 100]

    def testDictParamsExpandToInsertValues(self):
        query, params = parseQuery("INSERT INTO site ?", {"address": "1Test", "size": 100})
        assert query == "INSERT INTO site (address, size) VALUES (?, ?)"
        assert params == ("1Test", 100)

    def testListValueExpandsToInClause(self):
        query, params = parseQuery("SELECT * FROM site WHERE ?", {"address": ["1A", "1B"]})
        assert "address IN (?,?)" in query
        assert params == ["1A", "1B"]

    def testNotPrefixExpandsToNotEqual(self):
        query, params = parseQuery("SELECT * FROM site WHERE ?", {"not__address": "1Test"})
        assert "address != ?" in query
        assert params == ["1Test"]


class TestP2PDb:
    def testCheckTablesCreatesKeyvalueAndJsonAndSchemaTables(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db = Db(SCHEMA, pathlib.Path(d) / "test.db")
                changed = await db.checkTables()
                return changed

        changed = compat.run(scenario)
        assert set(changed) == {"keyvalue", "json", "post"}

    def testCheckTablesIsIdempotentOnSecondCall(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db = Db(SCHEMA, pathlib.Path(d) / "test.db")
                await db.checkTables()
                return await db.checkTables()

        assert compat.run(scenario) == []

    def testExecuteWithDictParamsInsertsRow(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db = Db(SCHEMA, pathlib.Path(d) / "test.db")
                await db.checkTables()
                await db.execute("INSERT INTO post ?", {"post_id": 1, "json_id": 0, "body": "hello"})
                res = await db.execute("SELECT * FROM post WHERE ?", {"post_id": 1})
                return dict(res.fetchone())

        row = compat.run(scenario)
        assert row["body"] == "hello"

    def testInsertOrUpdateInsertsThenUpdates(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db = Db(SCHEMA, pathlib.Path(d) / "test.db")
                await db.checkTables()
                await db.insertOrUpdate("post", {"body": "first"}, {"post_id": 5, "json_id": 0})
                await db.insertOrUpdate("post", {"body": "updated"}, {"post_id": 5, "json_id": 0})
                res = await db.execute("SELECT * FROM post WHERE ?", {"post_id": 5})
                rows = res.fetchall()
                return [dict(r) for r in rows]

        rows = compat.run(scenario)
        assert len(rows) == 1
        assert rows[0]["body"] == "updated"

    def testUpdateJsonSyncsKeyvalueAndTableRows(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db_dir = pathlib.Path(d)
                db = Db(SCHEMA, db_dir / "test.db")
                await db.checkTables()

                data = {
                    "title": "My Blog",
                    "posts": {
                        "1": {"post_id": 1, "body": "hello world"},
                        "2": {"post_id": 2, "body": "second post"},
                    },
                }
                file_bytes = json.dumps(data).encode("utf8")
                applied = await db.updateJson(db_dir / "1MergedSite" / "data" / "data.json", file_bytes)

                keyvalue_res = await db.execute("SELECT * FROM keyvalue WHERE key = ?", ("title",))
                keyvalue_row = keyvalue_res.fetchone()

                posts_res = await db.execute("SELECT * FROM post ORDER BY post_id")
                posts = [dict(r) for r in posts_res.fetchall()]
                return applied, keyvalue_row["value"], posts

        applied, title_value, posts = compat.run(scenario)
        assert applied is True
        assert title_value == "My Blog"
        assert len(posts) == 2
        assert posts[0]["body"] == "hello world"
        assert posts[1]["body"] == "second post"

    def testUpdateJsonWithDeletedFileClearsTableRows(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db_dir = pathlib.Path(d)
                db = Db(SCHEMA, db_dir / "test.db")
                await db.checkTables()

                data = {"title": "X", "posts": {"1": {"post_id": 1, "body": "hi"}}}
                await db.updateJson(db_dir / "1MergedSite" / "data" / "data.json", json.dumps(data).encode("utf8"))

                await db.updateJson(db_dir / "1MergedSite" / "data" / "data.json", None)  # File deleted

                posts_res = await db.execute("SELECT * FROM post")
                return posts_res.fetchall()

        assert compat.run(scenario) == []

    def testUpdateJsonIgnoresFileOutsideDbDir(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db_dir = pathlib.Path(d) / "site"
                db_dir.mkdir()
                db = Db(SCHEMA, db_dir / "test.db")
                await db.checkTables()
                outside_path = pathlib.Path(d) / "data.json"
                return await db.updateJson(outside_path, b"{}")

        assert compat.run(scenario) is False

    def testCommitAndCloseWithoutConnectionIsSafeNoop(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db = Db(SCHEMA, pathlib.Path(d) / "unused.db")
                commit_result = await db.commit()
                close_result = await db.close()
                return commit_result, close_result

        commit_result, close_result = compat.run(scenario)
        assert commit_result is False
        assert close_result is False

    def testCloseThenReopenReconnects(self):
        async def scenario():
            with tempfile.TemporaryDirectory() as d:
                db = Db(SCHEMA, pathlib.Path(d) / "test.db")
                await db.checkTables()
                await db.execute("INSERT INTO post ?", {"post_id": 9, "json_id": 0, "body": "persisted"})
                await db.commit()
                await db.close()

                res = await db.execute("SELECT * FROM post WHERE ?", {"post_id": 9})
                return dict(res.fetchone())

        row = compat.run(scenario)
        assert row["body"] == "persisted"
