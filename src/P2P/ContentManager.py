"""Trio port of Content/ContentManager.py.

ContentManager's full verification logic covers two cases:

  1. The ROOT content.json, signed directly by the site's own address.
     This is what every site has and what most sites only ever use.
  2. Non-root content.json (subdirectory "includes", ZeroNet's
     multi-user/forum feature), verified through a separate cert-signer
     chain (getUserContentRules/verifyCert/getRules) -- a genuinely
     different, more complex trust model layered on top of case 1.

Both are ported now, but case 2 carries real, deliberate scope cuts rather
than a blind translation of a security-critical trust chain:

  - getUserContentRules() requires the caller to already have the parsed
    content dict in hand (content=None raises ValueError) instead of the
    original's fallback of reading it from storage itself. That fallback
    read is synchronous in the original; SiteStorage here is async-only,
    and every real caller (WorkerManager's downloadContentJson, wire
    protocol handlers) already has the content parsed before verifying it
    -- so the fallback was dead weight, not a feature this port drops.
  - lax_cert_check defaults to False (strict: a compromised cert issuer's
    users lose write access) where the original defaults to True
    (permissive: compromised-cert users keep write access, on the theory
    that losing legitimate contributors is worse than the spam risk).
    Flip it per-ContentManager if a site needs the original's default --
    but a security-relevant flag should start strict, not permissive.
  - bad_certs (the addBadCert()/isGoodCert() compromised-issuer list) is
    in-memory only, one set per ContentManager -- not the original's
    single process-wide set persisted to data_dir/badcerts.json. No
    config.data_dir equivalent exists in this stack to persist it to, and
    sharing a set process-wide across sites doesn't fit this package's
    per-Site-owns-its-ContentManager model anyway.
  - The original's verifyContent()'s running site-size-limit tracking
    (site.settings["size"]/["size_optional"] against getSizeLimit()) is
    NOT ported -- there's no settings dict or size-limit config in this
    Site model yet. What IS ported from verifyContentInclude() is the
    self-contained, per-include checks that don't need that running
    total: max_size/max_size_optional against this content's own size,
    files_allowed/files_allowed_optional patterns, includes_allowed.
  - One real bug fix, not just a scope cut: the original's compromised-
    cert check indexes cert_addresses[0] (the issuer address's first
    *character*, since cert_signers maps domain -> a single address
    string everywhere else, including its own verifyCert()) instead of
    the address itself -- silently making the spam-protection block a
    no-op in practice, since bad_certs entries are full addresses that
    will essentially never equal a single leading character. Ported as
    the address directly here (getUserContentRules() below), matching
    what verifyCert() already does with the same dict entry.

self.contents is a plain dict here, not the original's ContentDbDict (a
SQLite-backed structure wrapping Db.py, itself not fully ported -- see
Phase 3's DbBackground.py). Same .get()/[] interface getFileInfo() needs;
DB-backed caching is a separate, later concern. Likewise getTotalSize()
here recomputes from self.contents rather than tracking an incremental
running total on a settings dict that doesn't exist in this scoped model.

sign()/hashFile()/hashFiles() add write-side support for case 1 only --
root content.json, matching the read side's own root-vs-non-root split.
Non-root signing (writing to a "user_contents" subdirectory under a cert)
isn't ported, and private-site encryption (isPrivate()/wrapContent()/
encryptFiles()) isn't either -- sign() refuses outright rather than
silently producing an unencrypted content.json for a site that expects
one. See sign()'s own docstring for the detail.
"""
import io
import json
import re
import time

from Crypt import CryptBitcoin, CryptHash
from util import SafeRe


class VerifyError(Exception):
    pass


class SignError(Exception):
    pass


def _getDirname(path: str) -> str:
    """Pure-string port of util/helper.py's getDirname() -- not imported
    from there because that module pulls in gevent at import time, which
    this trio-native package avoids entirely."""
    if "/" in path:
        return path[:path.rfind("/") + 1].lstrip("/")
    return ""


