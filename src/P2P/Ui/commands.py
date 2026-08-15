"""Trio port of a scoped slice of Ui/UiWebsocket.py's command surface --
bucket 3 of the "modern libraries vs hand-rolled" split from UiServer.py's
module docstring. Buckets 1 (wrapper HTML, Jinja2) and 2 (routing/CORS/
static files, Starlette) were replaced wholesale by libraries; this bucket
is genuine hand-rolled application logic that no library substitutes for,
so it's ported command by command -- same discipline as protocols/*.py on
the P2P side, not a one-pass translation of all ~30 commands.

Scoped to what the trio-native Site/SiteStorage/ContentManager stack
actually supports today. Deliberately NOT ported, because the thing they
need doesn't exist in this stack yet:
  - siteSign/sitePublish -- ContentManager has no sign(), only
    verifyContentJson()/_verifySignature() (see its own module docstring).
  - certAdd/certSelect/certList and the original's real per-user
    hasFilePermission() (which valid signer matches the *connecting user's*
    auth address) -- there's no User/UserManager ported yet, so fileWrite/
    fileDelete here are gated on "ADMIN" in site.permissions instead, a
    strictly coarser check than the original's own-site-or-authorized-
    signer rule.
  - siteAdd/siteDelete/siteClone/sitePause/siteResume -- needs
    SiteManager, not ported.
  - serverUpdate/serverShutdown/configSet/dbQuery -- needs the global
    `main` module server handles and Db.py, neither wired into this
    package.
  - The original's channel *events* (site.websockets iteration pushing
    "setSiteInfo"/etc. to other joined connections on change) -- channelJoin
    here only tracks per-session membership, since nothing in this stack
    yet emits change events to push.
"""
import base64
import os
import stat

from .UiServer import command


class CommandError(Exception):
    pass


def _requireSite(session):
    if session.site is None:
        raise CommandError("No site for this connection")
    return session.site


def _requireAdmin(session):
    site = _requireSite(session)
    if "ADMIN" not in site.permissions:
        raise CommandError("You don't have permission to run this command")
    return site


def _param(params, key, index, default=None):
    if isinstance(params, dict):
        return params.get(key, default)
    if isinstance(params, list):
        return params[index] if len(params) > index else default
    return default


@command("ping")
async def _cmdPing(session, params):
    return "pong"


@command("channelJoin")
async def _cmdChannelJoin(session, params):
    channels = _param(params, "channels", 0)
    if not isinstance(channels, list):
        channels = [channels]
    for channel in channels:
        if channel not in session.channels:
            session.channels.append(channel)
    return "ok"


def formatSiteInfo(site):
    content = site.content_manager.contents.get("content.json")
    if content:
        content = dict(content)
        content["files"] = len(content.get("files", {}))
        content["files_optional"] = len(content.get("files_optional", {}))
        content["includes"] = len(content.get("includes", {}))
        content.pop("sign", None)
        content.pop("signs", None)
        content.pop("signers_sign", None)
    return {
        "address": site.address,
        "address_hash": site.address_sha1.hex(),
        "permissions": list(site.permissions),
        "serving": site.isServing(),
        "peers": len(site.peers),
        "content": content,
    }


@command("siteInfo")
async def _cmdSiteInfo(session, params):
    return formatSiteInfo(_requireSite(session))


@command("fileGet")
async def _cmdFileGet(session, params):
    site = _requireSite(session)
    inner_path = _param(params, "inner_path", 0)
    fmt = _param(params, "format", 1, "text")
    if not site.storage.isFile(inner_path):
        return None
    body = await site.storage.read(inner_path, "rb")
    if fmt == "base64":
        return base64.b64encode(body).decode()
    return body.decode()


@command("fileList")
async def _cmdFileList(session, params):
    site = _requireSite(session)
    inner_path = _param(params, "inner_path", 0, "")
    return await site.storage.walk(inner_path)


@command("dirList")
async def _cmdDirList(session, params):
    site = _requireSite(session)
    inner_path = _param(params, "inner_path", 0, "")
    stats = _param(params, "stats", 1, False)
    names = await site.storage.list(inner_path)
    if not stats:
        return list(names)
    back = []
    for name in names:
        rel_path = ("%s/%s" % (inner_path, name)) if inner_path else name
        file_stat = os.stat(site.storage.getPath(rel_path))
        back.append({"name": name, "size": file_stat.st_size, "is_dir": stat.S_ISDIR(file_stat.st_mode)})
    return back


@command("fileWrite")
async def _cmdFileWrite(session, params):
    site = _requireAdmin(session)
    inner_path = _param(params, "inner_path", 0)
    content_base64 = _param(params, "content_base64", 1)
    content = base64.b64decode(content_base64)
    await site.storage.write(inner_path, content)
    if inner_path.endswith("content.json"):
        await site.content_manager.loadContent(inner_path)
    return "ok"


@command("fileDelete")
async def _cmdFileDelete(session, params):
    site = _requireAdmin(session)
    inner_path = _param(params, "inner_path", 0)
    await site.storage.delete(inner_path)
    return "ok"
