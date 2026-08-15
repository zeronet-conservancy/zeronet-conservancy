"""Trio port of a real, network-independent slice of Actions.py's CLI
commands -- the ones that operate purely on local state this stack
already owns (SiteManager/UserManager/ContentManager/SiteStorage), no
running Host/FileServer/UiServer session required.

Ported: siteCreate, siteSign, siteVerify, dbRebuild, dbQuery, plus the
four crypto commands (cryptPrivatekeyToAddress/cryptSign/cryptVerify/
cryptGetPrivatekey, trivial CryptBitcoin wrappers with no site/network
dependency at all).

Deliberately NOT ported here, because they need a live networking
session (a running P2P.app.App, not just local state): siteAnnounce,
siteDownload, siteNeedFile, sitePublish, siteCmd, peerPing, peerGetFile,
peerCmd. Those are a different kind of command -- "do something over the
wire" rather than "read/write local site state" -- and belong wired
against an actual running App instance (P2P/app.py), not reimplemented
here as one-shot connections the way the original's Actions.py does (a
fresh ConnectionServer per invocation). Also not ported: importBundle,
getConfig, test, ipythonThread/main (main is P2P.app.main() already);
main's server-lifecycle role is what P2P/app.py's App.run() already is.

siteVerify() re-derives its own equivalent of the original's
site.storage.verifyFiles() inline (a hash-check pass over every file
every loaded content.json lists) rather than adding that to
SiteStorage.py -- SiteStorage.py already documents that verifyFiles()
needs ContentManager pieces (hashfield) not ported, and this narrower
version (using ContentManager.verifyFile() directly, no hashfield
bookkeeping) is all a CLI verify command actually needs.
"""
import io
import json
import logging
import pathlib

import trio

from Crypt import CryptBitcoin

from .ContentManager import _getDirname
from .SiteManager import SiteManager
from .UserManager import UserManager

log = logging.getLogger("P2P.actions")


class ActionError(Exception):
    pass