class ContentManager:
    def __init__(self, storage, site_address: str, lax_cert_check: bool = False):
        self.storage = storage
        self.site_address = site_address
        self.contents: dict = {}  # content_inner_path -> parsed content.json dict
        self.bad_certs: set = set()  # compromised cert-issuer addresses -- see module docstring
        self.lax_cert_check = lax_cert_check

    def addBadCert(self, sign) -> None:
        addr = CryptBitcoin.get_sign_address_64("compromised", sign)
        if addr:
            self.bad_certs.add(addr)

    def isGoodCert(self, cert) -> bool:
        return cert not in self.bad_certs

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

    def getRules(self, inner_path: str, content: dict | None = None):
        """Resolve the rules governing inner_path: the plain {"signers":
        [...]} shape for root content.json, an "includes" entry for a
        subdirectory content.json listed in its parent's "includes", or
        the cert-signer-derived rules from getUserContentRules() for a
        "user_contents" (multi-user) subdirectory. Returns False if
        inner_path isn't covered by any loaded content.json."""
        inner_path = str(inner_path)
        if not inner_path.endswith("content.json"):
            file_info = self.getFileInfo(inner_path)
            if not file_info:
                return False
            inner_path = file_info["content_inner_path"]

        if inner_path == "content.json":
            return {"signers": self.getValidSigners(inner_path, content)}

        dirs = inner_path.split("/")
        inner_path_parts = [dirs.pop()]
        while dirs:
            inner_path_parts.insert(0, dirs.pop())
            content_inner_path = ("/".join(dirs) + "/content.json").strip("/")
            parent_content = self.contents.get(content_inner_path)
            if parent_content and "includes" in parent_content:
                return parent_content["includes"].get("/".join(inner_path_parts))
            elif parent_content and "user_contents" in parent_content:
                return self.getUserContentRules(parent_content, inner_path, content)
        return False

    def getUserContentRules(self, parent_content: dict, inner_path: str, content: dict | None):
        """Resolve write rules for a file inside a "user_contents"
        (multi-user/forum) subdirectory: which addresses may sign for this
        user, size/file-pattern limits, and whether their cert issuer is
        trusted. content must already be the parsed content.json covering
        inner_path -- see module docstring for why this doesn't fall back
        to reading it from storage itself."""
        if content is None:
            raise ValueError(
                "getUserContentRules() needs the parsed content dict for %s -- "
                "see P2P/ContentManager.py's module docstring." % inner_path
            )

        user_contents = parent_content["user_contents"]

        if "inner_path" in parent_content:
            parent_content_dir = _getDirname(parent_content["inner_path"])
            user_address = re.match(r"([A-Za-z0-9]*?)/", inner_path[len(parent_content_dir):]).group(1)
        else:
            user_address = re.match(r".*/([A-Za-z0-9]*?)/.*?$", inner_path).group(1)

        user_urn = "%s/%s" % (content.get("cert_auth_type", "n-a"), content.get("cert_user_id", "n-a"))
        cert_user_id = content.get("cert_user_id", "n-a")

        if user_address in user_contents["permissions"]:
            rules = dict(user_contents["permissions"].get(user_address, {}) or {})
        else:
            rules = dict(user_contents["permissions"].get(cert_user_id, {}) or {})

        banned = user_contents["permissions"].get(user_address) is False or user_contents["permissions"].get(cert_user_id) is False
        if "signers" in rules:
            rules["signers"] = rules["signers"][:]

        if content.get("cert_user_id") and content["cert_user_id"].count("@") == 1:
            name, domain = content["cert_user_id"].rsplit("@", 1)
            # NOTE: the original indexes this as cert_addresses[0] --
            # cert_signers maps domain -> a single address string
            # everywhere else (verifyCert() uses the same dict entry
            # directly as one address, not a sequence), so [0] there reads
            # as an off-by-one that silently checks isGoodCert() against
            # the address's first *character* instead of the address
            # itself, making the compromised-cert block effectively a
            # no-op. Fixed here: the full address, matching verifyCert().
            cert_address = parent_content["user_contents"].get("cert_signers", {}).get(domain)
        else:
            cert_address = None

        # To limit spam from a compromised cert issuer, only that issuer's
        # already-known signers keep write access unless lax_cert_check
        # explicitly accepts new ones from it too.
        if self.lax_cert_check or cert_address is None or self.isGoodCert(cert_address):
            permission_rules = user_contents.get("permission_rules", {}).items()
        else:
            permission_rules = {}.items()

        for permission_pattern, permission_rule in permission_rules:
            if not SafeRe.match(permission_pattern, user_urn):
                continue
            if permission_rule is None:
                permission_rule = {"max_size": 0, "max_size_optional": 0}
            for key, val in permission_rule.items():
                if key not in rules:
                    rules[key] = val[:] if isinstance(val, list) else val
                elif isinstance(val, int):
                    if val > rules[key]:
                        rules[key] = val
                elif isinstance(val, str):
                    if len(val) > len(rules[key]):
                        rules[key] = val
                elif isinstance(val, list):
                    rules[key] += val

        rules["cert_signers"] = user_contents.get("cert_signers", {})
        rules["cert_signers_pattern"] = user_contents.get("cert_signers_pattern")

        if "signers" not in rules:
            rules["signers"] = []
        if not banned:
            rules["signers"].append(user_address)
        rules["user_address"] = user_address
        rules["includes_allowed"] = False

        return rules

    def getValidSigners(self, inner_path: str, content: dict | None = None) -> list:
        if inner_path == "content.json":
            valid_signers = []
            root_content = self.contents.get("content.json")
            if root_content and "signers" in root_content:
                valid_signers += root_content["signers"][:]
        else:
            rules = self.getRules(inner_path, content)
            valid_signers = list(rules["signers"]) if rules and "signers" in rules else []
        if self.site_address not in valid_signers:
            valid_signers.append(self.site_address)
        return valid_signers

    def getSignsRequired(self, inner_path: str) -> int:
        return 1  # No multisig support yet (matches the original's own "Todo: Multisig")

    def verifyCertSign(self, user_address: str, user_auth_type: str, user_name: str, issuer_address: str, sign: str) -> bool:
        cert_subject = "%s#%s/%s" % (user_address, user_auth_type, user_name)
        return CryptBitcoin.verify(cert_subject, issuer_address, sign)

    def verifyCert(self, inner_path: str, content: dict) -> bool:
        rules = self.getRules(inner_path, content)
        if not rules:
            raise VerifyError("No rules for this file")

        if not rules.get("cert_signers") and not rules.get("cert_signers_pattern"):
            return True  # Does not need cert

        if "cert_user_id" not in content:
            raise VerifyError("Missing cert_user_id")
        if content["cert_user_id"].count("@") != 1:
            raise VerifyError("Invalid domain in cert_user_id")

        name, domain = content["cert_user_id"].rsplit("@", 1)
        cert_address = rules["cert_signers"].get(domain)
        if not cert_address:
            if rules.get("cert_signers_pattern") and SafeRe.match(rules["cert_signers_pattern"], domain):
                cert_address = domain
            else:
                raise VerifyError("Invalid cert signer: %s" % domain)

        return self.verifyCertSign(rules["user_address"], content["cert_auth_type"], name, cert_address, content["cert_sign"])

    def _verifyContentInclude(self, inner_path: str, content: dict, content_size: int, content_size_optional: int) -> bool:
        """Per-include structural checks that don't need a running site-size
        total -- see module docstring for what's NOT ported here."""
        rules = self.getRules(inner_path, content)
        if not rules:
            raise VerifyError("No rules")

        max_size = rules.get("max_size")
        if max_size is not None and content_size > max_size:
            raise VerifyError("Include too large %sB > %sB" % (content_size, max_size))

        if rules.get("max_size_optional") is not None and content_size_optional > rules["max_size_optional"]:
            raise VerifyError("Include optional files too large %sB > %sB" % (content_size_optional, rules["max_size_optional"]))

        if rules.get("files_allowed"):
            for file_inner_path in content.get("files", {}):
                if not SafeRe.match(r"^%s$" % rules["files_allowed"], file_inner_path):
                    raise VerifyError("File not allowed: %s" % file_inner_path)

        if rules.get("files_allowed_optional"):
            for file_inner_path in content.get("files_optional", {}):
                if not SafeRe.match(r"^%s$" % rules["files_allowed_optional"], file_inner_path):
                    raise VerifyError("Optional file not allowed: %s" % file_inner_path)

        if rules.get("includes_allowed") is False and content.get("includes"):
            raise VerifyError("Includes not allowed")

        return True

    def verifyContentJson(self, content: dict, size_limit_bytes: int | None = None, inner_path: str = "content.json") -> bool:
        """Verify a content.json: signature, replay/rollback protection,
        and structural rules. Root and non-root both go through here --
        non-root additionally runs the cert-signer chain (verifyCert(),
        via _verifySignature()) and the include-specific size/pattern
        checks (_verifyContentInclude()). Raises VerifyError on anything
        invalid rather than ever silently approving something unchecked.
        """
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

        if inner_path != "content.json":
            content_size = content_size_file + sum(
                f.get("size", 0) for f in content.get("files", {}).values() if f.get("size", 0) >= 0
            )
            content_size_optional = sum(
                f.get("size", 0) for f in content.get("files_optional", {}).values() if f.get("size", 0) >= 0
            )
            self._verifyContentInclude(inner_path, content, content_size, content_size_optional)

        return True

    def _verifySignature(self, inner_path: str, content: dict) -> bool:
        new_content = dict(content)
        old_sign = new_content.pop("sign", None)
        signs = new_content.pop("signs", None)
        sign_content = json.dumps(new_content, sort_keys=True)

        if not signs:
            if old_sign:
                raise VerifyError("Invalid old-style sign")
            raise VerifyError("Not signed")

        valid_signers = self.getValidSigners(inner_path, content)
        signs_required = self.getSignsRequired(inner_path)

        if inner_path == "content.json":
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
        else:
            if not self.verifyCert(inner_path, content):
                raise VerifyError("Invalid cert!")

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

    async def hashFile(self, file_relative_path: str) -> dict:
        content_bytes = await self.storage.read(file_relative_path)
        return {"sha512": CryptHash.sha512sum(io.BytesIO(content_bytes)), "size": len(content_bytes)}

    async def hashFiles(self, ignore_pattern=None) -> dict:
        """Hashes every real file under storage into a files_node dict.
        Root-content.json signing scope only, see sign()'s docstring:
        no optional-files distinction (files_optional_node), no hashfield
        bookkeeping (optionalDownloaded), no db-file exclusion beyond
        the plain content.json/dotfile/-old/-new skips."""
        files_node = {}
        for file_relative_path in await self.storage.walk("", ignore=ignore_pattern):
            file_name = file_relative_path.rsplit("/", 1)[-1]
            if file_name == "content.json":
                continue
            if file_name.startswith(".") or file_name.endswith("-old") or file_name.endswith("-new"):
                continue
            if not self.isValidRelativePath(file_relative_path):
                continue
            files_node[file_relative_path] = await self.hashFile(file_relative_path)
        return files_node

    async def sign(self, privatekey: str, extend: dict | None = None, filewrite: bool = True):
        """Create and sign the ROOT content.json. Return: the new content
        dict (whether or not filewrite happened).

        Deliberately narrower than the original's sign(), matching this
        file's own established root-vs-non-root split (see module
        docstring): only content.json itself, never a non-root "includes"/
        "user_contents" file -- that needs a cert issued to the signer,
        which requires the User/cert-issuance flow this file's read-side
        (verifyCert/getUserContentRules) supports but nothing here writes
        yet. No private-site encryption either (isPrivate()/wrapContent()/
        encryptFiles() aren't ported) -- signing a private site's
        content.json here would silently skip the envelope wrapping the
        original applies, so it's refused outright rather than produced
        wrong.
        """
        inner_path = "content.json"

        if self.contents.get(inner_path):
            content = dict(self.contents[inner_path])
        elif self.storage.isFile(inner_path):
            content = await self.storage.loadJson(inner_path)
            content.setdefault("files", {})
            content.setdefault("signs", {})
        else:
            content = {
                "files": {}, "signs": {},
                "title": "%s - ZeroNet_" % self.site_address,
                "description": "", "signs_required": 1, "ignore": "",
            }

        if content.get("private_recipients") or content.get("privatekey"):
            raise SignError("Private sites are not supported by this sign() -- see its own docstring")

        if extend:
            for key, val in extend.items():
                if not content.get(key):
                    content[key] = val

        files_node = await self.hashFiles(content.get("ignore"))

        new_content = dict(content)
        new_content["files"] = files_node
        new_content.pop("files_optional", None)
        new_content["modified"] = int(time.time())
        new_content["signs_required"] = content.get("signs_required", 1)
        new_content["address"] = self.site_address
        new_content["inner_path"] = inner_path

        privatekey_address = CryptBitcoin.privatekeyToAddress(privatekey)
        valid_signers = self.getValidSigners(inner_path, new_content)
        if privatekey_address not in valid_signers:
            raise SignError(
                "Private key invalid! Valid signers: %s, Private key address: %s" %
                (valid_signers, privatekey_address)
            )

        if privatekey_address == self.site_address:
            signers_data = "%s:%s" % (new_content["signs_required"], ",".join(valid_signers))
            new_content["signers_sign"] = CryptBitcoin.sign(signers_data, privatekey)

        new_content.pop("signs", None)
        new_content.pop("sign", None)
        sign_content = json.dumps(new_content, sort_keys=True)
        sign = CryptBitcoin.sign(sign_content, privatekey)
        new_content["signs"] = {privatekey_address: sign} if sign else {}

        if filewrite:
            await self.storage.writeJson(inner_path, new_content)
            self.contents[inner_path] = new_content

        return new_content
