"""Trio port of Ui/UiWebsocket.py's command surface -- bucket 3 of the
"modern libraries vs hand-rolled" split from UiServer.py's module
docstring. Buckets 1 (wrapper HTML, Jinja2) and 2 (routing/CORS/static
files, Starlette) were replaced wholesale by libraries; this bucket is
genuine hand-rolled application logic that no library substitutes for,
so it's ported command by command -- same discipline as protocols/*.py
on the P2P side, not a one-pass translation of all ~30 commands.

This second pass adds the commands that were blocked on infrastructure
that didn't exist yet when the first 8 (ping/siteInfo/channelJoin/
fileGet/fileList/dirList/fileWrite/fileDelete) were ported: ContentManager
.sign(), SiteManager, UserManager, and P2P.Db, all landed since. Added
here: siteSign, sitePublish, certAdd, certSet, certList, siteAdd,
siteDelete, sitePause, siteResume, siteList, permissionAdd,
permissionRemove, permissionDetails, userGetSettings, userSetSettings,
userGetGlobalSettings, userSetGlobalSettings, dbQuery.

Admin gating throughout matches the original's own model: a command that
needs @flag.admin in the original is gated here on "ADMIN" being in the
CONNECTED site's own permissions (_requireAdmin()) -- same check
fileWrite/fileDelete already used, not a new pattern.

sitePublish now pushes for real: UiApp takes an optional file_server
reference (P2P/app.py already owns both file_server and ui_server side by
side, so this is just threading an existing object through, not new
protocol work) and reuses the same _sitePeers()/publishUpdate() pattern
P2P/actions.py's CLI sitePublish already established. Unlike the CLI
version, though, this does NOT announce() first or raise if no peers are
reachable -- a websocket command handler shouldn't block on a fresh DHT/
tracker announce round trip just to answer "did the sign work", and the
original's own sitePublish doesn't either (it pushes to whatever peers
are already known and reports success either way). If UiApp has no
file_server configured (file_server=None, e.g. a UiServer built without
one), sitePublish still signs and marks serving, just doesn't push --
same graceful degradation as before this file_server wiring landed.

Still NOT ported, because the thing they need doesn't exist in this stack
(or isn't a good match for a headless command handler):
  - certSelect -- the original builds an HTML "select account" dialog and
    round-trips it through the client via cmd("notification")/cmd(
    "injectScript"); that's UI-rendering logic entangled with a specific
    client-side notification widget, not a good match for a headless
    command handler. certAdd/certSet/certList (the actual cert data
    operations certSelect wraps) are ported.
  - siteClone, siteFavourite/siteUnfavourite (needs a "dashboard" site
    concept not modeled here), announcerStats, serverInfo (needs
    FileServer/Host details -- ports, external IP, peer_id -- that aren't
    passed into UiApp), serverUpdate/serverShutdown/configSet (need the
    global `main` module server handles this package deliberately has no
    equivalent of -- see P2P/app.py's own module docstring), siteCmd's
    server-side counterpart siteListModifiedFiles, dbRebuild (CLI-only,
    via P2P/actions.py -- a destructive full-rebuild isn't a great fit
    for an unauthenticated-beyond-wrapper_key websocket command either).
  - The original's channel *events* (site.websockets iteration pushing
    "setSiteInfo"/etc. to other joined connections on change) -- channelJoin
    here only tracks per-session membership, since nothing in this stack
    yet emits change events to push.

siteVerify() re-derives its own equivalent of the original's
site.storage.verifyFiles() inline (a hash-check pass over every file
every loaded content.json lists) rather than adding that to
SiteStorage.py -- SiteStorage.py already documents that verifyFiles()
needs ContentManager pieces (hashfield) not ported, and this narrower
version (using ContentManager.verifyFile() directly, no hashfield
bookkeeping) is all a CLI verify command actually needs. (Note: this
paragraph describes P2P/actions.py's siteVerify, not a websocket command
-- there is no UI-facing siteVerify; verification is a CLI-only action
in the original too.)
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


def _requireSiteManager(session):
    site_manager = getattr(session.app, "site_manager", None)
    if site_manager is None:
        raise CommandError("This server has no site manager configured")
    return site_manager


async def _requireUser(session):
    user_manager = getattr(session.app, "user_manager", None)
    if user_manager is None:
        raise CommandError("This server has no user manager configured")
    user = await user_manager.get()
    if user is None:
        raise CommandError("No user available")
    return user


def _param(params, key, index, default=None):
    if isinstance(params, dict):
        return params.get(key, default)
    if isinstance(params, list):
        return params[index] if len(params) > index else default
    return default


def _sitePeers(session, site, need_num: int = 5) -> list:
    """Same pattern as P2P/actions.py's Actions._sitePeers(): builds real,
    dialable Peer objects from site.getConnectablePeers(), registering
    each record's ip/port (when known) into the host's peerstore first --
    see that method's own docstring for why that registration step is
    necessary at all. Returns [] if this UiApp has no file_server
    configured (sitePublish degrades to sign-only in that case)."""
    file_server = getattr(session.app, "file_server", None)
    if file_server is None:
        return []

    from multiaddr import Multiaddr

    from ..Peer import Peer

    records = site.getConnectablePeers(need_num=need_num)
    peerstore = file_server.host.get_peerstore()
    peers = []
    for record in records:
        if record.ip and record.port:
            try:
                peerstore.add_addrs(record.peer_id, [Multiaddr("/ip4/%s/tcp/%s" % (record.ip, record.port))], 3600)
            except Exception:
                pass
        peers.append(Peer(record.peer_id, file_server.host, file_server.connection_policy))
    return peers


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


# -- Site signing / publishing --

@command("siteSign")
async def _cmdSiteSign(session, params):
    site = _requireAdmin(session)
    privatekey = _param(params, "privatekey", 0)
    if not privatekey:
        user_manager = getattr(session.app, "user_manager", None)
        user = await user_manager.get() if user_manager else None
        if user:
            privatekey = user.getSiteData(site.address, create=False).get("privatekey")
    if not privatekey:
        raise CommandError("No privatekey given and none stored for this site")
    await site.content_manager.sign(privatekey)
    return "ok"


@command("sitePublish")
async def _cmdSitePublish(session, params):
    """Signs (unless sign=False), marks the site serving, and pushes to
    whatever peers are already known (no fresh announce -- see module
    docstring). Still returns "ok" even if nothing was reachable to push
    to: the sign+serve part always succeeded, and the original's own
    sitePublish doesn't fail the command over an unreachable swarm
    either."""
    site = _requireAdmin(session)
    if _param(params, "sign", 1, True):
        await _cmdSiteSign(session, params)
    site.serving = True

    inner_path = _param(params, "inner_path", 2, "content.json")
    if inner_path in site.content_manager.contents:
        peers = _sitePeers(session, site)
        if peers:
            from ..WorkerManager import publishUpdate
            await publishUpdate(site, peers, inner_path=inner_path)

    return "ok"


# -- Certificates --

@command("certAdd")
async def _cmdCertAdd(session, params):
    user = await _requireUser(session)
    auth_address = _param(params, "auth_address", 0)
    domain = _param(params, "domain", 1)
    auth_type = _param(params, "auth_type", 2)
    auth_user_name = _param(params, "auth_user_name", 3)
    cert_sign = _param(params, "cert_sign", 4) or _param(params, "cert", 4)
    result = await user.addCert(auth_address, domain, auth_type, auth_user_name, cert_sign)
    if result is True:
        return "ok"
    elif result is None:
        return "Not changed"
    else:
        return {"error": "Certificate not added: already have a different one for this domain"}


@command("certSet")
async def _cmdCertSet(session, params):
    site = _requireAdmin(session)
    user = await _requireUser(session)
    domain = _param(params, "domain", 0)
    user.setCert(site.address, domain)
    return "ok"


@command("certList")
async def _cmdCertList(session, params):
    site = _requireAdmin(session)
    user = await _requireUser(session)
    auth_address = user.getAuthAddress(site.address, create=False)
    back = []
    for domain, cert in user.certs.items():
        back.append({
            "auth_address": cert["auth_address"],
            "auth_type": cert["auth_type"],
            "auth_user_name": cert["auth_user_name"],
            "domain": domain,
            "selected": cert["auth_address"] == auth_address,
        })
    return back


# -- Site management (admin, via SiteManager) --

@command("siteAdd")
async def _cmdSiteAdd(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0)
    if address in site_manager.sites:
        return {"error": "Site already added"}
    site = site_manager.add(address)
    if not site:
        return {"error": "Invalid address"}
    return "ok"


@command("siteDelete")
async def _cmdSiteDelete(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0)
    if address not in site_manager.sites:
        return {"error": "Unknown site: %s" % address}
    site_manager.delete(address)
    return "Deleted"


@command("sitePause")
async def _cmdSitePause(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0)
    site = site_manager.sites.get(address)
    if not site:
        return {"error": "Unknown site: %s" % address}
    site.serving = False
    return "Paused"


@command("siteResume")
async def _cmdSiteResume(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0)
    site = site_manager.sites.get(address)
    if not site:
        return {"error": "Unknown site: %s" % address}
    site.serving = True
    return "Resumed"


@command("siteList")
async def _cmdSiteList(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    return [formatSiteInfo(site) for site in site_manager.sites.values()]


# -- Permissions --

_PERMISSION_DETAILS = {
    "ADMIN": "Allow this site to administrate your 0net node (Make sure you trust site developer before accepting!)",
    "NOSANDBOX": "Modify your client's configuration and access all site (Dangerous!)",
    "PushNotification": "Send notifications",
}


@command("permissionAdd")
async def _cmdPermissionAdd(session, params):
    site = _requireAdmin(session)
    permission = _param(params, "permission", 0)
    if permission not in site.permissions:
        site.permissions.append(permission)
    return "ok"


@command("permissionRemove")
async def _cmdPermissionRemove(session, params):
    site = _requireAdmin(session)
    permission = _param(params, "permission", 0)
    if permission in site.permissions:
        site.permissions.remove(permission)
    return "ok"


@command("permissionDetails")
async def _cmdPermissionDetails(session, params):
    _requireAdmin(session)
    permission = _param(params, "permission", 0)
    return _PERMISSION_DETAILS.get(permission, "")


# -- User settings --

@command("userGetSettings")
async def _cmdUserGetSettings(session, params):
    site = _requireSite(session)
    user = await _requireUser(session)
    return user.getSiteData(site.address, create=False).get("settings", {})


@command("userSetSettings")
async def _cmdUserSetSettings(session, params):
    site = _requireSite(session)
    user = await _requireUser(session)
    settings = _param(params, "settings", 0)
    user.setSiteSettings(site.address, settings)
    return "ok"


@command("userGetGlobalSettings")
async def _cmdUserGetGlobalSettings(session, params):
    user = await _requireUser(session)
    return user.settings


@command("userSetGlobalSettings")
async def _cmdUserSetGlobalSettings(session, params):
    _requireAdmin(session)
    user = await _requireUser(session)
    settings = _param(params, "settings", 0)
    user.settings = settings
    await user.save()
    return "ok"


# -- Db --

@command("dbQuery")
async def _cmdDbQuery(session, params):
    site = _requireSite(session)
    query = _param(params, "query", 0)
    query_params = _param(params, "params", 1)
    try:
        res = await site.storage.query(query, query_params)
    except Exception as err:
        return {"error": str(err)}
    return [dict(row) for row in res.fetchall()]
