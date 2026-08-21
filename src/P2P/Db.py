"""Trio port of Db/Db.py + Db/DbCursor.py -- schema-driven SQLite storage
used to index a site's content.json/data.json files into queryable
tables (the "to_table"/"to_keyvalue"/"to_json_table" mappings a plugin's
db schema.json declares), the mechanism behind commands like ZeroTalk's
structured queries.

Collapses the original's Db+DbCursor split into one class. The original's
DbCursor existed to let many gevent greenlets share one sqlite3
connection safely -- weakref-tracked cursor sets, a progress handler that
yields the hub, a lock around every execute() call, and a five-attempt
"wait for pending cursors to finish" dance in close(). All of that
coordination exists to answer one question: "is it safe for two greenlets
to touch this connection at once?" Here the answer is enforced
structurally instead: every blocking sqlite3 call for one Db instance
runs through trio.to_thread.run_sync under a trio.CapacityLimiter(1)
dedicated to that instance, so only ever one thread touches the
connection, full stop -- no lock, no progress handler, no cursor
tracking needed.

Also NOT ported, and deliberately so (global background state the
original spawns at import time):
  - dbCleanup()/dbCommitCheck()/dbCloseAll()/opened_dbs -- module-level
    greenlets auto-spawned on import that walk every open Db process-wide.
    A caller that wants periodic idle-cleanup or interval-commits should
    schedule its own loop calling close()/commit() on the Db instances it
    owns, in its own nursery -- same reasoning as P2P.User's saveDelayed()
    scope cut (trio has no ambient background-spawn).
  - executeDelayed()/insertOrUpdateDelayed()/processDelayed() -- the
    debounced-write queue, same reason: needs a nursery to schedule the
    flush, which isn't available at arbitrary call sites. Call execute()/
    insertOrUpdate() directly instead.

updateJson() takes the file's already-read bytes (or None for "deleted")
instead of the original's file-object/None/False tri-state -- SiteStorage
reads here are async, so there's no synchronous file object to hand in;
callers read via `await storage.read(...)` first.

Not wired into P2P.SiteStorage/P2P.ContentManager yet -- both already
documented that DB-backed querying was deferred pending this module; the
actual getDb()/query()/rebuildDb() integration is separate follow-up work,
not done here.
"""
import json
import logging
import re
import sqlite3
import time
from pathlib import Path

import trio

from util import SafeRe


class DbTableError(Exception):
    def __init__(self, message, table):
        super().__init__(message)
        self.table = table


def _quoteValue(value) -> str:
    if isinstance(value, int):
        return str(value)
    return "'%s'" % str(value).replace("'", "''")


def parseQuery(query: str, params):
    """Pure string transformation, ported unchanged from
    DbCursor.parseQuery(): lets callers pass a dict of params against a
    bare "?" placeholder and have it expanded into a full WHERE/VALUES
    clause, or ":name"-style params with a list value expanded into an
    IN-list of named placeholders."""
    query_type = query.split(" ", 1)[0].upper()
    if isinstance(params, dict) and "?" in query:
        if query_type in ("SELECT", "DELETE", "UPDATE"):
            query_wheres = []
            values = []
            for key, value in params.items():
                if isinstance(value, list):
                    if key.startswith("not__"):
                        field = key.replace("not__", "")
                        operator = "NOT IN"
                    else:
                        field = key
                        operator = "IN"
                    if len(value) > 100:
                        query_values = ",".join(_quoteValue(v) for v in value)
                    else:
                        query_values = ",".join(["?"] * len(value))
                        values += value
                    query_wheres.append("%s %s (%s)" % (field, operator, query_values))
                else:
                    if key.startswith("not__"):
                        query_wheres.append(key.replace("not__", "") + " != ?")
                    elif key.endswith("__like"):
                        query_wheres.append(key.replace("__like", "") + " LIKE ?")
                    elif key.endswith(">"):
                        query_wheres.append(key.replace(">", "") + " > ?")
                    elif key.endswith("<"):
                        query_wheres.append(key.replace("<", "") + " < ?")
                    else:
                        query_wheres.append(key + " = ?")
                    values.append(value)
            wheres = " AND ".join(query_wheres) or "1"
            query = re.sub(r"(.*)[?]", r"\1 %s" % wheres, query)
            params = values
        else:
            keys = ", ".join(params.keys())
            values_ph = ", ".join(["?"] * len(params))
            query = re.sub(r"(.*)[?]", r"\1(%s) VALUES (%s)" % (keys, values_ph), query)
            params = tuple(params.values())
    elif isinstance(params, dict) and ":" in query:
        new_params = {}
        for key, value in params.items():
            if isinstance(value, list):
                for idx, val in enumerate(value):
                    new_params["%s__%s" % (key, idx)] = val
                new_names = [":%s__%s" % (key, idx) for idx in range(len(value))]
                query = re.sub(r":" + re.escape(key) + r"([)\s]|$)", "(%s)%s" % (", ".join(new_names), r"\1"), query)
            else:
                new_params[key] = value
        params = new_params
    return query, params