class Actions:
    def __init__(self, data_dir: pathlib.Path):
        self.data_dir = data_dir
        self.site_manager = SiteManager(data_dir)
        self.user_manager = UserManager(data_dir)

    async def _getSite(self, address: str):
        if not self.site_manager.loaded:
            await self.site_manager.load()
        site = self.site_manager.get(address)
        if site is None:
            raise ActionError("Site not found: %s" % address)
        return site

    async def _getOrCreateUser(self):
        user = await self.user_manager.get()
        if user is None:
            user = self.user_manager.create()
        return user

    # -- Site commands --

    async def siteCreate(self, use_master_seed: bool = True) -> dict:
        log.info("Generating new privatekey (use_master_seed: %s)...", use_master_seed)
        if use_master_seed:
            user = await self._getOrCreateUser()
            address, address_index, site_data = await user.getNewSiteData()
            privatekey = site_data["privatekey"]
            log.info("Generated using master seed from users.json, site index: %s", address_index)
        else:
            privatekey = CryptBitcoin.newPrivatekey()
            address = CryptBitcoin.privatekeyToAddress(privatekey)
            address_index = None

        log.info("Site private key: %s", privatekey)
        log.info("                  !!! ^ Save it now, required to modify the site ^ !!!")
        log.info("Site address:     %s", address)

        if not self.site_manager.loaded:
            await self.site_manager.load()
        site = self.site_manager.add(address, own=True)
        await site.storage.write("index.html", ("Hello %s!" % address).encode("utf8"))

        extend = {"postmessage_nonce_security": True}
        if address_index is not None:
            extend["address_index"] = address_index
        await site.content_manager.sign(privatekey, extend=extend)
        await self.site_manager.save()

        log.info("Site created!")
        return {"address": address, "privatekey": privatekey}

    async def siteSign(self, address: str, privatekey: str | None = None, publish: bool = False) -> bool:
        site = await self._getSite(address)
        log.info("Signing site: %s...", address)

        if not privatekey:
            user = await self.user_manager.get()
            if user:
                privatekey = user.getSiteData(address, create=False).get("privatekey")
            if not privatekey:
                raise ActionError("No privatekey given and none stored in users.json for %s" % address)

        await site.content_manager.sign(privatekey)
        log.info("Site signed!")

        if publish:
            log.info("publish=True requires a running networking session (P2P.app.App) -- not started here.")
        return True

    async def siteVerify(self, address: str) -> dict:
        site = await self._getSite(address)
        log.info("Verifying site: %s...", address)
        cm = site.content_manager
        if "content.json" not in cm.contents:
            await cm.loadContent("content.json")

        bad_files = []
        for content_inner_path, content in list(cm.contents.items()):
            try:
                raw = await site.storage.read(content_inner_path)
                cm._verifySignature(content_inner_path, json.loads(raw))
                log.info("[OK] %s", content_inner_path)
            except Exception as err:
                log.error("[ERROR] %s: invalid file: %s!", content_inner_path, err)
                bad_files.append(content_inner_path)

            content_dir = _getDirname(content_inner_path)
            for file_relative_path in content.get("files", {}):
                file_inner_path = (content_dir + file_relative_path).strip("/")
                try:
                    raw = await site.storage.read(file_inner_path)
                    cm.verifyFile(file_inner_path, io.BytesIO(raw), ignore_same=False)
                except Exception as err:
                    log.error("[ERROR] %s: invalid file: %s!", file_inner_path, err)
                    bad_files.append(file_inner_path)

        if not bad_files:
            log.info("[OK] All files verified!")
        else:
            log.error("[ERROR] %s bad file(s) found!", len(bad_files))
        return {"bad_files": bad_files}

    async def dbRebuild(self, address: str) -> bool:
        site = await self._getSite(address)
        log.info("Rebuilding site sql cache: %s...", address)
        applied = await site.storage.rebuildDb(site.content_manager, reason="CLI dbRebuild")
        log.info("Done.")
        return applied

    async def dbQuery(self, address: str, query: str) -> list:
        site = await self._getSite(address)
        res = await site.storage.query(query)
        return [dict(row) for row in res.fetchall()]

    # -- Crypto commands (no site/network dependency) --

    def cryptPrivatekeyToAddress(self, privatekey: str) -> str:
        return CryptBitcoin.privatekeyToAddress(privatekey)

    def cryptSign(self, message: str, privatekey: str) -> str:
        return CryptBitcoin.sign(message, privatekey)

    def cryptVerify(self, message: str, sign: str, address: str) -> bool:
        return CryptBitcoin.verify(message, address, sign)

    def cryptGetPrivatekey(self, master_seed: str, site_address_index: int | None = None):
        if len(master_seed) != 64:
            raise ActionError("Invalid master seed length: %s (required: 64)" % len(master_seed))
        return CryptBitcoin.hdPrivatekey(master_seed, site_address_index)


async def _dispatch(args) -> None:
    actions = Actions(args.data_dir)
    method = getattr(actions, args.command, None)
    if method is None:
        raise SystemExit("Unknown command: %s" % args.command)

    kwargs = json.loads(args.kwargs) if args.kwargs else {}
    result = method(**kwargs)
    if hasattr(result, "__await__"):
        result = await result
    if result is not None:
        print(json.dumps(result, indent=2, default=str))


def main() -> None:
    """`python -m P2P.actions <command> --data-dir ... [--kwargs '{"address": "..."}']`"""
    import argparse

    parser = argparse.ArgumentParser(description="zeronet-conservancy trio-native CLI actions")
    parser.add_argument("command")
    parser.add_argument("--data-dir", type=pathlib.Path, required=True)
    parser.add_argument("--kwargs", help="JSON object of keyword arguments for the command")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    trio.run(_dispatch, args)


if __name__ == "__main__":
    main()
