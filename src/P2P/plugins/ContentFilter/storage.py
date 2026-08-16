"""Trio-native stand-in for plugins/ContentFilter's storage.

Deliberate simplifications vs. the original: no address-hashing
("ignore_block hashed address") matching trick for privacy-preserving
shared blocklists -- plain address string matching only. Synchronous
file I/O (json.load/dump), matching this stack's other simple JSON-
backed plugin storage (e.g. P2P.SiteManager's own sites.json handling)
rather than the original's SafeRe/threaded-save machinery.
"""
import json
import time
from pathlib import Path


class ContentFilterStorage:
    def __init__(self, data_dir: Path, filename: str = "content_filters.json"):
        self.file_path = data_dir / filename
        self.file_content: dict = {"mutes": {}, "siteblocks": {}}
        self.load()

    def load(self) -> None:
        if self.file_path.is_file():
            try:
                self.file_content = json.loads(self.file_path.read_text(encoding="utf8"))
            except (OSError, ValueError):
                self.file_content = {"mutes": {}, "siteblocks": {}}
        self.file_content.setdefault("mutes", {})
        self.file_content.setdefault("siteblocks", {})

    def save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(self.file_content, indent=1), encoding="utf8")

    def isSiteblocked(self, address: str) -> bool:
        return address in self.file_content["siteblocks"]

    def getSiteblockDetails(self, address: str) -> dict | None:
        return self.file_content["siteblocks"].get(address)

    def siteblockAdd(self, address: str, reason: str | None = None) -> None:
        self.file_content["siteblocks"][address] = {"date_added": time.time(), "reason": reason}
        self.save()

    def siteblockRemove(self, address: str) -> None:
        self.file_content["siteblocks"].pop(address, None)
        self.save()

    def isMuted(self, auth_address: str) -> bool:
        return auth_address in self.file_content["mutes"]

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
