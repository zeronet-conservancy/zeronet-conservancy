"""The real dashboard site's own Charts page reads its historical stats
from a single node-wide chart.db, queried via chartDbQuery -- see
commands.py's own module docstring for scope (chartDbQuery only; not
ChartCollector, the periodic sampler that would actually populate it,
nor chartGetPeerLocations).

Built on P2P.Db.Db -- the same trio-native, schema-driven SQLite engine
every site's own db already uses (SiteStorage's own getDb()), not a
second hand-rolled connection-safety scheme -- so chart.db gets the same
"only one thread ever touches this connection" guarantee for free.
Schema copied verbatim from the original's own ChartDb.getSchema() (data/
type/site tables), minus the original's own archive()/loadSites()/
loadTypes()/getTypeId()/getSiteId() convenience methods -- those exist to
support ChartCollector's write path, which isn't ported here; nothing
currently writes to this db; see commands.py for why that's an honest
gap, not a stub.

One Db instance per resolved data_dir, not a bare module-level singleton
-- session.app.data_dir varies per test/instance (see _requireAdmin's own
sibling helpers for this same getattr(session.app, "data_dir", ...)
fallback pattern), so caching by path keeps concurrent test runs (or a
real multi-instance deployment) from sharing state that shouldn't be
shared.
"""
from pathlib import Path

from Config import config
from P2P.Db import Db

_SCHEMA = {
    "db_name": "Chart",
    "version": 2,
    "tables": {
        "data": {
            "cols": [
                ["data_id", "INTEGER PRIMARY KEY ASC AUTOINCREMENT NOT NULL UNIQUE"],
                ["type_id", "INTEGER NOT NULL"],
                ["site_id", "INTEGER"],
                ["value", "INTEGER"],
                ["date_added", "DATETIME DEFAULT (CURRENT_TIMESTAMP)"],
            ],
            "indexes": [
                "CREATE INDEX data_site_id ON data (site_id)",
                "CREATE INDEX data_date_added ON data (date_added)",
            ],
            "schema_changed": 2,
        },
        "type": {
            "cols": [["type_id", "INTEGER PRIMARY KEY NOT NULL UNIQUE"], ["name", "TEXT"]],
            "schema_changed": 1,
        },
        "site": {
            "cols": [["site_id", "INTEGER PRIMARY KEY NOT NULL UNIQUE"], ["address", "TEXT"]],
            "schema_changed": 1,
        },
    },
}

_dbs: dict[str, Db] = {}


async def getChartDb(session) -> Db:
    data_dir = Path(getattr(session.app, "data_dir", None) or config.data_dir).resolve()
    db_path = data_dir / "chart.db"
    key = str(db_path)
    db = _dbs.get(key)
    if db is None:
        db = Db(_SCHEMA, db_path)
        await db.checkTables()
        _dbs[key] = db
    return db
