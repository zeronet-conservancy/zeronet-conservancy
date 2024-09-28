import os

from Db.Db import Db, DbTableError
from Config import config
from Plugin import PluginManager
from Debug import Debug


@PluginManager.acceptPlugins
class ContentDb(Db):
    def __init__(self, path):
        Db.__init__(self, {"db_name": "ContentDb", "tables": {}}, path)
        self.foreign_keys = True

    def init(self):
        try:
            self.schema = self.getSchema()
            try:
                self.checkTables()
            except DbTableError:
                pass
            self.log.debug("Checking foreign keys...")
            foreign_key_error = self.execute("PRAGMA foreign_key_check").fetchone()
            if foreign_key_error:
                raise Exception("Database foreign key error: %s" % foreign_key_error)
        except Exception as err:
            self.log.error("Error loading content.db: %s, rebuilding..." % Debug.formatException(err))
            self.close()
            os.unlink(self.db_path)  # Remove and try again
            Db.__init__(self, {"db_name": "ContentDb", "tables": {}}, self.db_path)
            self.foreign_keys = True
            self.schema = self.getSchema()
            try:
                self.checkTables()
            except DbTableError:
                pass
        self.site_ids = {}
        self.sites = {}

    def getSchema(self):
        schema = {}
        schema["db_name"] = "ContentDb"
        schema["version"] = 3
        schema["tables"] = {}

        if not self.getTableVersion("site"):
            self.log.debug("Migrating from table version-less content.db")
            version = int(self.execute("PRAGMA user_version").fetchone()[0])
            if version > 0:
                self.checkTables()
                self.execute("INSERT INTO keyvalue ?", {"json_id": 0, "key": "table.site.version", "value": 1})
                self.execute("INSERT INTO keyvalue ?", {"json_id": 0, "key": "table.content.version", "value": 1})

        schema["tables"]["site"] = {
            "cols": [
                ["site_id", "INTEGER PRIMARY KEY ASC NOT NULL UNIQUE"],
                ["address", "TEXT NOT NULL"],
            ],
            "indexes": [
                "CREATE UNIQUE INDEX site_address ON site (address)"
            ],
            "schema_changed": 1,
        }

        schema["tables"]["content"] = {
            "cols": [
                ["content_id", "INTEGER PRIMARY KEY UNIQUE NOT NULL"],
                ["site_id", "INTEGER REFERENCES site (site_id) ON DELETE CASCADE"],
                ["inner_path", "TEXT"],
                ["size", "INTEGER"],
                ["size_files", "INTEGER"],
                ["size_files_optional", "INTEGER"],
                ["modified", "INTEGER"],
                ["owner_id", "INTEGER REFERENCES site (site_id)"], # should be the same as site_id if not user content
            ],
            "indexes": [
                "CREATE UNIQUE INDEX content_key ON content (site_id, inner_path)",
                "CREATE INDEX content_modified ON content (site_id, modified)"
            ],
            "schema_changed": 2,
        }

        return schema

    def initSite(self, site):
        self.sites[site.address] = site

    def needSite(self, address):
        if address not in self.site_ids:
            params = {
                'address': address,
            }
            self.execute("INSERT INTO site ? ON CONFLICT(address) DO NOTHING", params)
            for row in self.execute('SELECT * FROM site WHERE ?', {'address': address}):
                self.site_ids[row["address"]] = row["site_id"]
            res = self.execute('SELECT site_id FROM site WHERE ?', params)
            self.site_ids[address] = res.fetchone()[0]
        return self.site_ids[address]

    def deleteSite(self, site):
        site_id = self.site_ids.get(site.address, 0)
        if site_id:
            self.execute("DELETE FROM site WHERE site_id = :site_id", {"site_id": site_id})
            del self.site_ids[site.address]
            del self.sites[site.address]

    def setContent(self, site, inner_path, content, size):
        """Record content.json data of a site into DB"""
        try:
            signs = content.get('signs').items()
        except Exception as exc:
            self.log.warning('Exception while setting content (see debug log for the content)')
            self.log.debug(content)
            raise(exc)
        if len(signs) < 1:
            # TODO: check what/how we should report
            raise RuntimeError('Content not signed')
        if len(signs) > 1:
            raise RuntimeError("Multi-sig not supported (and probably shouldn't on this level)")
        owner = list(signs)[0][0]
        owner_id = self.site_ids.get(owner, None)
        if owner_id is None:
            owner_id = self.needSite(owner)
        self.insertOrUpdate("content", {
            "size": size,
            "size_files": sum([val["size"] for key, val in content.get("files", {}).items()]),
            "size_files_optional": sum([val["size"] for key, val in content.get("files_optional", {}).items()]),
            "modified": int(content.get("modified", 0)),
            "owner_id": owner_id,
        }, {
            "site_id": self.site_ids.get(site.address, 0),
            "inner_path": inner_path,
        })

    def deleteContent(self, site, inner_path):
        self.execute("DELETE FROM content WHERE ?", {"site_id": self.site_ids.get(site.address, 0), "inner_path": inner_path})

    def loadDbDict(self, site):
        res = self.execute(
            "SELECT GROUP_CONCAT(inner_path, '|') AS inner_paths FROM content WHERE ?",
            {"site_id": self.site_ids.get(site.address, 0)}
        )
        row = res.fetchone()
        if row and row["inner_paths"]:
            inner_paths = row["inner_paths"].split("|")
            return dict.fromkeys(inner_paths, False)
        else:
            return {}

    def getTotalSize(self, site, ignore=None):
        params = {"site_id": self.site_ids.get(site.address, 0)}
        if ignore:
            params["not__inner_path"] = ignore
        res = self.execute("SELECT SUM(size) + SUM(size_files) AS size, SUM(size_files_optional) AS size_optional FROM content WHERE ?", params)
        row = dict(res.fetchone())

        if not row["size"]:
            row["size"] = 0
        if not row["size_optional"]:
            row["size_optional"] = 0

        return row["size"], row["size_optional"]

    def getAllSigners(self):
        """Returns all known public public and whether they have related site and user profile"""
        query = '''SELECT
  s.site_id,
  s.address,
  (c.content_count > 0) AS has_content_record,
  (exists (SELECT 1 FROM content c1 WHERE c1.site_id = s.site_id AND c1.inner_path = 'profile/content.json')) AS has_profile_content
FROM site s
LEFT JOIN (
  SELECT
    site_id,
    COUNT(*) AS content_count
  FROM content
  GROUP BY site_id
        ) c ON s.site_id = c.site_id'''
        res = self.execute(query)
        return [dict(x) for x in res.fetchall()]

    def getTotalSignedSize(self, address):
        """Get total size of files signed by address"""
        params = {
            'owner_id': self.site_ids.get(address, 0),
        }
        res = self.execute('SELECT SUM(size_files) FROM content WHERE ?', params)
        return res.fetchone()[0]

    def listModified(self, site, after=None, before=None):
        params = {"site_id": self.site_ids.get(site.address, 0)}
        if after:
            params["modified>"] = after
        if before:
            params["modified<"] = before
        res = self.execute("SELECT inner_path, modified FROM content WHERE ?", params)
        return {row["inner_path"]: row["modified"] for row in res}

content_dbs = {}


def getContentDb(path=None):
    if not path:
        path = config.start_dir / 'content.db'
    if path not in content_dbs:
        content_dbs[path] = ContentDb(path)
        content_dbs[path].init()
    return content_dbs[path]

getContentDb()  # Pre-connect to default one
