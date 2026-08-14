import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from Config import config
from Db import Db
from Site import SiteManager
from Site.Site import Site


class TestSiteBuilder:
    address = "1TeSTvb4w2PWE81S2rEELgmX2GCCExQGT"
    privatekey = "5KUh3PvNm5HUWoCfSUfcYvfQ2g3PrRNJWr6Q9eqdBGu23mtMntv"  # For 1TeSTvb4w2PWE81S2rEELgmX2GCCExQGT

    @staticmethod
    def _template_dir():
        return Path(__file__).resolve().parent.parent.parent / "plugins/UiSiteBuilder/media/template"

    @staticmethod
    def _seed_site_dir(data_dir):
        site_dir = Path(data_dir) / TestSiteBuilder.address
        shutil.copytree(TestSiteBuilder._template_dir(), site_dir)
        # sign() picks up ignore/optional/title from an existing content.json
        shutil.copy(site_dir / "content.json-default", site_dir / "content.json")
        return site_dir

    def test_template_signs_and_queries(self):
        data_dir = tempfile.mkdtemp(prefix="sitebuilder-test-")
        try:
            # Minimal private-dir files that UserManager/SiteManager expect
            (Path(data_dir) / "users.json").write_text(json.dumps({}))
            (Path(data_dir) / "sites.json").write_text(json.dumps({}))
            (Path(data_dir) / "filters.json").write_text(json.dumps({}))

            self._seed_site_dir(data_dir)

            with mock.patch("Config.config.data_dir", Path(data_dir)), \
                    mock.patch("Config.config.private_dir", Path(data_dir)):
                # SiteManager.load() also initializes plugin singletons (e.g. ContentFilter)
                SiteManager.site_manager.load()
                site = Site(self.address)
                site.content_manager.sign("content.json", privatekey=self.privatekey)

                # Mirrors Site.clone(): the sql cache must be rebuilt after signing,
                # otherwise it is built from the pre-sign content (empty) during sign's
                # onUpdated("content.json") hook.
                site.storage.rebuildDb()

                content = site.content_manager.contents["content.json"]
                files = content["files"]

                # Static files + data are hashed into the manifest
                for required in [
                    "index.html", "js/all.js", "js/ZeroFrame.js", "css/all.css",
                    "dbschema.json", "builder/editor.html", "builder/editor.js",
                    "data/settings.json", "data/pages/1.json",
                    "data-default/settings.json", "data-default/pages/1.json",
                    "content.json-default",
                    "js/lib/editorjs.umd.js", "js/lib/header.umd.js", "js/lib/list.umd.js",
                    "js/lib/quote.umd.js", "js/lib/code.umd.js", "js/lib/image.umd.js",
                    "js/lib/delimiter.umd.js", "js/lib/marked.min.js",
                    "js/lib/highlight.min.js", "js/lib/highlight.css", "js/lib/undo.js",
                    "templates/templates.json", "templates/landing.json", "templates/faq.json"
                ]:
                    assert required in files, f"missing from content.json: {required}"

                # The sqlite cache is ignored, not hashed
                assert not any("sitebuilder.db" in f for f in files)

                # ignore/optional patterns preserved from the template
                assert "sitebuilder" in content["ignore"]
                assert "data/media" in content["optional"]

                # Signature is valid and all files pass sha512 verification
                assert site.content_manager.verifyFile(
                    "content.json", site.storage.open("content.json", "rb"), ignore_same=False
                ) is True
                assert site.storage.verifyFiles()["bad_files"] == []

                # dbschema.json loads and dbQuery returns the seeded page
                rows = list(site.storage.query("SELECT page_id, slug, title FROM page ORDER BY page_id"))
                assert len(rows) == 1
                assert rows[0]["slug"] == "home"
                assert rows[0]["title"] == "Home"

                # settings.json is mapped into keyvalue
                title_rows = list(site.storage.query("SELECT value FROM keyvalue WHERE key = 'title'"))
                assert [r["value"] for r in title_rows] == ["Site Builder Demo"]

                Db.dbCloseAll()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
            SiteManager.site_manager.sites.clear()

    def test_plugin_creates_site_and_favourites(self):
        import importlib
        from User import UserManager

        sbp = importlib.import_module("UiSiteBuilder.UiSiteBuilderPlugin")
        sbp._builder_address = None

        data_dir = tempfile.mkdtemp(prefix="sitebuilder-plugin-")
        try:
            (Path(data_dir) / "users.json").write_text(json.dumps({
                "15E5rhcAUD69WbiYsYARh4YHJ4sLm2JEyc": {
                    "certs": {},
                    "master_seed": "024bceac1105483d66585d8a60eaf20aa8c3254b0f266e0d626ddb6114e2949a",
                    "sites": {}
                }
            }))
            (Path(data_dir) / "sites.json").write_text(json.dumps({}))
            (Path(data_dir) / "filters.json").write_text(json.dumps({}))

            UserManager.user_manager.users = {}  # Force reload from our temp users.json

            with mock.patch("Config.config.data_dir", Path(data_dir)), \
                    mock.patch("Config.config.private_dir", Path(data_dir)):
                SiteManager.site_manager.load()

                address = sbp.ensure_builder_site()
                assert address

                site = SiteManager.site_manager.sites.get(address)
                assert site is not None
                assert site.settings["own"] is True
                content = site.content_manager.contents["content.json"]
                assert "data/pages/1.json" in content["files"]
                assert site.storage.query("SELECT slug FROM page").fetchone()["slug"] == "home"

                # Idempotent: second call returns the same site
                assert sbp.ensure_builder_site() == address

                # Favourited on the dashboard
                sbp.favourite_builder(address)
                users = json.loads((Path(data_dir) / "users.json").read_text())
                site_data = users["15E5rhcAUD69WbiYsYARh4YHJ4sLm2JEyc"]["sites"][config.homepage]
                assert site_data["settings"]["favorite_sites"].get(address) is True

                Db.dbCloseAll()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
            SiteManager.site_manager.sites.clear()

    def test_deleted_site_is_recreated(self):
        import importlib
        from User import UserManager

        sbp = importlib.import_module("UiSiteBuilder.UiSiteBuilderPlugin")
        sbp._builder_address = None

        data_dir = tempfile.mkdtemp(prefix="sitebuilder-del-")
        try:
            (Path(data_dir) / "users.json").write_text(json.dumps({
                "15E5rhcAUD69WbiYsYARh4YHJ4sLm2JEyc": {
                    "certs": {},
                    "master_seed": "024bceac1105483d66585d8a60eaf20aa8c3254b0f266e0d626ddb6114e2949a",
                    "sites": {}
                }
            }))
            (Path(data_dir) / "sites.json").write_text(json.dumps({}))
            (Path(data_dir) / "filters.json").write_text(json.dumps({}))

            UserManager.user_manager.users = {}

            with mock.patch("Config.config.data_dir", Path(data_dir)), \
                    mock.patch("Config.config.private_dir", Path(data_dir)):
                SiteManager.site_manager.sites = {}
                SiteManager.site_manager.loaded = False
                SiteManager.site_manager.load()

                address = sbp.ensure_builder_site()
                site = SiteManager.site_manager.sites.get(address)
                assert site is not None

                # Delete the site the same way the UI does
                site.delete()
                user = UserManager.user_manager.get()
                user.deleteSiteData(address)

                # Same session: the cached address must be re-validated so a
                # fresh site is created instead of returning the deleted one
                new_address = sbp.ensure_builder_site()
                assert new_address != address
                assert SiteManager.site_manager.sites.get(new_address).settings["own"] is True

                # Simulate a restart: only the on-disk state survives
                sbp._builder_address = None
                again = sbp.ensure_builder_site()
                assert again == new_address

                Db.dbCloseAll()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
            SiteManager.site_manager.sites.clear()

    def test_starters_and_create_from_starter(self):
        import importlib
        from User import UserManager

        sbp = importlib.import_module("UiSiteBuilder.UiSiteBuilderPlugin")
        sbp._builder_address = None

        data_dir = tempfile.mkdtemp(prefix="sitebuilder-starter-")
        try:
            (Path(data_dir) / "users.json").write_text(json.dumps({
                "15E5rhcAUD69WbiYsYARh4YHJ4sLm2JEyc": {
                    "certs": {},
                    "master_seed": "024bceac1105483d66585d8a60eaf20aa8c3254b0f266e0d626ddb6114e2949a",
                    "sites": {}
                }
            }))
            (Path(data_dir) / "sites.json").write_text(json.dumps({}))
            (Path(data_dir) / "filters.json").write_text(json.dumps({}))

            UserManager.user_manager.users = {}  # Force reload from our temp users.json

            with mock.patch("Config.config.data_dir", Path(data_dir)), \
                    mock.patch("Config.config.private_dir", Path(data_dir)):
                SiteManager.site_manager.load()

                starters = sbp.list_starters()
                ids = [s["id"] for s in starters]
                assert "blank" in ids
                assert "personal" in ids
                assert "business" in ids

                # Every starter must be valid JSON with pages/
                for starter in starters:
                    starter_dir = Path(sbp.starters_dir) / starter["id"]
                    assert (starter_dir / "settings.json").is_file()
                    assert (starter_dir / "pages").is_dir()

                address = sbp.create_builder_site(starter="personal", primary=False)
                assert address
                site = SiteManager.site_manager.sites.get(address)
                assert site is not None
                rows = list(site.storage.query("SELECT slug FROM page ORDER BY page_id"))
                assert [r["slug"] for r in rows] == ["home", "about", "contact"]

                # Owned flag is set and persisted synchronously to sites.json
                assert site.settings["own"] is True
                sites_json = json.loads((Path(data_dir) / "sites.json").read_text())
                assert sites_json[address]["own"] is True

                # Starter's title/description are applied to content.json
                content = site.content_manager.contents["content.json"]
                assert content["title"] == "Jane Doe"
                assert content["description"] == "Personal site"

                # The owner's privatekey is stored, so the dashboard reports the
                # site as owned (privatekey == True in siteList).
                user = UserManager.user_manager.get()
                assert user.getSiteData(address, create=False).get("privatekey")

                Db.dbCloseAll()
        finally:
            shutil.rmtree(data_dir, ignore_errors=True)
            SiteManager.site_manager.sites.clear()
