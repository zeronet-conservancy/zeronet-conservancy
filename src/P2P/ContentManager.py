"""Trio port of Content/ContentManager.py -- deliberately narrow scope.

ContentManager doesn't split as cleanly as SiteStorage did. Its full
verification logic covers two cases:

  1. The ROOT content.json, signed directly by the site's own address.
     This is what every site has and what most sites only ever use.
  2. Non-root content.json (subdirectory "includes", ZeroNet's
     multi-user/forum feature), verified through a separate cert-signer
     chain (getUserContentRules/verifyCert/getRules) -- a genuinely
     different, more complex trust model layered on top of case 1.

This file ports case 1 in full (signature verification, replay/rollback
protection, structural checks) since it's the actual security boundary
every site depends on. Case 2 is NOT ported -- getValidSigners()/
_verifySignature() explicitly raise NotImplementedError for any inner_path
other than "content.json" rather than silently skipping or approving it.
That cert-signer system is a separate, large undertaking deserving its
own dedicated pass; a rushed port of a trust-chain feature is worse than
leaving it unimplemented, because a subtly wrong check looks safe.

self.contents is a plain dict here, not the original's ContentDbDict (a
SQLite-backed structure wrapping Db.py, itself not fully ported -- see
Phase 3's DbBackground.py). Same .get()/[] interface getFileInfo() needs;
DB-backed caching is a separate, later concern. Likewise getTotalSize()
here recomputes from self.contents rather than tracking an incremental
running total on a settings dict that doesn't exist in this scoped model.
"""
import json
import re
import time

from Crypt import CryptBitcoin, CryptHash


class VerifyError(Exception):
    pass


class ContentManager:
    def __init__(self, storage, site_address: str):
        self.storage = storage
        self.site_address = site_address
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

    def isValidRelativePath(self, relative_path) -> bool:
        """Ported verbatim -- pure string validation."""
        relative_path = str(relative_path)
        if ".." in relative_path.replace("\\", "/").split("/"):
            return False
        elif len(relative_path) > 255:
            return False
        elif not relative_path:
            return False
        elif relative_path[0] in ("/", "\\"):
            return False
        elif relative_path[-1] in (".", " "):
            return False
        elif re.match(r".*(^|/)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]|CONOUT\$|CONIN\$)(\.|/|$)", relative_path, re.IGNORECASE):
            return False
        else:
            return bool(re.match(r"^[^\x00-\x1F\"*:<>?\\|]+$", relative_path))

    def getTotalSize(self) -> int:
        """Sum of all known (non-negative-size) file sizes across every
        loaded content.json. Computed fresh rather than tracked
        incrementally -- see module docstring."""
        total = 0
        for content in self.contents.values():
            for file_info in content.get("files", {}).values():
                if file_info.get("size", 0) >= 0:
                    total += file_info["size"]
        return total

    def getValidSigners(self, inner_path: str) -> list:
        """Root content.json only. Non-root paths need the cert-signer
        chain (getUserContentRules/getRules), not ported -- see module
        docstring."""
        if inner_path != "content.json":
            raise NotImplementedError(
                "Non-root content.json signer resolution (includes/user content, "
                "the cert-signer chain) is not ported -- see P2P/ContentManager.py's "
                "module docstring."
            )
        valid_signers = []
        root_content = self.contents.get("content.json")
        if root_content and "signers" in root_content:
            valid_signers += root_content["signers"][:]
        if self.site_address not in valid_signers:
            valid_signers.append(self.site_address)
        return valid_signers

    def getSignsRequired(self, inner_path: str) -> int:
        return 1  # No multisig support yet (matches the original's own "Todo: Multisig")

    def verifyContentJson(self, content: dict, size_limit_bytes: int | None = None) -> bool:
        """Verify a ROOT content.json: signature, replay/rollback
        protection, and basic structural rules. Raises VerifyError (bad
        content) or NotImplementedError (asked to verify something outside
        this file's scope -- see module docstring) rather than ever
        silently approving something unchecked.
        """
        inner_path = "content.json"

        if content.get("address") and content["address"] != self.site_address:
            raise VerifyError("Wrong site address: %s != %s" % (content["address"], self.site_address))
        if content.get("inner_path") and content["inner_path"] != inner_path:
            raise VerifyError("Wrong inner_path: %s" % content["inner_path"])

        old_content = self.contents.get(inner_path)
        if old_content:
            if old_content.get("modified") == content.get("modified"):
                return False  # Same content.json we already have -- not an error, just nothing to do
            if old_content.get("modified", 0) > content.get("modified", 0):
                raise VerifyError(
                    "We have newer (Our: %s, Sent: %s)" % (old_content["modified"], content.get("modified"))
                )
        if content.get("modified", 0) > time.time() + 60 * 60 * 24:  # allow 1 day+ clock drift
            raise VerifyError("Modify timestamp is in the far future!")

        for file_relative_path in list(content.get("files", {}).keys()) + list(content.get("files_optional", {}).keys()):
            if not self.isValidRelativePath(file_relative_path):
                raise VerifyError("Invalid relative path: %s" % file_relative_path)

        content_size_file = len(json.dumps(content, indent=1))
        if size_limit_bytes is not None and content_size_file > size_limit_bytes:
            raise VerifyError("Content too large %s B > %s B" % (content_size_file, size_limit_bytes))

        self._verifySignature(inner_path, content)
        return True

    def _verifySignature(self, inner_path: str, content: dict) -> bool:
        if inner_path != "content.json":
            raise NotImplementedError(
                "Non-root content.json verification (cert-signer chain) is not "
                "ported -- see P2P/ContentManager.py's module docstring."
            )

        new_content = dict(content)
        old_sign = new_content.pop("sign", None)
        signs = new_content.pop("signs", None)
        sign_content = json.dumps(new_content, sort_keys=True)

        if not signs:
            if old_sign:
                raise VerifyError("Invalid old-style sign")
            raise VerifyError("Not signed")

        valid_signers = self.getValidSigners(inner_path)
        signs_required = self.getSignsRequired(inner_path)

        # If the signer list itself was extended beyond the bare site
        # address, the extended list has to be authorized by the site
        # address too -- otherwise a malicious peer could just widen
        # "signers" and add their own key to it.
        if len(valid_signers) > 1:
            if "signers_sign" not in content:
                raise VerifyError("Missing signers_sign")
            signers_data = "%s:%s" % (signs_required, ",".join(valid_signers))
            if not CryptBitcoin.verify(signers_data, self.site_address, content["signers_sign"]):
                raise VerifyError("Invalid signers_sign!")

        valid_signs = 0
        for address in valid_signers:
            if address in signs:
                valid_signs += CryptBitcoin.verify(sign_content, address, signs[address])
            if valid_signs >= signs_required:
                break
        if valid_signs < signs_required:
            raise VerifyError("Valid signs: %s/%s" % (valid_signs, signs_required))
        return True

    def verifyFile(self, inner_path: str, file, ignore_same: bool = True) -> bool:
        """Regular-file path: sha512 + size check against the loaded
        content.json's file entry. content.json itself goes through
        verifyContentJson() instead (different shape: takes a parsed dict,
        not a file object, and the caller needs the True/False/raise
        distinction verifyContentJson() gives for "unchanged" vs "invalid")."""
        if inner_path.endswith("content.json"):
            raise NotImplementedError(
                "Use verifyContentJson() for content.json, not verifyFile() -- "
                "see P2P/ContentManager.py's module docstring."
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
