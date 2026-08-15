"""Per-site sidecar for optional-file bookkeeping (pin state, first-seen
download time, a size limit) -- see commands.py's own module docstring
for why this isn't the original's schema-driven `file_optional` SQL
table. Lives at the site's own storage root as a dotfile
(.optional_files.json), same "out-of-band file living inside the site
directory but not part of synced content" precedent as content.db
itself, rather than in P2P.SiteManager's data_dir (this is genuinely
per-site data, unlike P2P.plugins.ContentFilter's storage which is
process-wide).
"""
import json
import time
from pathlib import Path


class OptionalFilesStorage:
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_content: dict = {"files": {}, "limit": None}
        self.load()

    def load(self) -> None:
        if self.file_path.is_file():
            try:
                self.file_content = json.loads(self.file_path.read_text(encoding="utf8"))
            except (OSError, ValueError):
                self.file_content = {"files": {}, "limit": None}
        self.file_content.setdefault("files", {})
        self.file_content.setdefault("limit", None)

    def save(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(json.dumps(self.file_content, indent=1), encoding="utf8")

    def getEntry(self, inner_path: str) -> dict:
        return self.file_content["files"].get(inner_path, {})

    def markDownloaded(self, inner_path: str, size: int) -> None:
        entry = self.file_content["files"].setdefault(inner_path, {})
        entry["size"] = size
        entry.setdefault("time_downloaded", time.time())
        self.save()

    def setPinned(self, inner_path: str, is_pinned: bool) -> None:
        entry = self.file_content["files"].setdefault(inner_path, {})
        entry["is_pinned"] = is_pinned
        self.save()

    def forget(self, inner_path: str) -> None:
        self.file_content["files"].pop(inner_path, None)
        self.save()

    def getLimit(self):
        return self.file_content["limit"]

    def setLimit(self, limit) -> None:
        self.file_content["limit"] = limit
        self.save()
