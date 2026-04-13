import shutil
import os

import pytest
from Site import SiteManager

TEST_DATA_PATH = "src/Test/testdata"

@pytest.mark.usefixtures("resetSettings")
class TestSite:
    def testClone(self, site):
        assert str(site.storage.directory) == TEST_DATA_PATH + "/epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8"

        # Remove old files
        if os.path.isdir(TEST_DATA_PATH + "/epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9"):
            shutil.rmtree(TEST_DATA_PATH + "/epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9")
        assert not os.path.isfile(TEST_DATA_PATH + "/epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9/content.json")

        # Clone epix18w3j2ftdj5078sw4qhxudp5wxxj3zc5k72vsl8 to epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9
        new_site = site.clone(
            "epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9", "5JU2p5h3R7B1WrbaEdEDNZR7YHqRLGcjNcqwqVQzX2H4SuNe2ee", address_index=1
        )

        # Check if clone was successful
        assert new_site.address == "epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9"
        assert new_site.storage.isFile("content.json")
        assert new_site.storage.isFile("index.html")
        assert new_site.storage.isFile("data/users/content.json")
        assert new_site.storage.isFile("data/zeroblog.db")
        assert new_site.storage.verifyFiles()["bad_files"] == []  # No bad files allowed
        assert new_site.storage.query("SELECT * FROM keyvalue WHERE key = 'title'").fetchone()["value"] == "MyZeroBlog"

        # Optional files should be removed

        assert len(new_site.storage.loadJson("content.json").get("files_optional", {})) == 0

        # Test re-cloning (updating)

        # Changes in non-data files should be overwritten
        new_site.storage.write("index.html", b"this will be overwritten")
        assert new_site.storage.read("index.html") == b"this will be overwritten"

        # Changes in data file should be kept after re-cloning
        changed_contentjson = new_site.storage.loadJson("content.json")
        changed_contentjson["description"] = "Update Description Test"
        new_site.storage.writeJson("content.json", changed_contentjson)

        changed_data = new_site.storage.loadJson("data/data.json")
        changed_data["title"] = "UpdateTest"
        new_site.storage.writeJson("data/data.json", changed_data)

        # The update should be reflected to database
        assert new_site.storage.query("SELECT * FROM keyvalue WHERE key = 'title'").fetchone()["value"] == "UpdateTest"

        # Re-clone the site
        site.log.debug("Re-cloning")
        site.clone("epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9")

        assert new_site.storage.loadJson("data/data.json")["title"] == "UpdateTest"
        assert new_site.storage.loadJson("content.json")["description"] == "Update Description Test"
        assert new_site.storage.read("index.html") != "this will be overwritten"

        # Delete created files
        new_site.storage.deleteFiles()
        assert not os.path.isdir(TEST_DATA_PATH + "/epix1t9gw466rzahpn6tuftg78gt8v62n9z0n3uakk9")

        # Delete from site registry
        assert new_site.address in SiteManager.site_manager.sites
        SiteManager.site_manager.delete(new_site.address)
        assert new_site.address not in SiteManager.site_manager.sites
