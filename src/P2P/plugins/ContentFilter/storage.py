"""Trio-native stand-in for plugins/ContentFilter's storage.

Deliberate simplifications vs. the original: no address-hashing
("ignore_block hashed address") matching trick for privacy-preserving
shared blocklists -- plain address string matching only. Synchronous
file I/O (json.load/dump), matching this stack's other simple JSON-
backed plugin storage (e.g. P2P.SiteManager's own sites.json handling)
rather than the original's SafeRe/threaded-save machinery.

Filter-includes (subscribing to another already-known site's own
mutes/siteblocks) are ported now too -- SiteManagerPlugin.py's own
earlier docstring deferred this because it "needs mutes to exist first,
since an include's whole point is importing someone else's mute list
too"; mutes now do exist (muteAdd/muteRemove/muteList), so that
prerequisite is satisfied. include_filters is the merged mutes/
siteblocks superset from every included site's own content -- isMuted()/
isSiteblocked() check it alongside this node's own local mutes/
siteblocks, which is also the WHOLE enforcement story: SiteManagerPlugin.
add()/SitePlugin.needFile()/SiteStoragePlugin.updateDbFile() already
call isMuted()/isSiteblocked() at every real enforcement point, so
extending those two methods here is enough -- no changes needed to any
of the three.

Reads an included site's own file via a synchronous Path.read_text(),
not the async SiteStorage.loadJson() -- matching this class's own
"synchronous file I/O" convention above, and only possible at all
because getPath() itself does no I/O (a pure path join). Only works for
a site this node already has locally (site_manager.sites.get(address)),
same "silently skip, log a warning" contract the original's own
includeUpdateAll() has for an include whose target site isn't loaded
yet -- no auto-download is triggered, faithfully matching the original,
which never triggered one either.

NOT ported: automatic re-merge when an included file changes on disk
(the original's SiteStoragePlugin.onUpdated() hook, watching for
"<address>/<inner_path>" == an active include) -- an included list only
refreshes now when includeAdd()/includeRemove() itself runs, not on a
live update to the file it points at. A real, live-refresh gap, but a
separate, smaller follow-up from the core add/remove/enforce feature
here, not blocking it.
"""
import json
import time
from pathlib import Path


class ContentFilterStorage:
    def __init__(self, data_dir: Path, filename: str = "content_filters.json", site_manager=None):
        self.file_path = data_dir / filename
        self.file_content: dict = {"mutes": {}, "siteblocks": {}, "includes": {}}
        self.site_manager = site_manager
        self.include_filters: dict = {"mutes": set(), "siteblocks": set()}
        self.load()
        self.includeUpdateAll()

    def load(self) -> None:
        if self.file_path.is_file():
            try:
                self.file_content = json.loads(self.file_path.read_text(encoding="utf8"))
            except (OSError, ValueError):
                self.file_content = {"mutes": {}, "siteblocks": {}, "includes": {}}
        self.file_content.setdefault("mutes", {})
        self.file_content.setdefault("siteblocks", {})
        self.file_content.setdefault("includes", {})

    def save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(self.file_content, indent=1), encoding="utf8")

    def isSiteblocked(self, address: str) -> bool:
        return address in self.file_content["siteblocks"] or address in self.include_filters["siteblocks"]

    def getSiteblockDetails(self, address: str) -> dict | None:
        return self.file_content["siteblocks"].get(address)

    def siteblockAdd(self, address: str, reason: str | None = None) -> None:
        self.file_content["siteblocks"][address] = {"date_added": time.time(), "reason": reason}
        self.save()

    def siteblockRemove(self, address: str) -> None:
        self.file_content["siteblocks"].pop(address, None)
        self.save()

    def isMuted(self, auth_address: str) -> bool:
        return auth_address in self.file_content["mutes"] or auth_address in self.include_filters["mutes"]

    def muteAdd(self, auth_address: str, cert_user_id: str | None = None,
                reason: str | None = None) -> None:
        self.file_content["mutes"][auth_address] = {
            "cert_user_id": cert_user_id,
            "reason": reason,
            "date_added": time.time(),
        }
        self.save()

    def muteRemove(self, auth_address: str) -> None:
        self.file_content["mutes"].pop(auth_address, None)
        self.save()

    def includeAdd(self, address: str, inner_path: str, description: str | None = None) -> None:
        key = "%s/%s" % (address, inner_path)
        self.file_content["includes"][key] = {
            "date_added": time.time(), "address": address, "description": description, "inner_path": inner_path,
        }
        self.includeUpdateAll()
        self.save()

    def includeRemove(self, address: str, inner_path: str) -> bool:
        key = "%s/%s" % (address, inner_path)
        if key not in self.file_content["includes"]:
            return False
        del self.file_content["includes"][key]
        self.includeUpdateAll()
        self.save()
        return True

    def includeUpdateAll(self) -> None:
        new_filters: dict = {"mutes": set(), "siteblocks": set()}
        if self.site_manager is not None:
            for include in self.file_content["includes"].values():
                site = self.site_manager.sites.get(include["address"])
                if site is None:
                    continue  # Included site not locally known -- same silent-skip contract as the original
                try:
                    content = json.loads(site.storage.getPath(include["inner_path"]).read_text(encoding="utf8"))
                except (OSError, ValueError):
                    continue
                for key in ("mutes", "siteblocks"):
                    value = content.get(key)
                    if isinstance(value, dict):
                        new_filters[key].update(value.keys())
        self.include_filters = new_filters
