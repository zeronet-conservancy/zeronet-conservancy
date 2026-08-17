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

A third pass adds serverInfo, announcerInfo, and siteListModifiedFiles.
serverInfo is deliberately narrower than the original -- only fields
genuinely available from what's threaded into UiApp (peer_id, listen
addrs, site count from file_server), no port_opened/tor/version/config
fingerprinting, since none of that exists in this stack yet.
announcerInfo needs UiApp's new `announcers` reference (site address ->
P2P.SiteAnnouncer, same threading pattern as file_server/site_manager/
user_manager -- P2P/app.py already owns this dict) and
TrackerStats.all() (a small new accessor on discovery/tracker.py's
TrackerStats, alongside its existing per-tracker get()).
siteListModifiedFiles skips the original's site.settings["cache"]-backed
"only recheck since last signed" shortcut (that settings dict doesn't
exist in this stack -- see P2P.SiteManager's own docstring) and always
walks every listed file; still capped at 100 files, same as the
original, so this stays cheap for the sizes this stack deals with.

certSelect (uses the wrapper's existing notification/injected-script
channel to provide the account selector, including the local auth
identity and provider registration links), serverShutdown, and configSet
(the latter via the UiConfig plugin, not this file) are all ported now,
despite older notes in this file once listing them as gaps -- checked
against the actual @command(...) registrations, not just this docstring,
before writing this.

A later pass adds the Multiuser plugin's own account-switching/master-seed
commands (userShowMasterSeed, userLogout, userSelectForm, userSet,
userLoginForm, userLogin) -- the "log into a DIFFERENT existing account"
half of multiuser support, on top of the account-isolation primitive
UserManager.multiuser already provided. Restructured the same way
certSelect/corsPermission already were: the original drives its account
picker and login prompt via a server-held response continuation
(self.cmd(..., callback)), which this stack's fire-and-forget
UiSession.push() has no equivalent of, so the client-side injected script
calls the follow-up command (userSet/userLogin) directly instead of
round-tripping through a callback the server would have to keep state for.

_resolveMergerPath() (used by fileGet/fileList/dirList via the new
_resolveCrossSitePath() dispatcher, alongside _resolveCorsPath()) is a
real, narrow port of plugins/MergerSite/MergerSitePlugin.py's own
checkMergerPath(): an inner_path of "merged-<type>/<address>/<rest>"
reads from a DIFFERENT site than the one this connection is scoped to,
provided the connected site declares a "Merger:<type>" permission and
the target site's own content.json declares "merged_type": "<type>".
Unlike the original's cached merger_db/merged_db module globals (rebuilt
explicitly on SiteManager.load()/saveDelayed()), _mergerTypes()/
_mergedType() below just read live site state on every call -- cheap
(a permissions list scan, a dict lookup already in memory) and never
stale, so there's no rebuild-on-mutation bookkeeping to get wrong.
P2P/plugins/MergerSite/commands.py's own mergerSiteList, mergerSiteAdd,
and mergerSiteDelete now all use these same two helpers too -- see that
module's own docstring. Narrower than the original: the read side is
read-only (fileGet/fileList/dirList), same scope _resolveCorsPath()
itself is limited to, and there's still no hasSitePermission() cross-site
bridge or actionPermissionDetails.

