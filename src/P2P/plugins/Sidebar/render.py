"""Real, but deliberately scoped, port of SidebarPlugin.py's HTML-building
half (sidebarRender*() + actionSidebarGetHtmlTag itself) -- see
commands.py's sidebarGetHtmlTag docstring for how this fits into the
"why the drag gesture never worked" investigation that led here.

Ported for real, using this stack's own real data:
  - Header (title), file-type size breakdown, size limit, optional-file
    stats/settings (reusing OptionalManager's own storage), a simple DB
    summary, site controls (pause/resume/delete/sign+publish/address),
    the "this is my site" checkbox, own-site settings (title/description),
    and the content.json chooser.

Deliberately NOT ported, because the thing they need doesn't exist in
this stack (or isn't a good match), same "narrow but real, not faked"
discipline as every other file in this package:
  - Peer stats (sidebarRenderPeerStats) -- the original's percentages
    (connectable/onion/local) come from legacy Peer/ConnectionServer
    objects and TorManager.site_onions, neither of which this stack's
    P2P.Site/PeerRecord model exposes in the same shape. A real peer
    COUNT is shown instead (len(site.peers)), not the full breakdown.
  - Transfer stats (sidebarRenderTransferStats) -- needs bytes_recv/
    bytes_sent counters this stack's Site never tracks (no settings
    dict; see P2P.SiteManager's own docstring). Faking a number here
    would be a lie, not a simplification, so it's omitted entirely.
  - Bad files (sidebarRenderBadFiles) -- site.bad_files isn't tracked.
  - Identity/quota (sidebarRenderIdentity) -- needs an async User cert
    lookup plus getRules() (content.json permission-rules resolution,
    itself not ported -- see ContentManager's own module docstring for
    what it excludes). A real per-site auth address IS shown when a
    user already exists, without the quota-used calculation.
  - The globe visualization and GeoLite2 IP-geolocation download
    (media_globe/, downloadGeoLiteDb) -- a large, separate, network-
    egress-heavy feature nothing else in this stack depends on.
  - Donate links -- trivial to add later (plain content.json field
    reads) but not exercised by anything this investigation needed.
"""
import html
import math
from pathlib import Path


def _extensionSizesFromFiles(files: dict) -> tuple[dict[str, int], int]:
    sizes: dict[str, int] = {}
    total = 0
    for inner_path, file_info in files.items():
        size = file_info.get("size", 0)
        total += size
        ext = inner_path.rsplit(".", 1)[-1] if "." in inner_path else ""
        sizes[ext] = sizes.get(ext, 0) + size
    return sizes, total


def _formatSize(size: float) -> str:
    if size > 1024 * 1024 * 10:
        return "%.0fMB" % (size / 1024 / 1024)
    return "%.0fkB" % (size / 1024)


def _renderFileStats(body: list, site) -> None:
    raw_content = site.content_manager.contents.get("content.json") or {}
    sizes, size_total = _extensionSizesFromFiles(raw_content.get("files", {}))

    body.append(
        "<li><label>Files "
        "<a href='#Site+directory' id='link-directory' class='link-right'>Open site directory</a>"
        "</label><ul class='graph graph-stacked'>"
    )

    groups = (
        ("html", "yellow"), ("css", "orange"), ("js", "purple"),
        ("jpg", "green"), ("png", "green"), ("gif", "green"),
        ("json", "darkblue"), ("Other", "white"), ("Total", "black"),
    )
    accounted = 0
    for ext, color in groups:
        if ext in ("Other", "Total"):
            continue
        size = sizes.get(ext, 0)
        accounted += size
        percent = (100 * size / size_total) if size_total else 0
        body.append(
            "<li style='width: %.2f%%' class='ext-%s back-%s'></li>"
            % (math.floor(percent * 100) / 100, html.escape(ext), color)
        )
    other_size = max(0, size_total - accounted)
    percent = (100 * other_size / size_total) if size_total else 0
    body.append("<li style='width: %.2f%%' class='ext-other back-white'></li>" % (math.floor(percent * 100) / 100,))

    body.append("</ul><ul class='graph-legend'>")
    for ext, color in groups:
        size = size_total if ext == "Total" else (other_size if ext == "Other" else sizes.get(ext, 0))
        body.append(
            "<li class='color-%s'><span>%s:</span><b>%s</b></li>"
            % (color, html.escape(ext or "(no ext)"), _formatSize(size))
        )
    body.append("</ul></li>")