class Db:
    def __init__(self, schema: dict, db_path):
        self.db_path = Path(db_path)
        self.db_dir = self.db_path.parent
        self.schema = dict(schema)
        self.schema["version"] = self.schema.get("version", 1)
        self.conn: sqlite3.Connection | None = None
        self.log = logging.getLogger("P2P.Db:%s" % self.schema.get("db_name", self.db_path.name))
        self.collect_stats = False
        self.need_commit = False
        self.db_keyvalues: dict = {}
        self.query_stats: dict = {}
        self._limiter = trio.CapacityLimiter(1)  # Confines all sqlite3 calls to one worker thread

    async def _run(self, fn, *args):
        return await trio.to_thread.run_sync(fn, *args, limiter=self._limiter)

    async def connect(self) -> None:
        if self.conn:
            return

        def _connect():
            self.db_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.db_path), isolation_level="DEFERRED", check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            return conn

        self.conn = await self._run(_connect)
        self.log.debug("Connected to %s", self.db_path)

    async def execute(self, query: str, params=None) -> sqlite3.Cursor:
        await self.connect()
        query = query.strip()
        query, params = parseQuery(query, params)

        def _execute():
            s = time.time()
            cursor = self.conn.cursor()
            if query.upper().strip("; ") == "VACUUM":
                self.conn.commit()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor, time.time() - s

        cursor, taken = await self._run(_execute)

        if self.collect_stats:
            stats = self.query_stats.setdefault(query, {"call": 0, "time": 0.0})
            stats["call"] += 1
            stats["time"] += taken

        query_type = query.split(" ", 1)[0].upper()
        if query_type in ("UPDATE", "DELETE", "INSERT", "CREATE"):
            self.need_commit = True

        return cursor

    async def insertOrUpdate(self, table: str, query_sets: dict, query_wheres: dict, oninsert: dict | None = None) -> None:
        sql_sets = ["%s = :%s" % (key, key) for key in query_sets]
        sql_wheres = ["%s = :%s" % (key, key) for key in query_wheres]
        params = dict(query_sets)
        params.update(query_wheres)
        cursor = await self.execute(
            "UPDATE %s SET %s WHERE %s" % (table, ", ".join(sql_sets), " AND ".join(sql_wheres)), params
        )
        if cursor.rowcount == 0:
            params.update(oninsert or {})
            await self.execute("INSERT INTO %s ?" % table, params)

    async def createTable(self, table: str, cols: list) -> None:
        await self.execute("DROP TABLE IF EXISTS %s" % table)
        col_definitions = ["%s %s" % (name, coltype) for name, coltype in cols]
        await self.execute("CREATE TABLE %s (%s)" % (table, ",".join(col_definitions)))

    async def createIndexes(self, table: str, indexes: list) -> None:
        for index in indexes:
            if not index.strip().upper().startswith("CREATE"):
                self.log.error("Index command should start with CREATE: %s", index)
                continue
            await self.execute(index)

    async def getTableVersion(self, table_name: str):
        if not self.db_keyvalues:
            try:
                res = await self.execute("SELECT * FROM keyvalue WHERE json_id=0")
            except sqlite3.OperationalError as err:
                self.log.debug("Query table version error: %s", err)
                return False
            for row in res:
                self.db_keyvalues[row["key"]] = row["value"]
        return self.db_keyvalues.get("table.%s.version" % table_name, 0)

    async def needTable(self, table: str, cols: list, indexes: list | None = None, version: int = 1) -> bool:
        current_version = await self.getTableVersion(table)
        if int(current_version) < int(version):
            self.log.debug("Table %s outdated...version: %s need: %s, rebuilding...", table, current_version, version)
            await self.createTable(table, cols)
            if indexes:
                await self.createIndexes(table, indexes)
            await self.execute(
                "INSERT OR REPLACE INTO keyvalue ?",
                {"json_id": 0, "key": "table.%s.version" % table, "value": version},
            )
            return True
        return False

    async def checkTables(self) -> list:
        changed_tables = []

        if await self.needTable("keyvalue", [
            ["keyvalue_id", "INTEGER PRIMARY KEY AUTOINCREMENT"],
            ["key", "TEXT"],
            ["value", "INTEGER"],
            ["json_id", "INTEGER"],
        ], ["CREATE UNIQUE INDEX key_id ON keyvalue(json_id, key)"], version=self.schema["version"]):
            changed_tables.append("keyvalue")

        if "json" not in self.schema.get("tables", {}):
            version = self.schema["version"]
            json_changed = False
            if version == 1:
                json_changed = await self.needTable("json", [
                    ["json_id", "INTEGER PRIMARY KEY AUTOINCREMENT"],
                    ["path", "VARCHAR(255)"],
                ], ["CREATE UNIQUE INDEX path ON json(path)"], version=version)
            elif version == 2:
                json_changed = await self.needTable("json", [
                    ["json_id", "INTEGER PRIMARY KEY AUTOINCREMENT"],
                    ["directory", "VARCHAR(255)"],
                    ["file_name", "VARCHAR(255)"],
                ], ["CREATE UNIQUE INDEX path ON json(directory, file_name)"], version=version)
            elif version == 3:
                json_changed = await self.needTable("json", [
                    ["json_id", "INTEGER PRIMARY KEY AUTOINCREMENT"],
                    ["site", "VARCHAR(255)"],
                    ["directory", "VARCHAR(255)"],
                    ["file_name", "VARCHAR(255)"],
                ], ["CREATE UNIQUE INDEX path ON json(directory, site, file_name)"], version=version)
            if json_changed:
                changed_tables.append("json")

        for table_name, table_settings in self.schema.get("tables", {}).items():
            try:
                indexes = table_settings.get("indexes", [])
                version = table_settings.get("schema_changed", 0)
                if await self.needTable(table_name, table_settings["cols"], indexes, version=version):
                    changed_tables.append(table_name)
            except Exception as err:
                self.log.error("Error creating table %s: %s", table_name, err)
                raise DbTableError(err, table_name)

        if changed_tables:
            self.db_keyvalues = {}
        return changed_tables

    async def getJsonRow(self, file_path: str):
        directory, file_name = re.match(r"^(.*?)/*([^/]*)$", file_path).groups()
        version = self.schema["version"]
        if version == 1:
            key = {"path": file_path}
        elif version == 2:
            key = {"directory": directory, "file_name": file_name}
        elif version == 3:
            site_address, sub_directory = re.match(r"^([^/]*)/(.*)$", directory).groups()
            key = {"site": site_address, "directory": sub_directory, "file_name": file_name}
        else:
            raise Exception("Dbschema version %s not supported" % version)

        res = await self.execute("SELECT * FROM json WHERE ? LIMIT 1", key)
        row = res.fetchone()
        if not row:
            await self.execute("INSERT INTO json ?", key)
            res = await self.execute("SELECT * FROM json WHERE ? LIMIT 1", key)
            row = res.fetchone()
        return row

    async def updateJson(self, file_path, file_bytes: bytes | None = None) -> bool:
        file_path = Path(file_path)
        try:
            relative_path = file_path.relative_to(self.db_dir)
        except ValueError:
            return False  # Not from the db dir: skipping

        matched_maps = []
        for match, map_settings in self.schema.get("maps", {}).items():
            try:
                if SafeRe.match(match, str(relative_path)):
                    matched_maps.append(map_settings)
            except SafeRe.UnsafePatternError as err:
                self.log.error("%s", err)
        if not matched_maps:
            return False

        if file_bytes is None:
            data = {}
        else:
            try:
                data = json.loads(file_bytes.decode("utf8"))
            except Exception as err:
                self.log.debug("Json file %s load error: %s", file_path, err)
                data = {}

        json_row = None
        if not data or any("to_keyvalue" in m or "to_table" in m for m in matched_maps):
            json_row = await self.getJsonRow(str(relative_path))

        for dbmap in matched_maps:
            if dbmap.get("to_keyvalue"):
                res = await self.execute("SELECT * FROM keyvalue WHERE json_id = ?", (json_row["json_id"],))
                current_keyvalue = {}
                current_keyvalue_id = {}
                for row in res:
                    current_keyvalue[row["key"]] = row["value"]
                    current_keyvalue_id[row["key"]] = row["keyvalue_id"]

                for key in dbmap["to_keyvalue"]:
                    if key not in current_keyvalue:
                        await self.execute(
                            "INSERT INTO keyvalue ?", {"key": key, "value": data.get(key), "json_id": json_row["json_id"]}
                        )
                    elif data.get(key) != current_keyvalue[key]:
                        await self.execute(
                            "UPDATE keyvalue SET value = ? WHERE keyvalue_id = ?",
                            (data.get(key), current_keyvalue_id[key]),
                        )

            if dbmap.get("to_json_table"):
                directory, file_name = re.match(r"^(.*?)/*([^/]*)$", str(relative_path)).groups()
                data_json_row = dict(await self.getJsonRow(directory + "/" + dbmap.get("file_name", file_name)))
                changed = any(data.get(key) != data_json_row.get(key) for key in dbmap["to_json_table"])
                if changed:
                    data_json_row.update({key: val for key, val in data.items() if key in dbmap["to_json_table"]})
                    await self.execute("INSERT OR REPLACE INTO json ?", data_json_row)

            for table_settings in dbmap.get("to_table", []):
                if isinstance(table_settings, dict):
                    table_name = table_settings["table"]
                    node = table_settings.get("node", table_name)
                    key_col = table_settings.get("key_col")
                    val_col = table_settings.get("val_col")
                    import_cols = table_settings.get("import_cols")
                    replaces = table_settings.get("replaces")
                else:
                    table_name = table_settings
                    node = table_settings
                    key_col = val_col = import_cols = replaces = None

                if not import_cols:
                    import_cols = {item[0] for item in self.schema["tables"][table_name]["cols"]}

                await self.execute("DELETE FROM %s WHERE json_id = ?" % table_name, (json_row["json_id"],))

                if node not in data:
                    continue

                if key_col:
                    for key, val in data[node].items():
                        if val_col:
                            await self.execute(
                                "INSERT OR REPLACE INTO %s ?" % table_name,
                                {key_col: key, val_col: val, "json_id": json_row["json_id"]},
                            )
                        elif isinstance(val, dict):
                            row = val
                            if import_cols:
                                row = {k: row[k] for k in row if k in import_cols}
                            row[key_col] = key
                            if replaces:
                                for replace_key, replace in replaces.items():
                                    if replace_key in row:
                                        for replace_from, replace_to in replace.items():
                                            row[replace_key] = row[replace_key].replace(replace_from, replace_to)
                            row["json_id"] = json_row["json_id"]
                            await self.execute("INSERT OR REPLACE INTO %s ?" % table_name, row)
                        elif isinstance(val, list):
                            for row in val:
                                row[key_col] = key
                                row["json_id"] = json_row["json_id"]
                                await self.execute("INSERT OR REPLACE INTO %s ?" % table_name, row)
                else:
                    for row in data[node]:
                        row["json_id"] = json_row["json_id"]
                        if import_cols:
                            row = {k: row[k] for k in row if k in import_cols}
                        await self.execute("INSERT OR REPLACE INTO %s ?" % table_name, row)

        if not data and json_row is not None:
            self.log.debug("Cleanup json row for %s", file_path)
            await self.execute("DELETE FROM json WHERE json_id = %s" % json_row["json_id"])

        return True

    async def commit(self, reason: str = "Unknown") -> bool:
        if not self.conn:
            return False

        def _commit():
            self.conn.commit()

        try:
            s = time.time()
            await self._run(_commit)
            self.need_commit = False
            self.log.debug("Committed in %.3fs (reason: %s)", time.time() - s, reason)
            return True
        except Exception as err:
            self.log.error("Commit error: %s (reason: %s)", err, reason)
            return False

    async def close(self, reason: str = "Unknown") -> bool:
        if not self.conn:
            return False
        if self.need_commit:
            await self.commit("Closing: %s" % reason)

        conn = self.conn
        self.conn = None
        await self._run(conn.close)
        self.log.debug("%s closed (reason: %s)", self.db_path, reason)
        return True