Still NOT ported, because the thing they need doesn't exist in this stack
(or isn't a good match for a headless command handler):
  - announcerStats (the ALL-sites admin aggregation, as opposed to
    announcerInfo's per-site report -- the original filters by
    self.site.announcer.getTrackers(), which is always [] in this
    stack's core with no tracker plugins registered yet, so a faithful
    port would always return {}; not worth the extra surface for
    something that can't do anything until a tracker plugin exists).
  - serverUpdate (the original's self-update-and-restart flow -- no
    equivalent of the global `main` module server handles this package
    deliberately has, see P2P/app.py's own module docstring, and no
    update-channel/restart mechanism either).
  - dbRebuild as a UI command (CLI-only, via P2P/actions.py -- a
    destructive full-rebuild isn't a great fit for an
    unauthenticated-beyond-wrapper_key websocket command either).
  - The original's channel *events* triggered by genuinely background,
    non-UI-initiated activity -- peer count changes, optional-file
    discovery, etc. UiApp.broadcast() itself is real and used now
    (sitePublish/sitePause/siteResume/siteUpdate/fileNeed, all
    user-initiated, plus one real network-driven trigger via
    FileServer.on_update_applied when a peer pushes us a fresh
    content.json -- see UiServer.py's own module docstring), so this
    gap is narrower than it used to be, not the "nothing pushes at all"
    it once was.

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
import copy
import html
import os
import re
import stat
import sys
from pathlib import Path

from Config import config
from Crypt import CryptBitcoin, CryptHash
from util import QueryJson, SafeRe

from ..ContentManager import _getDirname
from ..PluginManager import plugin_manager
from .UiServer import COMMAND_HANDLERS, command


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


_CORS_PATH_RE = re.compile(r"^cors-([A-Za-z0-9]{26,35})/(.*)$")


def _resolveCorsPath(session, inner_path):
    """Port of plugins/Cors/CorsPlugin.py's corsFuncWrapper()/
    getCorsPath(): an inner_path of "cors-<address>/<rest>" reads from a
    DIFFERENT site than the one this connection is scoped to, provided
    the connected site was granted "Cors:<address>" (or is ADMIN).
    "Cors" here is this stack's cross-SITE permission grant, not the
    browser CORS security feature its name suggests -- reused verbatim
    from the original's own docstring-less name, not renamed, to avoid
    inventing a second name for the same concept the sites/plugins that
    use this already call "cors".

    Narrower than the original two ways: only the read-only commands
    that (a) the original's own corsFuncWrapper actually covers and
    (b) exist in this stack at all -- fileGet/fileList/dirList, not
    fileRules/optionalFileInfo (neither ported here yet). And no HTTP
    cors-<address>/file.jpg raw-file route (UiRequest.py's own
    parsePath() half) -- websocket commands only.

    Grant is direct (see corsPermissionAdd below), not gated behind the
    original's own client-side confirm-dialog round trip -- this stack
    has no server-initiated request/response continuation mechanism yet
    (UiSession.push() is fire-and-forget), matching how permissionAdd
    already grants directly with no confirm step."""
    match = _CORS_PATH_RE.match(inner_path)
    if not match:
        return _requireSite(session), inner_path
    acting_site = _requireSite(session)
    cors_address, cors_inner_path = match.groups()
    if ("Cors:%s" % cors_address) not in acting_site.permissions and "ADMIN" not in acting_site.permissions:
        raise CommandError("This site has no permission to access site %s" % cors_address)
    site_manager = _requireSiteManager(session)
    target_site = site_manager.sites.get(cors_address)
    if target_site is None:
        raise CommandError("No site found: %s" % cors_address)
    return target_site, cors_inner_path


def _mergedType(site):
    """The merge type this site itself declares via content.json's own
    "merged_type" key (e.g. "ZeroMe"), or None if it isn't a mergeable
    per-user site at all. Matches MergerSitePlugin.updateMergerSites()'s
    own merged_db derivation -- just computed live instead of cached."""
    return site.content_manager.contents.get("content.json", {}).get("merged_type")


def _mergerTypes(site):
    """Every merge type this site is allowed to READ merged content as,
    derived from its own "Merger:<type>" permission strings -- matches
    MergerSitePlugin.updateMergerSites()'s own merger_db derivation."""
    return [p[len("Merger:"):] for p in site.permissions if p.startswith("Merger:")]


_MERGED_PATH_RE = re.compile(r"^merged-([A-Za-z0-9_-]+)/([A-Za-z0-9]{26,35})/(.*)$")


def _resolveMergerPath(session, inner_path):
    """Port of plugins/MergerSite/MergerSitePlugin.py's own
    checkMergerPath(): an inner_path of "merged-<type>/<address>/<rest>"
    reads from a DIFFERENT site than the one this connection is scoped
    to, provided the connected site declares a "Merger:<type>"
    permission AND the target site's own content.json declares itself
    as "merged_type": "<type>" -- both checks the original makes, kept
    here. See this file's own module docstring for full scope."""
    match = _MERGED_PATH_RE.match(inner_path)
    if not match:
        return _requireSite(session), inner_path
    acting_site = _requireSite(session)
    merger_type, merged_address, merged_inner_path = match.groups()
    if merger_type not in _mergerTypes(acting_site):
        raise CommandError(
            "No merger (%s) permission to load: %s (%s not in %s)"
            % (acting_site.address, inner_path, merger_type, _mergerTypes(acting_site))
        )
    site_manager = _requireSiteManager(session)
    target_site = site_manager.sites.get(merged_address)
    if target_site is None:
        raise CommandError("No site found: %s" % merged_address)
    if _mergedType(target_site) != merger_type:
        raise CommandError(
            "Merger site (%s) does not have permission for merged site: %s (%s)"
            % (merger_type, merged_address, _mergedType(target_site))
        )
    return target_site, merged_inner_path


def _resolveCrossSitePath(session, inner_path):
    """Dispatches fileGet/fileList/dirList's inner_path to whichever
    cross-site scheme (if any) it uses -- "merged-<type>/<address>/..."
    (MergerSite) or "cors-<address>/..." (Cors) -- falling back to the
    connection's own site otherwise. The two prefixes are mutually
    exclusive by construction (checked directly rather than chaining
    both resolvers), so a merger-resolved inner_path is never
    mistakenly re-resolved as a cors path, or vice versa."""
    if inner_path.startswith("merged-"):
        return _resolveMergerPath(session, inner_path)
    if inner_path.startswith("cors-"):
        return _resolveCorsPath(session, inner_path)
    return _requireSite(session), inner_path


async def _requireUser(session):
    """Get-or-create, not get-or-fail: a fresh --p2p install has no user
    until something explicitly creates one (only siteCreate did, until
    this fix). Without this, every per-user websocket command --
    including userGetGlobalSettings, which the real wrapper.js's own
    ZeroSiteTheme.coffee calls unconditionally on every page load to
    sync dark/light theme -- errored out from the very first page load
    on a brand new install, matching original ZeroNet's own implicit
    "a local single-user-mode client always has a user" behavior.

    In multiuser mode, resolves by session.master_address (the cookie
    UiApp._ensureMultiuserCookie already validated -- or minted a fresh
    account and a fresh cookie for -- before this session's websocket
    ever connected; see that method's and UiSession's own docstrings).
    A master_address that doesn't resolve to a real user here means this
    particular connection's cookie was never validated by that HTTP path
    at all (a raw/programmatic websocket client, not a real browser that
    loaded a wrapper page first) -- falls back to the same get-or-create
    single-user behavior below rather than fabricating a user for an
    address nothing can prove ownership of (an address is derived FROM a
    seed, not freely assignable)."""
    user_manager = getattr(session.app, "user_manager", None)
    if user_manager is None:
        raise CommandError("This server has no user manager configured")
    if user_manager.multiuser and session.master_address:
        user = await user_manager.get(session.master_address)
        if user is not None:
            return user
    user = await user_manager.get()
    if user is None:
        user = user_manager.create()
    return user


def _param(params, key, index, default=None):
    """Found live: the real wrapper.js's own ws.cmd() (all.js) sends
    single-argument commands with a bare scalar as "params" -- e.g.
    ws.cmd("permissionAdd", permission, cb) puts the plain string
    "ADMIN" straight in the "params" field, not ["ADMIN"] or
    {"permission": "ADMIN"}. The original's own handleRequest() dispatch
    explicitly supports this as a third calling convention ("Support
    calling as named, unnamed parameters and raw first argument too"):
    dict -> **kwargs, list -> *args, any other truthy value -> the sole
    positional arg. Without this branch, a bare-scalar call silently
    resolved to the default (usually None) for every command that uses
    this convention -- reproduced live via the ADMIN grant flow: the
    "Grant" button's permissionAdd(permission) call persisted `null"
    instead of "ADMIN" (permission never actually took), and
    permissionDetails(permission) returned "" (the grant dialog's
    "undefined" description text)."""
    if isinstance(params, dict):
        return params.get(key, default)
    if isinstance(params, list):
        return params[index] if len(params) > index else default
    if params is not None and index == 0:
        return params
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


class _AsSiteProxy:
    """Site stand-in used by the "as" command below: delegates every
    attribute to the target site except `permissions`, which stays the
    acting connection's own -- matching the original UiWebsocket.actionAs,
    where hasCmdPermission stays bound to the original `self` (the acting
    connection), not the site being acted on. Without this, a dashboard
    site (ADMIN on itself, not on the target) couldn't run admin-gated
    commands like siteSetLimit against sites it doesn't own, which is the
    entire point of "as" -- it's how the sidebar's per-site buttons work."""
    def __init__(self, target_site, acting_permissions):
        self._target = target_site
        self.permissions = acting_permissions

    def __getattr__(self, name):
        return getattr(self._target, name)


@command("as")
async def _cmdAs(session, params):
    acting_site = _requireSite(session)
    address = _param(params, "address", 0)
    cmd = _param(params, "cmd", 1)
    inner_params = _param(params, "params", 2, [])
    if address != acting_site.address and "ADMIN" not in acting_site.permissions:
        raise CommandError("No permission for site %s" % address)
    handler = COMMAND_HANDLERS.get(cmd)
    if handler is None:
        raise CommandError("Unknown command: %s" % cmd)
    site_manager = _requireSiteManager(session)
    target_site = site_manager.sites.get(address)
    if target_site is None:
        raise CommandError("No permission for site %s" % address)
    sub_session = copy.copy(session)
    sub_session.site = _AsSiteProxy(target_site, acting_site.permissions)
    return await handler(sub_session, inner_params)


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


@command("channelJoinAllsite")
async def _cmdChannelJoinAllsite(session, params):
    _requireAdmin(session)
    channel = _param(params, "channel", 0)
    if channel not in session.channels:
        session.channels.append(channel)
    return "ok"


def formatSiteInfo(site, site_manager=None, user=None):
    """`settings`/`size_limit`/`next_size_limit`/`bad_files`/
    `started_task_num`/`tasks` were added after a real crash found live:
    the actual production wrapper.js (unmodified, from src/Ui/media/)
    unconditionally reads site_info.settings.size and site_info.size_limit
    on every single page load (Wrapper.reloadSiteInfo()) -- without them,
    every page load threw a TypeError before the wrapper could finish
    initializing. This stack has no site.settings dict (see
    P2P.SiteManager's own docstring on why) or per-site size-limit
    tracking, so `settings` here is a minimal, honest stand-in: `size` is
    computed for real from content.json's own file listing (not cached/
    stale), `size_limit`/`next_size_limit` fall back to content.json's own
    declared limit or the original's own 10MB default -- there's no
    admin-configurable override system behind them yet. `bad_files`/
    `started_task_num`/`tasks` are always 0 -- this stack doesn't track
    per-site bad-file lists or expose a per-site WorkerManager instance
    the way the original's Site.worker_manager does.

    Legacy UI state fields such as ``settings.own`` and ``settings.modified``
    are included even when no account is available. ZeroMe/ZeroTalk read
    these fields while refreshing their page state, and an omitted field is
    exposed to the browser as ``undefined``.

    When a user is supplied, the legacy identity fields are included too:
    auth_address, cert_user_id, and privatekey (a boolean indicating that
    the server has the site's signing key). The private key itself is never
    sent to the browser; siteSign resolves it server-side.
    """
    raw_content = site.content_manager.contents.get("content.json")
    size = 0
    size_optional = 0
    if raw_content:
        size += sum(f.get("size", 0) for f in raw_content.get("files", {}).values())
        size_optional = sum(f.get("size", 0) for f in raw_content.get("files_optional", {}).values())
        size += size_optional

    content = dict(raw_content) if raw_content else {}
    if content:
        content["files"] = len(content.get("files", {}))
        content["files_optional"] = len(content.get("files_optional", {}))
        content["includes"] = len(content.get("includes", {}))
        content.pop("sign", None)
        content.pop("signs", None)
        content.pop("signers_sign", None)

    size_limit_mb = (raw_content or {}).get("size_limit", 10)
    if site_manager is not None:
        override = site_manager.getSizeLimitOverride(site.address)
        if override is not None:
            size_limit_mb = override

    modified_files_notification = (
        site_manager.getSiteSetting(site.address, "modified_files_notification", True)
        if site_manager is not None else True
    )
    is_own = site_manager.isOwn(site.address) if site_manager is not None else False
    info = {
        "address": site.address,
        "address_hash": site.address_sha1.hex(),
        "permissions": list(site.permissions),
        "serving": site.isServing(),
        "peers": len(site.peers),
        "content": content,
        "settings": {
            "size": size,
            "size_optional": size_optional,
            "own": is_own,
            "modified": (raw_content or {}).get("modified", 0),
            "permissions": list(site.permissions),
            "modified_files_notification": modified_files_notification,
        },
        "size_limit": size_limit_mb,
        "next_size_limit": size_limit_mb,
        "bad_files": 0,
        "started_task_num": 0,
        "tasks": 0,
    }
    if user is not None:
        site_data = user.getSiteData(site.address)
        follow = site_data.get("follow")
        info.update({
            "auth_address": site_data.get("auth_address"),
            "cert_user_id": user.getCertUserId(site.address),
            "privatekey": bool(site_data.get("privatekey")),
            "feed_follow_num": len(follow) if follow is not None else None,
        })
    return info


@command("siteInfo")
async def _cmdSiteInfo(session, params):
    site = _requireSite(session)
    # Standalone/test UiServers may intentionally omit account storage; the
    # production App always supplies UserManager and gets the full identity
    # payload below.
    user_manager = getattr(session.app, "user_manager", None)
    user = await _requireUser(session) if user_manager is not None else None
    info = formatSiteInfo(site, getattr(session.app, "site_manager", None), user)
    # User identity/auth-address generation is lazy. Persist it here so a
    # first visit to ZeroTalk/ZeroMe survives a restart like legacy ZeroNet.
    if user is not None and user._dirty:
        await user.save()
    return info


@command("fileGet")
async def _cmdFileGet(session, params):
    inner_path = _param(params, "inner_path", 0)
    site, inner_path = _resolveCrossSitePath(session, inner_path)
    fmt = _param(params, "format", 1, "text")
    if not site.storage.isFile(inner_path):
        return None
    body = await site.storage.read(inner_path, "rb")
    if fmt == "base64":
        return base64.b64encode(body).decode()
    return body.decode()


@command("fileNeed")
async def _cmdFileNeed(session, params):
    """Fetch a missing regular file or Bigfile through the native scheduler.

    Goes through site.needFile() rather than constructing a Scheduler
    directly -- see Site.py's own docstring on why: that's now the real
    plugin-overridable hook point (e.g. ContentFilter's mute check), and
    the fresh-Scheduler-per-call behavior is unchanged either way."""
    site = _requireSite(session)
    inner_path = _param(params, "inner_path", 0)
    timeout = float(_param(params, "timeout", 1, 60))
    file_server = getattr(session.app, "file_server", None)
    if file_server is None:
        raise CommandError("This server has no file server configured")

    from multiaddr import Multiaddr
    from ..Peer import Peer

    records = site.getConnectablePeers(need_num=5)
    peers = []
    for record in records:
        if record.ip and record.port:
            try:
                file_server.host.get_peerstore().add_addrs(
                    record.peer_id, [Multiaddr("/ip4/%s/tcp/%s" % (record.ip, record.port))], 3600,
                )
            except Exception:
                pass
        peers.append(Peer(record.peer_id, file_server.host, file_server.connection_policy))
    data = await site.needFile(inner_path, peers, timeout=timeout)
    session.app.broadcast("siteChanged", site, {"event": "file_done"})
    return {"inner_path": inner_path, "size": len(data), "downloaded": True}


@command("fileList")
async def _cmdFileList(session, params):
    inner_path = _param(params, "inner_path", 0, "")
    site, inner_path = _resolveCrossSitePath(session, inner_path)
    return await site.storage.walk(inner_path)


@command("dirList")
async def _cmdDirList(session, params):
    inner_path = _param(params, "inner_path", 0, "")
    site, inner_path = _resolveCrossSitePath(session, inner_path)
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


@command("fileQuery")
async def _cmdFileQuery(session, params):
    """Found live: ZeroName's own ZeroName.coffee calls fileQuery(["data/names.json",
    ""]) on every page load to list registered domains, unconditionally --
    without this command, res[0] in its updateDomains() callback was
    undefined, and Object.keys(undefined) threw before the page could
    render (a blank page under a red banner, no error visible to the
    user). Reuses util.QueryJson.query verbatim, same as the original's
    actionFileQuery -- glob-walks dir_inner_path for JSON files matching
    its last path segment and returns each match's queried rows."""
    site = _requireSite(session)
    dir_inner_path = _param(params, "dir_inner_path", 0)
    query = _param(params, "query", 1, "") or ""
    dir_path = str(site.storage.getPath(dir_inner_path))
    return list(QueryJson.query(dir_path, query))


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

    session.app.broadcast("siteChanged", site, {"event": "file_done"})
    return "ok"


# -- Certificates --

@command("certAdd")
async def _cmdCertAdd(session, params):
    site = _requireSite(session)
    user = await _requireUser(session)
    if isinstance(params, dict):
        auth_address = params.get("auth_address") or user.getAuthAddress(site.address)
        domain = params.get("domain")
        auth_type = params.get("auth_type")
        auth_user_name = params.get("auth_user_name")
        cert_sign = params.get("cert_sign") or params.get("cert")
    elif isinstance(params, list) and len(params) >= 5:
        # Compatibility with the internal form used by older native callers.
        auth_address, domain, auth_type, auth_user_name, cert_sign = params[:5]
    else:
        # ZeroFrame's documented/public form omits auth_address; the current
        # site's local auth identity is the certificate subject.
        auth_address = user.getAuthAddress(site.address)
        domain = _param(params, "domain", 0)
        auth_type = _param(params, "auth_type", 1)
        auth_user_name = _param(params, "auth_user_name", 2)
        cert_sign = _param(params, "cert_sign", 3) or _param(params, "cert", 3)
    try:
        result = await user.addCert(auth_address, domain, auth_type, auth_user_name, cert_sign)
    except Exception as err:
        return {"error": str(err)}
    if result is True:
        user.setCert(site.address, domain)
        await user.save()
        info = formatSiteInfo(site, getattr(session.app, "site_manager", None), user)
        info["cert_changed"] = domain
        session.pushAfterResponse("setSiteInfo", info)
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
    await user.save()
    info = formatSiteInfo(site, getattr(session.app, "site_manager", None), user)
    info["cert_changed"] = domain
    session.pushAfterResponse("setSiteInfo", info)
    return "ok"


@command("certIssueLocal")
async def _cmdCertIssueLocal(session, params):
    """Issue a certificate from this node's local provider identity.

    This is intentionally separate from certAdd: certAdd imports a provider
    certificate, while this command creates one locally. The returned
    provider_address must be added to a site's cert_signers policy before
    content signed with the certificate will be accepted there.
    """
    site = _requireSite(session)
    user = await _requireUser(session)
    domain = _param(params, "domain", 0)
    auth_type = _param(params, "auth_type", 1, "web")
    auth_user_name = _param(params, "auth_user_name", 2)
    if not domain or not auth_user_name:
        return {"error": "domain and auth_user_name are required"}
    try:
        cert = await user.issueCert(site.address, domain, auth_type, auth_user_name)
    except Exception as err:
        return {"error": str(err)}
    info = formatSiteInfo(site, getattr(session.app, "site_manager", None), user)
    info["cert_changed"] = domain
    session.pushAfterResponse("setSiteInfo", info)
    return cert


@command("providerCreate")
async def _cmdProviderCreate(session, params):
    """Create a local ZeroNet identity-provider site and announce its domain."""
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    user = await _requireUser(session)
    domain = (_param(params, "domain", 0) or "").strip().lower()
    if not domain or not domain.endswith(".bit"):
        return {"error": "provider domain must end with .bit"}
    if not site_manager.loaded:
        await site_manager.load()

    provider_privatekey = CryptBitcoin.newPrivatekey()
    provider_address = CryptBitcoin.privatekeyToAddress(provider_privatekey)
    add_site = getattr(session.app, "on_missing_site", None)
    site = add_site(provider_address, own=True) if add_site is not None else site_manager.add(provider_address, own=True)
    if not site:
        return {"error": "Unable to create provider site"}
    site.permissions = ["ADMIN"]
    await site.storage.write("index.html", ("""<!doctype html>
<meta charset="utf-8">
<title>%s identity provider</title>
<h1>%s</h1>
<p>This ZeroNet site is an identity provider for <b>%s</b>.</p>
<p>Provider address: <code>%s</code></p>
<p>Registration and certificate issuance are handled by the local ZeroNet provider API.</p>
""" % (html.escape(domain), html.escape(domain), html.escape(domain), provider_address)).encode("utf-8"))
    await site.storage.write("provider.json", ("%s\n" % (
        '{"domain": "%s", "provider_address": "%s", "protocol": "zeronet-identity-v1"}'
        % (domain, provider_address)
    )).encode("utf-8"))
    await site.content_manager.sign(provider_privatekey, extend={
        "title": "%s identity provider" % domain,
        "description": "Local ZeroNet identity provider for %s" % domain,
        "provider_domain": domain,
        "provider_address": provider_address,
    })

    user.settings["local_provider_privatekey"] = provider_privatekey
    user.settings["local_provider_address"] = provider_address
    await user.save()
    await site_manager.save()

    dht = getattr(session.app, "dht_discovery", None)
    announced = False
    if dht is not None:
        await dht.announce_provider(domain)
        announced = True
    return {
        "domain": domain,
        "address": provider_address,
        "provider_address": provider_address,
        "privatekey": provider_privatekey,
        "announced": announced,
    }


@command("certProviderIssue")
async def _cmdCertProviderIssue(session, params):
    """Sign a certificate for a requester from an owned provider site."""
    _requireAdmin(session)
    user = await _requireUser(session)
    auth_address = _param(params, "auth_address", 0)
    domain = _param(params, "domain", 1)
    auth_type = _param(params, "auth_type", 2, "web")
    auth_user_name = _param(params, "auth_user_name", 3)
    if not auth_address or not domain or not auth_user_name:
        return {"error": "auth_address, domain and auth_user_name are required"}
    try:
        return await user.issueCertForAuth(auth_address, domain, auth_type, auth_user_name)
    except Exception as err:
        return {"error": str(err)}


@command("certProviderAnnounce")
async def _cmdCertProviderAnnounce(session, params):
    """Issue a local certificate and announce its opaque identity key."""
    dht = getattr(session.app, "dht_discovery", None)
    if dht is None:
        return {"error": "ZeroNet DHT is disabled"}
    site = _requireSite(session)
    user = await _requireUser(session)
    domain = _param(params, "domain", 0)
    auth_type = _param(params, "auth_type", 1, "web")
    auth_user_name = _param(params, "auth_user_name", 2)
    if not domain or not auth_user_name:
        return {"error": "domain and auth_user_name are required"}
    try:
        cert = await user.issueCert(site.address, domain, auth_type, auth_user_name)
        key = await dht.announce_identity(domain, auth_type, auth_user_name)
    except Exception as err:
        return {"error": str(err)}
    cert["identity_key"] = key.hex()
    cert["announced"] = True
    return cert


@command("certProviderFind")
async def _cmdCertProviderFind(session, params):
    """Discover providers for an identity without exposing its plaintext key."""
    dht = getattr(session.app, "dht_discovery", None)
    if dht is None:
        return {"error": "ZeroNet DHT is disabled"}
    domain = _param(params, "domain", 0)
    auth_type = _param(params, "auth_type", 1, "web")
    auth_user_name = _param(params, "auth_user_name", 2)
    if not domain or not auth_user_name:
        return {"error": "domain and auth_user_name are required"}
    try:
        peers = await dht.find_identity_providers(domain, auth_type, auth_user_name)
    except Exception as err:
        return {"error": str(err)}
    return {"peers": [peer.peer_id.to_base58() for peer in peers]}


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


@command("certSelect")
async def _cmdCertSelect(session, params):
    """Show the existing wrapper's account selector for ZeroMe/ZeroTalk.

    The legacy implementation rendered a notification and injected a click
    handler. Native websocket pushes provide the same two primitives, while
    certSet remains the authoritative, admin-gated mutation.
    """
    site = _requireSite(session)
    user = await _requireUser(session)
    accepted_domains = _param(params, "accepted_domains", 0, []) or []
    accepted_pattern = _param(params, "accepted_pattern", 2)
    accept_any = _param(params, "accept_any", 1, False)
    if not accepted_domains and not accepted_pattern:
        accept_any = True

    site_data = user.getSiteData(site.address)
    auth_address = site_data.get("auth_address")
    active = site_data.get("cert", "")
    local_identity = site_data.get("auth_address")
    local_allowed = not accepted_domains and not accepted_pattern
    accounts = [("", "Use local identity (%s)" % local_identity, active == "", local_allowed)]
    for domain, cert in user.certs.items():
        allowed = accept_any or domain in accepted_domains or (
            accepted_pattern and SafeRe.match(accepted_pattern, domain)
        )
        if not allowed:
            continue
        if cert.get("auth_address") != auth_address:
            continue
        accounts.append((domain, "%s@%s" % (cert.get("auth_user_name", ""), domain), domain == active, True))

    body = "<span style='padding-bottom:5px;display:inline-block'>Select account you want to use in this site:</span>"
    for domain, title, selected, selectable in accounts:
        css = " active" if selected else ""
        css += " cert" if selectable else " disabled"
        body += (
            "<a href='#Select+account' data-domain='%s' class='select select-close%s'>"
            "<b>%s</b>%s</a>"
        ) % (
            html.escape(domain, quote=True), css, html.escape(title),
            " <small>(currently selected)</small>" if selected else "",
        )

    # A certificate is issued by a trusted provider; it cannot be generated
    # locally without breaking the site's signer trust model. Match the
    # legacy selector's first-use path by linking to each provider's
    # registration site when an accepted domain is not present yet.
    cert_signers = {}
    for content in site.content_manager.contents.values():
        user_contents = content.get("user_contents", {})
        cert_signers.update(user_contents.get("cert_signers", {}) or {})
        if cert_signers:
            break
    for domain in accepted_domains:
        if domain in user.certs:
            continue
        if domain.endswith(".bit") and domain not in cert_signers:
            provider_path = domain
        elif domain in cert_signers:
            provider = cert_signers[domain]
            provider_path = provider[0] if isinstance(provider, (list, tuple)) else provider
        else:
            continue
        body += (
            "<a href='/%s' target='_top' class='select cert-register'>"
            "<b>Register %s</b><small> (create an account)</small></a>"
            % (html.escape(str(provider_path), quote=True), html.escape(domain))
        )

    session.push("notification", ["ask", body])
    session.push("injectScript", """
      (function() {
        document.querySelectorAll('.notification .select.cert').forEach(function(item) {
          item.addEventListener('click', function(event) {
            event.preventDefault();
            var domain = item.getAttribute('data-domain') || '';
            zeroframe.cmd('certSet', {domain: domain}, function() {
              var notification = item.closest('.notification');
              if (notification) notification.remove();
            });
          });
        });
      })();
    """)
    return [{"domain": domain, "title": title, "selected": selected} for domain, title, selected, _ in accounts]


# -- Site management (admin, via SiteManager) --

@command("siteAdd")
async def _cmdSiteAdd(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0)
    if address in site_manager.sites:
        return {"error": "Site already added"}
    add_site = getattr(session.app, "on_missing_site", None)
    site = add_site(address) if add_site is not None else site_manager.add(address)
    if not site:
        return {"error": "Invalid address"}
    # App.addSite() wires the site into FileServer and creates its announcer.
    # Trigger the original's announce-on-add behavior without delaying the
    # command response; the connection nursery owns this task's lifetime.
    announce_once = getattr(session.app, "_announceOnce", None)
    if announce_once is not None and session.nursery is not None:
        session.nursery.start_soon(announce_once, site.address)
    return "ok"


@command("siteCreate")
async def _cmdSiteCreate(session, params):
    """Create the same minimal, signed site as the native CLI action."""
    _requireAdmin(session)
    use_master_seed = _param(params, "use_master_seed", 0, True)
    if use_master_seed:
        user = await _requireUser(session)
        address, address_index, site_data = await user.getNewSiteData()
        privatekey = site_data["privatekey"]
    else:
        privatekey = CryptBitcoin.newPrivatekey()
        address = CryptBitcoin.privatekeyToAddress(privatekey)
        address_index = None
    add_site = getattr(session.app, "addSite", None)
    if add_site is None:
        site_manager = _requireSiteManager(session)
        site = site_manager.add(address, own=True)
    else:
        site = add_site(address, own=True)
    if site is None:
        raise CommandError("Unable to create site")
    await site.storage.write("index.html", ("Hello %s!" % address).encode("utf8"))
    extend = {"postmessage_nonce_security": True}
    if address_index is not None:
        extend["address_index"] = address_index
    await site.content_manager.sign(privatekey, extend=extend)
    await _requireSiteManager(session).save()
    return {"address": address}


@command("siteClone")
async def _cmdSiteClone(session, params):
    """Real, but root-content.json-only port of the original's Site.clone()
    -- matches ContentManager.sign()'s own established root-vs-non-root
    split (see that module's docstring): copies every file the source
    site's root content.json actually lists (skipping any optional file
    that isn't downloaded yet) under root_inner_path, seeds a fresh
    content.json from the source's own header fields, and lets sign()'s
    hashFiles() recompute the real files/files_optional hashes from
    what's actually on disk -- same "narrow but real" discipline as
    siteCreate. This is what both ZeroHello's per-site "Clone" button
    (no root_inner_path/target_address -- a plain fresh copy) and its
    dashboard "Create new site" button (root_inner_path="template-new",
    cloning off ZeroHello's own bundled template) actually send.

    Upgrading an existing cloned site in place (target_address given --
    ZeroHello's "Upgrade" button on an outdated clone) copies the newer
    files over that site's own storage and re-signs with ITS OWN stored
    privatekey, without touching its existing content.json header
    (title/domain/etc. stay the site owner's, only files change) --
    matches the original's overwrite=False clone() semantics there.

    Doesn't touch included (non-root) content.json files or the
    original's "-default" template-file convention -- neither exists
    anywhere in this stack yet, and nothing this stack serves depends on
    them (this stack's ZeroHello template lives entirely under a single
    root_inner_path, no nested content.json of its own). Also skips the
    original's bad_files-before-cloning guard: bad_files isn't tracked
    in this stack (see ContentManager's own module docstring)."""
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0)
    root_inner_path = _param(params, "root_inner_path", 1, "") or ""
    target_address = _param(params, "target_address", 2)

    source_site = site_manager.sites.get(address)
    if source_site is None:
        raise CommandError("Unknown site: %s" % address)

    user = await _requireUser(session)
    address_index = None

    if target_address:
        target_site = site_manager.sites.get(target_address)
        if target_site is None:
            raise CommandError("Unknown site: %s" % target_address)
        privatekey = user.getSiteData(target_address).get("privatekey")
        if not privatekey:
            raise CommandError("No privatekey stored for site %s" % target_address)
        is_new = False
    else:
        new_address, address_index, site_data = await user.getNewSiteData()
        privatekey = site_data["privatekey"]
        add_site = getattr(session.app, "addSite", None)
        target_site = add_site(new_address, own=True) if add_site else site_manager.add(new_address, own=True)
        if target_site is None:
            raise CommandError("Unable to create site")
        target_address = new_address
        is_new = True

    root = Path(root_inner_path) if root_inner_path else None
    raw_content = source_site.content_manager.contents.get("content.json") or {}

    if is_new and not target_site.storage.isFile("content.json"):
        header = dict(raw_content)
        for key in ("files", "files_optional", "signs", "sign", "signers_sign", "domain"):
            header.pop(key, None)
        header["title"] = "my" + str(header.get("title", target_address))
        header.setdefault("description", "")
        header["cloned_from"] = address
        header["clone_root"] = root_inner_path
        if address_index is not None:
            header["address_index"] = address_index
        await target_site.storage.writeJson("content.json", header)
        await target_site.content_manager.loadContent("content.json")

    for relative_path in raw_content.get("files", {}):
        file_path = Path(relative_path)
        if root is not None:
            if root != file_path and root not in file_path.parents:
                continue
            dest_relative = str(file_path.relative_to(root))
        else:
            dest_relative = relative_path
        if dest_relative == "content.json" or not source_site.storage.isFile(relative_path):
            continue
        data = await source_site.storage.read(relative_path)
        await target_site.storage.write(dest_relative, data)

    await target_site.content_manager.sign(privatekey)
    await site_manager.save()
    return {"address": target_address}


@command("siteDelete")
async def _cmdSiteDelete(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0)
    if address not in site_manager.sites:
        return {"error": "Unknown site: %s" % address}
    delete_site = getattr(session.app, "deleteSite", None)
    if delete_site is not None:
        delete_site(address)
    else:
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
    session.app.broadcast("siteChanged", site, {"event": "paused"})
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
    session.app.broadcast("siteChanged", site, {"event": "resumed"})
    return "Resumed"


@command("siteUpdate")
async def _cmdSiteUpdate(session, params):
    """Refresh locally available content metadata.

    Native download scheduling is not yet a WorkerManager feature, but the
    existing dashboard button must still re-enable a paused site and reload
    content.json when it is already on disk.
    """
    site_manager = _requireSiteManager(session)
    address = _param(params, "address", 0, _requireSite(session).address)
    site = site_manager.sites.get(address)
    if site is None:
        raise CommandError("Unknown site: %s" % address)
    if site is not session.site:
        _requireAdmin(session)
    site.serving = True
    if site.storage.isFile("content.json"):
        await site.content_manager.loadContent()
    session.app.broadcast("siteChanged", site, {"event": "updated"})
    return "Updated"


@command("siteUpdateAll")
async def _cmdSiteUpdateAll(session, params):
    """Server-side loop version of ZeroHello's own "Update all sites" menu
    item, which does this same thing client-side (iterating its own
    Page.site_list.sites and calling siteUpdate per address). A single
    command is simpler for a caller that doesn't already hold a full site
    list client-side (the new left-drawer menu doesn't)."""
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    updated = []
    for site in site_manager.sites.values():
        if not site.isServing():
            continue
        if site.storage.isFile("content.json"):
            await site.content_manager.loadContent()
        session.app.broadcast("siteChanged", site, {"event": "updated"})
        updated.append(site.address)
    return {"updated": updated}


@command("siteReload")
async def _cmdSiteReload(session, params):
    site = _requireSite(session)
    inner_path = _param(params, "inner_path", 0, "content.json")
    if not site.storage.isFile(inner_path):
        raise CommandError("Content file not found: %s" % inner_path)
    await site.content_manager.loadContent(inner_path)
    return "ok"


@command("siteFavourite")
async def _cmdSiteFavourite(session, params):
    _requireAdmin(session)
    user = await _requireUser(session)
    dashboard = getattr(session.app, "homepage", None)
    if not dashboard:
        raise CommandError("No dashboard site configured")
    settings = user.getSiteData(dashboard).get("settings", {})
    settings.setdefault("favorite_sites", {})[_param(params, "address", 0)] = True
    user.setSiteSettings(dashboard, settings)
    await user.save()
    return "Added to favourites"


@command("siteUnfavourite")
async def _cmdSiteUnfavourite(session, params):
    _requireAdmin(session)
    user = await _requireUser(session)
    dashboard = getattr(session.app, "homepage", None)
    if not dashboard:
        raise CommandError("No dashboard site configured")
    settings = user.getSiteData(dashboard).get("settings", {})
    settings.setdefault("favorite_sites", {}).pop(_param(params, "address", 0), None)
    user.setSiteSettings(dashboard, settings)
    await user.save()
    return "Removed from favourites"


@command("siteList")
async def _cmdSiteList(session, params):
    _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    return [formatSiteInfo(site, site_manager) for site in site_manager.sites.values()]


@command("siteSetLimit")
async def _cmdSiteSetLimit(session, params):
    site = _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    size_limit = float(_param(params, "size_limit", 0))
    await site_manager.setSizeLimitOverride(site.address, size_limit)
    return "ok"


@command("siteSetAutodownloadBigfileLimit")
async def _cmdSiteSetAutodownloadBigfileLimit(session, params):
    site = _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    limit = float(_param(params, "limit", 0))
    if limit < 0:
        return {"error": "limit must be non-negative"}
    await site_manager.setSiteSetting(site.address, "autodownload_bigfile_size_limit", limit)
    return "ok"


@command("siteSetOwned")
async def _cmdSiteSetOwned(session, params):
    site = _requireAdmin(session)
    site_manager = _requireSiteManager(session)
    owned = bool(_param(params, "owned", 0))
    await site_manager.setOwn(site.address, owned)
    return "ok"


@command("siteSetSettingsValue")
async def _cmdSiteSetSettingsValue(session, params):
    site = _requireSite(session)
    key = _param(params, "key", 0)
    value = _param(params, "value", 1)
    if key != "modified_files_notification":
        raise CommandError("Unsupported site setting: %s" % key)
    site_manager = _requireSiteManager(session)
    await site_manager.setSiteSetting(site.address, key, value)
    return "ok"


# -- Permissions --

_PERMISSION_DETAILS = {
    "ADMIN": "Allow this site to administrate your 0net node (Make sure you trust site developer before accepting!)",
    "NOSANDBOX": "Modify your client's configuration and access all site (Dangerous!)",
    "PushNotification": "Send notifications",
}


async def _saveSitePermissions(session):
    """permissionAdd/Remove mutate site.permissions in place; without this,
    a granted ADMIN permission only lived for the rest of the current
    process and every restart re-prompted the "Grant" dialog -- see
    SiteManager.save()'s own docstring. Best-effort: no site_manager (e.g.
    a bare UiServer built without one, as most tests use) just skips
    persisting, same graceful degradation sitePublish already uses for a
    missing file_server."""
    site_manager = getattr(session.app, "site_manager", None)
    if site_manager is not None:
        await site_manager.save()


@command("permissionAdd")
async def _cmdPermissionAdd(session, params):
    """Deliberately NOT _requireAdmin()-gated, matching the original's own
    actionPermissionAdd (no @flag.admin there, unlike Remove/Details right
    below it): this is the command the "Grant" button in the wrapper's own
    permission-request dialog calls, for a site that by definition doesn't
    have the permission yet -- gating it on already having ADMIN would
    make granting ADMIN for the first time permanently impossible."""
    site = _requireSite(session)
    permission = _param(params, "permission", 0)
    if permission not in site.permissions:
        site.permissions.append(permission)
        await _saveSitePermissions(session)
    return "ok"


@command("corsPermission")
async def _cmdCorsPermission(session, params):
    """Port of plugins/Cors/CorsPlugin.py's actionCorsPermission/
    cbCorsPermission -- real production site JS calls this exact command
    name with a list of addresses (Page.cmd("corsPermission", [address],
    cb), found live in an already-downloaded site's own bundled all.js)
    to request read access to another site via _resolveCorsPath() above.
    Grants directly, no confirm-dialog round trip -- see
    _resolveCorsPath()'s own docstring for why. Auto-adds a site that
    isn't loaded yet (SiteManager.need()), matching the original's own
    gevent.spawn(site_manager.need, address) -- awaited here rather than
    fired-and-forgotten, since this stack has no equivalent background-
    spawn convention for a plain command handler."""
    site = _requireSite(session)
    addresses = _param(params, "address", 0)
    if not isinstance(addresses, list):
        addresses = [addresses]
    site_manager = _requireSiteManager(session)
    granted = False
    for address in addresses:
        permission = "Cors:%s" % address
        if permission in site.permissions:
            continue
        await site_manager.need(address)
        site.permissions.append(permission)
        granted = True
    if granted:
        await _saveSitePermissions(session)
    return "ok"


@command("permissionRemove")
async def _cmdPermissionRemove(session, params):
    site = _requireAdmin(session)
    permission = _param(params, "permission", 0)
    if permission in site.permissions:
        site.permissions.remove(permission)
        await _saveSitePermissions(session)
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


@command("userShowMasterSeed")
async def _cmdUserShowMasterSeed(session, params):
    """Port of the Multiuser plugin's actionUserShowMasterSeed(): reveal the
    connected user's master seed via the same notification channel
    certSelect already uses. Not multiuser-specific -- a single-user
    install has exactly as much need to back up its one identity's seed,
    so this is available in both modes (unlike userSet/userSelectForm/
    userLogin below, which are genuinely about switching BETWEEN accounts
    and only make sense once UserManager.multiuser is on)."""
    _requireAdmin(session)
    user = await _requireUser(session)
    message = (
        "<b style='padding-top:5px;display:inline-block'>Your unique private key:</b>"
        "<div style='font-size:84%; background-color:#FFF0AD; padding:5px 8px; margin:9px 0px'>"
        + html.escape(user.master_seed) +
        "</div><small>(Save it, you can access your account using this information)</small>"
    )
    session.push("notification", ["info", message])
    return "ok"


@command("userLogout")
async def _cmdUserLogout(session, params):
    """Port of actionUserLogout(): clears the master_address cookie client-
    side and, in multiuser mode, drops the user from UserManager so the
    next page load mints (or the next userLogin/userSet picks) a different
    identity. In single-user mode UserManager.get() always returns the
    first loaded user regardless of cookie, so deleting it here would just
    make _requireUser() silently recreate an empty one on the next command
    -- clearing the cookie is still meaningful (drives the client back to
    a logged-out UI state) even though there's nothing to delete."""
    _requireAdmin(session)
    user_manager = getattr(session.app, "user_manager", None)
    if user_manager is None:
        raise CommandError("This server has no user manager configured")
    user = await _requireUser(session)
    message = (
        "<b>You have been logged out.</b> "
        "<a href='#Login' class='button' id='button_notification'>Login to another account</a>"
    )
    session.push("notification", ["done", message, 1000000])
    session.push("injectScript", """
      document.cookie = 'master_address=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/';
      var button = document.getElementById('button_notification');
      if (button) button.addEventListener('click', function() { zeroframe.cmd('userLoginForm', []); });
    """)
    if user_manager.multiuser and user.master_address in user_manager.users:
        del user_manager.users[user.master_address]
    return "ok"


@command("userSelectForm")
async def _cmdUserSelectForm(session, params):
    """Port of actionUserSelectForm(): list every account this server
    already knows (from users.json) so the connected browser can switch to
    one of them. The original drives this via a server-side response
    continuation (self.cmd(..., callback)); this stack's session.push() is
    fire-and-forget (see certSelect's own docstring above), so the click
    handler calls userSet directly client-side instead of round-tripping
    through a server-held callback -- same restructuring certSelect and
    corsPermission already used for the same reason."""
    _requireAdmin(session)
    user_manager = getattr(session.app, "user_manager", None)
    if user_manager is None or not user_manager.multiuser:
        raise CommandError("Only allowed in multiuser mode")
    user = await _requireUser(session)
    users = await user_manager.list()

    body = "<span style='padding-bottom:5px;display:inline-block'>Change account:</span>"
    for master_address, other in users.items():
        is_active = master_address == user.master_address
        if other.certs:
            first_cert = next(iter(other.certs.keys()))
            title = "%s@%s" % (other.certs[first_cert].get("auth_user_name", ""), first_cert)
        else:
            title = master_address
            if len(other.sites) < 2 and not is_active:
                continue  # Skip ad-hoc, barely-used accounts -- same filter as the original
        css = " active" if is_active else ""
        body += "<a href='#Select+user' data-master-address='%s' class='select select-close user%s'>%s</a>" % (
            html.escape(master_address, quote=True), css, html.escape(title),
        )

    session.push("notification", ["ask", body])
    session.push("injectScript", """
      (function() {
        document.querySelectorAll('.notification .select.user').forEach(function(item) {
          item.addEventListener('click', function(event) {
            event.preventDefault();
            var masterAddress = item.getAttribute('data-master-address') || '';
            zeroframe.cmd('userSet', {master_address: masterAddress}, function() {});
          });
        });
      })();
    """)
    return "ok"


@command("userSet")
async def _cmdUserSet(session, params):
    """Port of actionUserSet(): switch this browser's cookie to a DIFFERENT
    account this server already knows, then reload. Admin-gated and
    multiuser-only, same reasoning as userSelectForm above."""
    _requireAdmin(session)
    user_manager = getattr(session.app, "user_manager", None)
    if user_manager is None or not user_manager.multiuser:
        raise CommandError("Only allowed in multiuser mode")
    master_address = _param(params, "master_address", 0)
    user = await user_manager.get(master_address)
    if user is None:
        raise CommandError("No user found")
    session.push("notification", ["done", "Successful login, reloading page..."])
    session.push("injectScript", (
        "document.cookie = 'master_address=%s;path=/;max-age=2592000;';"
        "zeroframe.cmd('wrapperReload', ['login=done']);"
    ) % user.master_address)
    return "ok"


@command("userLoginForm")
async def _cmdUserLoginForm(session, params):
    """Port of actionUserLoginForm(): prompt for a master seed to log into
    an account this server may never have seen before. The original shows
    its prompt via a server-continuation self.cmd("prompt", ..., callback);
    same fire-and-forget constraint as userSelectForm above, so this uses a
    plain client-side window.prompt() and hands the typed seed to the new
    userLogin command instead. Deliberately NOT admin-gated, matching the
    original -- logging in is how a connection acquires an identity in the
    first place, so it can't require the permission that identity grants."""
    session.push("injectScript", """
      (function() {
        var seed = window.prompt('Login\\nYour private key:');
        if (seed) zeroframe.cmd('userLogin', {master_seed: seed}, function() {});
      })();
    """)
    return "ok"


@command("userLogin")
async def _cmdUserLogin(session, params):
    """Port of responseUserLogin(): resolve (or, in multiuser mode, create)
    the account for a submitted master seed, then set the cookie and
    reload. Same access as userLoginForm -- not admin-gated."""
    user_manager = getattr(session.app, "user_manager", None)
    if user_manager is None:
        raise CommandError("This server has no user manager configured")
    master_seed = _param(params, "master_seed", 0)
    if not master_seed:
        raise CommandError("No master seed given")
    try:
        master_address = CryptBitcoin.privatekeyToAddress(master_seed)
    except Exception:
        master_address = None
    if not master_address:
        session.push("notification", ["error", "Error: Invalid master seed"])
        raise CommandError("Invalid master seed")

    user = await user_manager.get(master_address) if user_manager.multiuser else None
    if user is None:
        user = user_manager.create(master_seed=master_seed)
    session.push("notification", ["done", "Successful login, reloading page..."])
    session.push("injectScript", (
        "document.cookie = 'master_address=%s;path=/;max-age=2592000;';"
        "zeroframe.cmd('wrapperReload', ['login=done']);"
    ) % user.master_address)
    return "ok"


@command("serverShowdirectory")
async def _cmdServerShowdirectory(session, params):
    """Return a directory for the native UI to display/copy.

    The legacy command opens a local desktop file manager, which is unsafe
    and meaningless for a headless native server. Returning the validated
    path preserves the useful part of the menu action.
    """
    _requireAdmin(session)
    directory = _param(params, "directory", 0, "backup")
    inner_path = _param(params, "inner_path", 1, "")
    if directory == "backup":
        path = Path(getattr(session.app, "data_dir", config.data_dir)).resolve()
    elif directory == "log":
        path = Path(config.log_dir).resolve()
    elif directory == "site":
        site = _requireSite(session)
        path = site.storage.getPath(inner_path).resolve()
    else:
        raise CommandError("Unknown directory: %s" % directory)
    if not path.is_dir():
        raise CommandError("Not a directory")
    return {"directory": directory, "path": str(path)}


@command("serverShutdown")
async def _cmdServerShutdown(session, params):
    _requireAdmin(session)
    callback = getattr(session.app, "shutdown_callback", None)
    if callback is None:
        raise CommandError("Shutdown is not available")
    callback()
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


# -- Server / announcer info, listing modified files --

def _formatPortOpened(ip_external: bool | None) -> dict:
    """Shared by formatServerInfo() and serverPortcheck() so a manual
    recheck's response matches what the next serverInfo poll would report.
    IPv6 is always None ("Unsupported" in the real dashboard.js) -- this
    stack has no IPv6 UPnP mapping."""
    return {"ipv4": bool(ip_external) if ip_external is not None else None, "ipv6": None}


def formatServerInfo(session):
    """Deliberately narrower than the original's actionServerInfo(): still
    missing fileserver_ip/config fingerprinting (none of that exists in
    this stack yet). tor_enabled/tor_status match
    the original's own field names now that P2P.Tor.TorManager exists
    (tor_has_meek_bridges/tor_use_bridges are not ported concepts here).

    version/rev ARE included now (they weren't in the first pass) --
    the real wrapper.js's own all.js reads Page.server_info.version on
    every single page load (ZeroHello.setServerInfo, Dashboard.render),
    unconditionally, not just when the sidebar is opened, so their
    absence crashed every page load rather than degrading a sidebar
    feature. Same admin-gated fingerprinting-avoidance split as the
    original: an unprivileged site gets config.user_agent instead of the
    real version string. rev is always the same dummy integer either way
    (config.user_agent_rev), matching the original's own "some legacy
    code relies on this being an integer" comment -- not a simplification
    here, that's genuinely what the original does too.

    multiuser/master_address are now included too, matching the original
    Multiuser plugin's own formatServerInfo() override -- "multiuser": True
    whenever UserManager.multiuser is set, "master_address" additionally
    when the connection is ADMIN (so a site can't fingerprint another
    account's address just by asking). Not ported: "multiuser_admin", the
    original's distinction between the proxy operator's own local accounts
    (config.private_dir/users.json at plugin-load time) and a stranger's --
    this stack has no equivalent of the --multiuser-local operator-owned-
    accounts concept, only a flat --multiuser on/off.

    user_settings was missing entirely -- found live, clicking the real
    ZeroHello's theme menu: Head.renderMenuTheme() unconditionally reads
    Page.server_info.user_settings.use_system_theme, and with no
    user_settings key at all that's "reading a property of undefined",
    not just a missing sub-field. The original always includes this (both
    the admin and non-admin branches use self.user.settings, unlike
    version/plugins which differ by branch), so it's added unconditionally
    here too. formatServerInfo() itself stays synchronous (broadcast()
    calls it from a sync context), so this can't await UserManager.get()
    -- instead it peeks at whatever user_manager.users already has
    loaded, same "single user mode, first user wins" convention
    UserManager.get() itself uses, just without the await. Empty {} if no
    user has been created/loaded yet in this process at all, which is
    honest (there genuinely are no settings yet), not a stand-in fake."""
    site = getattr(session, "site", None)
    is_admin = bool(site is not None and "ADMIN" in site.permissions)
    user_manager = getattr(session.app, "user_manager", None)
    if user_manager is not None and user_manager.multiuser and session.master_address:
        user = user_manager.users.get(session.master_address)
    else:
        user = next(iter(user_manager.users.values()), None) if user_manager else None
    info = {
        "platform": sys.platform,
        "version": config.version if is_admin else config.user_agent,
        "rev": config.user_agent_rev,
        "plugins": list(plugin_manager.plugin_names) if is_admin else [],
        "user_settings": user.settings if user else {},
        "language": config.language or "en",
    }
    if user_manager is not None and user_manager.multiuser:
        info["multiuser"] = True
        if is_admin and user is not None:
            info["master_address"] = user.master_address
    file_server = getattr(session.app, "file_server", None)
    if file_server is not None:
        info["peer_id"] = file_server.host.peer_id.to_base58()
        info["addrs"] = [str(addr) for addr in file_server.host.get_addrs()]
        info["sites"] = len(file_server.sites)
        # ip_external/port_opened have no self-test-via-peer equivalent in
        # this stack (see App._setupUpnp() in P2P/app.py) -- a successful
        # UPnP mapping is the only real reachability signal available.
        # ip_external is a tri-state bool (App.py sets it, never this
        # function): None while UPnP setup hasn't finished yet (the real
        # dashboard.js renders that as "Checking..."), True once a mapping
        # succeeds, False once UPnP is disabled/fails/finishes without one.
        #
        # ip_external is what the real ZeroHello dashboard.js's header PORT
        # badge actually reads (Dashboard.render()); port_opened is a
        # separate {ipv4, ipv6} shape its port-badge dropdown reads
        # (handlePortClick()) -- None here renders as "Unsupported" there,
        # which is accurate: this stack has no IPv6 UPnP mapping at all.
        ip_external = getattr(session.app, "ip_external", None)
        info["ip_external"] = ip_external
        info["port_opened"] = _formatPortOpened(ip_external)
        tcp_addrs = [addr for addr in file_server.host.get_addrs() if "/ws" not in str(addr)]
        if tcp_addrs:
            info["fileserver_port"] = int(tcp_addrs[0].value_for_protocol("tcp"))
    tor_manager = getattr(session.app, "tor_manager", None)
    if tor_manager is not None:
        info["tor_enabled"] = tor_manager.enabled
        info["tor_status"] = tor_manager.status
    return info


def formatAnnouncerInfo(session, site):
    announcers = getattr(session.app, "announcers", None)
    announcer = announcers.get(site.address) if announcers else None
    stats = announcer.stats.all() if announcer else {}
    return {"address": site.address, "stats": stats}


@command("serverInfo")
async def _cmdServerInfo(session, params):
    return formatServerInfo(session)


@command("serverPortcheck")
async def _cmdServerPortcheck(session, params):
    """Real ZeroHello's "Re-check opened port" button (handlePortRecheckClick)
    calls this then unconditionally calls reloadServerInfo() -- it doesn't
    do anything with the response itself, just clears its own port_checking
    spinner flag once this resolves. Legacy actionServerPortcheck() ran
    FileServer.portCheck() (an actual external self-test) and responded
    with the resulting dict; this stack's only real reachability signal is
    UPnP (see App._setupUpnp()'s own docstring), so this re-runs that same
    best-effort mapping attempt on demand and reports its outcome in the
    same shape formatServerInfo() already uses, for parity with any site
    JS that (unlike ZeroHello) does read the direct response.

    port_recheck_callback is None when UPnP was disabled via --no-upnp --
    silently re-attempting it anyway on a manual click would override that
    choice, so this reports the current (always-False) state without
    retrying instead."""
    _requireAdmin(session)
    callback = getattr(session.app, "port_recheck_callback", None)
    if callback is not None:
        await callback()
    return _formatPortOpened(getattr(session.app, "ip_external", None))


@command("serverErrors")
async def _cmdServerErrors(session, params):
    """Was entirely missing -- ZeroHello.reloadServerErrors() calls this
    unconditionally on every page load (right after serverInfo), and an
    unrecognized command's undefined result crashed setServerErrors()
    reading .length on it. config.error_logger is a real, always-attached
    root logging.Handler (Config.py wires it up regardless of which stack
    is running -- see its own class docstring), so this is genuine
    recent-ERROR-lines data, not a stub; it just hadn't been wired to a
    command yet."""
    return config.error_logger.lines


@command("announcerInfo")
async def _cmdAnnouncerInfo(session, params):
    return formatAnnouncerInfo(session, _requireSite(session))


@command("siteListModifiedFiles")
async def _cmdSiteListModifiedFiles(session, params):
    """Narrower than the original: no site.settings["cache"]-backed
    "only recheck since last signed" shortcut (that settings dict doesn't
    exist here -- see P2P.SiteManager's own docstring on why), so this
    always walks every file content.json lists. Fine for the sizes this
    stack deals with (still capped at 100 files, same as the original)."""
    site = _requireSite(session)
    content_inner_path = _param(params, "content_inner_path", 0, "content.json")
    content = site.content_manager.contents.get(content_inner_path)
    if not content:
        return {"error": "content file not available"}

    min_mtime = content.get("modified", 0)
    content_dir = _getDirname(content_inner_path)
    inner_paths = [content_inner_path] + list(content.get("includes", {}).keys()) + list(content.get("files", {}).keys())
    if len(inner_paths) > 100:
        return {"error": "Too many files in content.json"}

    modified_files = []
    for relative_inner_path in inner_paths:
        inner_path = content_dir + relative_inner_path
        try:
            mtime = os.path.getmtime(site.storage.getPath(inner_path))
        except OSError:
            modified_files.append(inner_path)  # Listed but missing on disk -- treat as needing attention
            continue

        if mtime <= min_mtime + 1:
            continue  # Not touched since this content.json was signed

        if inner_path.endswith("content.json"):
            modified_files.append(inner_path)
        else:
            file_info = content.get("files", {}).get(relative_inner_path)
            same_size = file_info and site.storage.getSize(inner_path) == file_info.get("size")
            if not same_size:  # Cheap skip on size match -- same heuristic WorkerManager.syncSite() uses
                modified_files.append(inner_path)

    return {"modified_files": modified_files}


# -- Bigfile upload (Layer E) --

UPLOAD_NONCES: dict[str, dict] = {}


@command("bigfileUploadInit")
async def _cmdBigfileUploadInit(session, params):
    """Real port of plugins/Bigfile/BigfilePlugin.py's own
    actionBigfileUploadInit(): mints a one-time nonce for a subsequent
    raw-body upload to /ZeroNet-Internal/BigfileUpload (see UiServer.py's
    own _handleBigfileUpload(), where the actual bytes/hashing/
    content.json update happens) -- this command only validates
    permission and reserves the nonce, matching the original's own split
    between "who's allowed to start an upload" (a websocket command, real
    session/user context) and "receive the actual bytes" (a plain HTTP
    POST with no session at all -- the nonce is what proves the POST is
    legitimate, not a fresh permission check on the POST itself).

    Only the "xhr" protocol is ported -- one raw-body POST endpoint, not
    the original's alternate WebSocket-streaming upload path
    (BigfileUploadWebsocket). Both exist in the original purely as two
    delivery mechanisms for identical upload logic; XHR is the simpler,
    universally-supported one, and this repo bundles no client-side asset
    that specifically needs the WebSocket variant."""
    site = _requireSite(session)
    inner_path = str(_param(params, "inner_path", 0)).strip("/")
    size = int(_param(params, "size", 1, 0))
    protocol = _param(params, "protocol", 2, "xhr")
    if protocol != "xhr":
        return {"error": "Unknown protocol"}

    user = await _requireUser(session)
    site_manager = _requireSiteManager(session)
    is_own = site_manager.isOwn(site.address)
    valid_signers = site.content_manager.getValidSigners(inner_path)
    auth_address = user.getAuthAddress(site.address)
    if not is_own and auth_address not in valid_signers:
        return {"error": "Forbidden, you can only modify your own files"}

    from ..Bigfile import DEFAULT_PIECE_SIZE

    nonce = CryptHash.random()
    piece_size = DEFAULT_PIECE_SIZE
    piecemap_inner_path = inner_path + ".piecemap.msgpack"
    file_info = site.content_manager.getFileInfo(inner_path, new_file=True)
    content_inner_path = file_info["content_inner_path"] if file_info else "content.json"
    content_inner_path_dir = _getDirname(content_inner_path)
    file_relative_path = inner_path[len(content_inner_path_dir):]

    UPLOAD_NONCES[nonce] = {
        "site": site,
        "inner_path": inner_path,
        "size": size,
        "piece_size": piece_size,
        "piecemap_inner_path": piecemap_inner_path,
        "content_inner_path": content_inner_path,
        "file_relative_path": file_relative_path,
        "piecemap_relative_path": piecemap_inner_path[len(content_inner_path_dir):],
    }
    return {
        "url": "/ZeroNet-Internal/BigfileUpload?upload_nonce=" + nonce,
        "piece_size": piece_size,
        "inner_path": inner_path,
        "file_relative_path": file_relative_path,
    }