def _renderSizeLimit(body: list, site, formatted_info: dict) -> None:
    size_mb = formatted_info["settings"]["size"] / 1024 / 1024
    size_limit = formatted_info["size_limit"]
    percent_used = (size_mb / size_limit) if size_limit else 0
    body.append(
        "<li><label>Size limit <small>(limit used: %.0f%%)</small></label>"
        "<input type='text' class='text text-num' value='%s' id='input-sitelimit'/><span class='text-post'>MB</span>"
        "<a href='#Set' class='button' id='button-sitelimit'>Set</a></li>"
        % (percent_used * 100, html.escape(str(size_limit)))
    )


def _renderOptionalFileStats(body: list, site) -> bool:
    total = 0
    downloaded = 0
    for content_inner_path, content in site.content_manager.contents.items():
        for relative_path, file_info in content.get("files_optional", {}).items():
            size = file_info.get("size", 0)
            total += size
            inner_path = relative_path if "/" not in content_inner_path else content_inner_path.rsplit("/", 1)[0] + "/" + relative_path
            if site.storage.isFile(inner_path):
                downloaded += size
    if not total:
        return False

    percent = downloaded / total
    body.append(
        "<li><label>Optional files</label>"
        "<ul class='graph'><li style='width: 100%%' class='total back-black'></li>"
        "<li style='width: %.0f%%' class='connected back-green'></li></ul>"
        "<ul class='graph-legend'>"
        "<li class='color-green'><span>Downloaded:</span><b>%s</b></li>"
        "<li class='color-black'><span>Total:</span><b>%s</b></li></ul></li>"
        % (percent * 100, _formatSize(downloaded), _formatSize(total))
    )
    return True


def _renderDbInfo(body: list, site) -> None:
    if site.storage.db is not None:
        db_path = str(site.storage.db.db_path)
        size_kb = site.storage.getSize(site.storage.getInnerPath(Path(db_path))) / 1024
        body.append(
            "<li><label>Database <small>(%.2fkB)</small></label>"
            "<div class='flex'><input type='text' class='text disabled' value='%s' disabled='disabled'/>"
            "<a href='#Rebuild' id='button-dbrebuild' class='button'>Rebuild</a></div></li>"
            % (size_kb, html.escape(db_path))
        )
    else:
        body.append("<li><label>Database</label><div class='flex'>"
                     "<input type='text' class='text disabled' value='No database found' disabled='disabled'/></div></li>")


def _renderControls(body: list, site, is_admin: bool) -> None:
    class_pause = "" if site.isServing() else "hidden"
    class_resume = "hidden" if site.isServing() else ""
    admin_only = "" if is_admin else "hidden"
    body.append(
        "<li><label>Site control</label>"
        "<a href='#Pause' class='button %s %s' id='button-pause'>Pause</a>"
        "<a href='#Resume' class='button %s %s' id='button-resume'>Resume</a>"
        "<a href='#Clone' class='button %s' id='button-clone'>Clone</a>"
        "<a href='#Delete' class='button %s' id='button-delete'>Delete</a></li>"
        % (class_pause, admin_only, class_resume, admin_only, admin_only, admin_only)
    )
    body.append(
        "<li><label>Site address</label><br><div class='flex'>"
        "<span class='input text disabled'>%s</span></div></li>" % html.escape(site.address)
    )
    body.append(
        "<li><label>ZeroNet</label>"
        "<a href='/Config' target='_top' class='button'>Dashboard</a></li>"
    )


def _renderOwnedCheckbox(body: list, is_own: bool) -> None:
    checked = "checked='checked'" if is_own else ""
    body.append(
        "<h2 class='owned-title'>This is my site</h2>"
        "<input type='checkbox' class='checkbox' id='checkbox-owned' %s/><div class='checkbox-skin'></div>" % checked
    )


def _renderOwnSettings(body: list, site) -> None:
    raw_content = site.content_manager.contents.get("content.json") or {}
    title = raw_content.get("title", "")
    description = raw_content.get("description", "")
    body.append(
        "<li><label for='settings-title'>Site title</label>"
        "<input type='text' class='text' value='%s' id='settings-title'/></li>"
        "<li><label for='settings-description'>Site description</label>"
        "<input type='text' class='text' value='%s' id='settings-description'/></li>"
        "<li><a href='#Save' class='button' id='button-settings'>Save site settings</a></li>"
        % (html.escape(title, quote=True), html.escape(description, quote=True))
    )


