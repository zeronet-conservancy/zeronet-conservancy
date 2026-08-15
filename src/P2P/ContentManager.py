"""Trio port of Content/ContentManager.py -- deliberately narrow scope.

ContentManager doesn't split as cleanly as SiteStorage did: its core
verification logic (content.json signing chains, cert verification,
getValidSigners/verifyContent/verifyCert/sign) is one tightly-coupled,
security-critical unit of ~800 lines. Rushing a port of *that* risks a
real vulnerability (a subtly wrong signature check is worse than no
check, because it looks safe) -- it deserves its own dedicated,
carefully-reviewed pass, not a slice of a session already covering four
other files. VerifyError is raised with a clear "not implemented" message
for the content.json-signing path rather than silently treating any
content.json as valid.

What's ported here: content.json *loading* (parsing only, not the
original's 246-line loadContent() with its recursive-includes/bad-file-
tracking/user-content-scanning logic -- another deliberate simplification)
and getFileInfo()/verifyFile()'s regular-file path (sha512+size check),
which is what's actually needed to validate a downloaded file against
already-trusted content.json data.

self.contents is a plain dict here, not the original's ContentDbDict
(a SQLite-backed structure wrapping Db.py, itself not fully ported --
see Phase 3's DbBackground.py). A plain dict satisfies the same
.get()/[] interface getFileInfo() needs; the DB-backed caching layer is a
separate, later concern, not a correctness requirement for this logic.
"""
import json

from Crypt import CryptHash
from util import helper


class VerifyError(Exception):
    pass


class ContentManager:
    def __init__(self, storage):
        self.storage = storage
        self.contents: dict = {}  # content_inner_path -> parsed content.json dict

    async def loadContent(self, content_inner_path: str = "content.json") -> dict:
        """Parse and cache one content.json. Not the original's recursive
        includes/bad-file-tracking/user-content-scanning -- just loading."""
        content = await self.storage.loadJson(content_inner_path)
        self.contents[content_inner_path] = content
        return content

    def getFileInfo(self, inner_path: str, new_file: bool = False):
        """Look up a file's entry (from "files" or "files_optional") in
        whichever loaded content.json actually covers it. Ported
        essentially unchanged -- pure logic over self.contents."""
        dirs = inner_path.split("/")
        inner_path_parts = []
        while dirs:
            inner_path_parts.insert(0, dirs.pop())
            content_inner_path = ("/".join(dirs) + "/content.json").strip("/")
            content = self.contents.get(content_inner_path)

            if content and "files" in content:
                back = content["files"].get("/".join(inner_path_parts))
                if back:
                    back = dict(back)
                    back["content_inner_path"] = content_inner_path
                    back["optional"] = False
                    back["relative_path"] = "/".join(inner_path_parts)
                    return back

            if content and "files_optional" in content:
                back = content["files_optional"].get("/".join(inner_path_parts))
                if back:
                    back = dict(back)
                    back["content_inner_path"] = content_inner_path
                    back["optional"] = True
                    back["relative_path"] = "/".join(inner_path_parts)
                    return back

            if new_file and content:
                return {
                    "content_inner_path": content_inner_path,
                    "relative_path": "/".join(inner_path_parts),
                    "optional": None,
                }

        return False

    def verifyFile(self, inner_path: str, file, ignore_same: bool = True) -> bool:
        """Regular-file path only: sha512 + size check against the loaded
        content.json's file entry. content.json itself (the signature/cert
        trust chain) is NOT handled here -- see the module docstring."""
        if inner_path.endswith("content.json"):
            raise NotImplementedError(
                "content.json signature verification is not ported yet -- "
                "see P2P/ContentManager.py's module docstring. Do not treat "
                "an unsigned content.json as valid; this is a hard stop, not a skip."
            )

        file_info = self.getFileInfo(inner_path)
        if not file_info:
            raise VerifyError("File not in content.json")

        if CryptHash.sha512sum(file) != file_info.get("sha512", ""):
            raise VerifyError("Invalid hash")

        if file_info.get("size", 0) != file.tell():
            raise VerifyError(
                "File size does not match %s <> %s" % (file.tell(), file_info.get("size", 0))
            )

        return True

    def listModified(self, after=None, before=None) -> dict:
        """inner_path -> modified time, for every loaded content.json,
        matching the original's listModified()."""
        back = {}
        for content_inner_path, content in self.contents.items():
            modified = content.get("modified")
            if modified is None:
                continue
            if after is not None and modified <= after:
                continue
            if before is not None and modified >= before:
                continue
            back[content_inner_path] = modified
        return back