def _renderPrivateSite(body: list, site, recipients: dict, pending_requests: dict) -> None:
    """Owner-facing private-site management: current approved recipients
    (with a Remove button each), a pending-requests list delivered via
    P2P.protocols.request_access (approve/deny, one click, no signature
    to copy-paste), and a manual approve-by-signature fallback for the
    out-of-band case (a request that never reached this node directly,
    e.g. the requester wasn't connected to it at request time). Purely a
    settings editor -- approving/removing a recipient here only updates
    the persisted private_recipients list (P2P.Ui.commands.siteApproveRequest/
    siteAddRecipient/siteRemoveRecipient); it takes a "Sign and publish"
    (below) to actually re-wrap the site with the new recipient list, same
    explicit-separate-step convention siteSign already has everywhere else
    in this file.

    Status is derived from `recipients` (SiteManager's own persisted
    setting), NOT site.content_manager.isPrivate() -- that checks
    self.contents["content.json"], which for the OWNER always holds the
    decrypted plaintext after sign() (see ContentManager.py's own module
    docstring), so it never actually reports True for the one person
    this section is built for. Same "don't trust the possibly-decrypted
    in-memory cache" lesson Site.unlockPrivate() already had to learn."""
    if recipients:
        status = "Private, %d recipient%s" % (len(recipients), "" if len(recipients) == 1 else "s")
    else:
        status = "Public"
    body.append("<li><label>Private site <small>(%s)</small></label>" % html.escape(status))
    if recipients:
        body.append("<ul class='recipients'>")
        for address in sorted(recipients):
            body.append(
                "<li class='recipient'>%s "
                "<a href='#Remove' class='button recipient-remove' data-address='%s'>Remove</a></li>"
                % (html.escape(address), html.escape(address, quote=True))
            )
        body.append("</ul>")
    body.append("</li>")

    if pending_requests:
        body.append(
            "<li><label>Pending access requests <small>(%d)</small></label>"
            "<ul class='pending-requests'>" % len(pending_requests)
        )
        for address in sorted(pending_requests):
            escaped_address = html.escape(address, quote=True)
            body.append(
                "<li class='pending-request'>%s "
                "<a href='#Approve' class='button request-approve' data-address='%s'>Approve</a> "
                "<a href='#Deny' class='button request-deny' data-address='%s'>Deny</a></li>"
                % (html.escape(address), escaped_address, escaped_address)
            )
        body.append("</ul></li>")

    body.append(
        "<li><label for='input-recipient-address'>Approve recipient: address</label>"
        "<input type='text' class='text' id='input-recipient-address'/></li>"
        "<li><label for='input-recipient-signature'>...their access request signature</label>"
        "<input type='text' class='text' id='input-recipient-signature'/></li>"
        "<li><a href='#Approve' class='button' id='button-recipient-add'>Approve recipient</a></li>"
    )


def _renderContents(body: list, site) -> None:
    raw_content = site.content_manager.contents.get("content.json") or {}
    body.append(
        "<li><label>Content publishing</label>"
        "<div class='flex'><input type='text' class='text' value='content.json' id='input-contents'/>"
        "<a href='#Sign-and-Publish' id='button-sign-publish' class='button'>Sign and publish</a></div>"
    )
    contents = ["content.json"] + list(raw_content.get("includes", {}).keys())
    body.append("<div class='contents'>Choose: ")
    for content in contents:
        body.append("<a href='%s' class='contents-content'>%s</a> " % (html.escape(content), html.escape(content)))
    body.append("</div></li>")


def renderSidebarHtml(site, formatted_info: dict, is_own: bool, is_admin: bool, site_manager=None) -> str:
    raw_content = site.content_manager.contents.get("content.json") or {}
    title = raw_content.get("title", site.address)

    body = ["<div>", "<a href='#Close' class='close'>&times;</a>", "<h1>%s</h1>" % html.escape(title)]
    body.append("<ul class='fields'>")
    body.append(
        "<li><label>Peers</label><ul class='graph-legend'>"
        "<li class='color-green'><span>Connected:</span><b>%d</b></li></ul></li>" % len(site.peers)
    )
    _renderFileStats(body, site)
    _renderSizeLimit(body, site, formatted_info)
    has_optional = _renderOptionalFileStats(body, site)
    _renderDbInfo(body, site)
    _renderControls(body, site, is_admin)
    body.append("</ul>")

    if is_admin:
        _renderOwnedCheckbox(body, is_own)
        body.append("<div class='settings-owned'><ul class='fields'>")
        if is_own:
            _renderOwnSettings(body, site)
            recipients = site_manager.getSiteSetting(site.address, "private_recipients", {}) if site_manager else {}
            pending_requests = site_manager.getSiteSetting(site.address, "private_pending_requests", {}) if site_manager else {}
            _renderPrivateSite(body, site, recipients, pending_requests)
        _renderContents(body, site)
        body.append("</ul></div>")

    body.append("</div>")
    return "".join(body)
