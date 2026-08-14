import os
import json
import html
import shutil
import logging
from pathlib import Path

import gevent
from gevent.lock import RLock

from Config import config
from Plugin import PluginManager
from util import helper
from util.Flag import flag

plugin_dir = os.path.dirname(__file__)
template_dir = os.path.join(plugin_dir, "media", "template")
starters_dir = os.path.join(plugin_dir, "media", "starters")

log = logging.getLogger("UiSiteBuilder")

# Idempotent creation state (module-level, shared across plugin reloads)
_builder_address = None
_builder_lock = RLock()


def _state_path():
    return Path(config.private_dir) / "sitebuilder.json"


def _site_exists(address):
    if not address:
        return False
    site_dir = Path(config.data_dir) / address
    # Require content.json so a partially-deleted directory (leftover files)
    # is not mistaken for a live site.
    return site_dir.is_dir() and (site_dir / "content.json").is_file()


def _read_builder_address():
    global _builder_address
    if _builder_address:
        if _site_exists(_builder_address):
            return _builder_address
        _builder_address = None
    try:
        data = json.loads(_state_path().read_text())
        address = data.get("address")
    except Exception:
        return None
    if _site_exists(address):
        _builder_address = address
        return address
    return None


def _write_builder_address(address):
    global _builder_address
    _builder_address = address
    helper.atomicWrite(_state_path(), json.dumps({"address": address}).encode("utf8"))


def list_starters():
    """Return available starter sites."""
    starters = []
    for name in sorted(os.listdir(starters_dir)):
        starter_dir = os.path.join(starters_dir, name)
        if not os.path.isdir(starter_dir):
            continue
        try:
            with open(os.path.join(starter_dir, "settings.json")) as f:
                settings = json.load(f)
        except Exception:
            continue
        starters.append({
            "id": name,
            "title": settings.get("title", name),
            "description": settings.get("description", "")
        })
    return starters


def _starter_dir(starter):
    starter_dir = os.path.join(starters_dir, starter)
    if not os.path.isdir(starter_dir):
        starter_dir = os.path.join(starters_dir, "blank")
    return starter_dir


def _apply_starter_metadata(site_dir, starter_dir):
    """Copy the starter's title/description into the site's content.json.

    The dashboard shows the site's content.json title, so without this every
    site builder site is listed as "Site Builder" and they look like one copy.
    """
    try:
        settings = json.loads((Path(starter_dir) / "settings.json").read_text())
    except Exception:
        return
    content_path = Path(site_dir) / "content.json"
    try:
        content = json.loads(content_path.read_text())
    except Exception:
        content = {}
    for key in ("title", "description"):
        value = settings.get(key)
        if value:
            content[key] = value
    content_path.write_text(json.dumps(content, indent=2) + "\n")


def _notify_new_site(site):
    """Push the new site to admin UI websockets so the dashboard lists it immediately."""
    import sys
    if "main" not in sys.modules:  # import main has side-effects, breaks tests
        return
    try:
        import main
        ui_server = getattr(main, "ui_server", None)
    except Exception:
        ui_server = None
    if not ui_server:
        return
    for ws in list(getattr(ui_server, "websockets", [])):
        try:
            if ws.site is None or "ADMIN" not in ws.site.settings.get("permissions", []):
                continue
            if ws not in site.websockets:
                site.websockets.append(ws)
            ws.event("siteChanged", site)
        except Exception:
            continue


def create_builder_site(starter="blank", primary=False):
    """Create a fresh site from a starter, signed by the user's master seed."""
    from Site import SiteManager
    from User import UserManager

    starter_dir = _starter_dir(starter)

    user = UserManager.user_manager.get()
    if not user:
        user = UserManager.user_manager.create()

    address, address_index, site_data = user.getNewSiteData()
    privatekey = site_data["privatekey"]

    site_dir = Path(config.data_dir) / address
    shutil.copytree(template_dir, site_dir)
    # Replace the demo content with the chosen starter (for both the live data
    # and the clone seed).
    shutil.rmtree(site_dir / "data")
    shutil.rmtree(site_dir / "data-default")
    shutil.copytree(starter_dir, site_dir / "data")
    shutil.copytree(starter_dir, site_dir / "data-default")
    # sign() picks up ignore/optional/title from an existing content.json
    shutil.copy(site_dir / "content.json-default", site_dir / "content.json")
    _apply_starter_metadata(site_dir, starter_dir)

    # Register through SiteManager so the site is added to sites.json and
    # sites_changed is bumped (the same path Site.clone() uses).
    site = SiteManager.site_manager.add(address, all_file=False)
    site.content_manager.sign(
        "content.json",
        privatekey=privatekey,
        extend={"postmessage_nonce_security": True, "address_index": address_index}
    )
    site.settings["own"] = True
    # Only the primary site is remembered for the /SiteBuilder redirect
    if primary:
        _write_builder_address(address)
    site.saveSettings()
    # Persist ownership immediately instead of relying on the rate-limited
    # saveDelayed, otherwise the site can revert to non-owned after a restart.
    SiteManager.site_manager.save()
    # Mirrors Site.clone(): rebuild the sql cache after signing
    site.storage.rebuildDb()

    _notify_new_site(site)

    log.info("Created site builder site: %s (starter: %s)" % (address, starter))
    return address


def ensure_builder_site():
    """Return the primary builder site address, creating it on first use."""
    address = _read_builder_address()
    if address:
        return address
    with _builder_lock:
        address = _read_builder_address()
        if address:
            return address
        return create_builder_site(primary=True)


def favourite_builder(address):
    """Add the builder site to the dashboard's favourite sites."""
    from User import UserManager

    user = UserManager.user_manager.get()
    if not user:
        return

    dashboard = config.homepage
    site_data = user.getSiteData(dashboard, create=True)
    settings = site_data.get("settings", {})
    favs = settings.get("favorite_sites", {})
    if address not in favs:
        favs[address] = True
        settings["favorite_sites"] = favs
        site_data["settings"] = settings
        user.save()
        log.info("Added site builder to dashboard favourites: %s" % address)


@PluginManager.registerTo("SiteManager")
class SiteManagerPlugin(object):
    def load(self, *args, **kwargs):
        back = super(SiteManagerPlugin, self).load(*args, **kwargs)
        if config.action == "main":
            gevent.spawn(self._ensure_startup)
        return back

    def _ensure_startup(self):
        try:
            address = ensure_builder_site()
            if address:
                favourite_builder(address)
        except Exception as err:
            log.error("Site builder init error: %s" % err)


@PluginManager.registerTo("UiRequest")
class UiRequestPlugin(object):
    def actionWrapper(self, path, extra_headers=None):
        key = path.strip("/").lower()
        if key == "sitebuilder/new":
            return self.renderStartersPage()
        if key == "sitebuilder":
            starter = self.get.get("starter")
            if starter:
                with _builder_lock:
                    address = create_builder_site(starter=starter, primary=False)
                favourite_builder(address)
            else:
                address = ensure_builder_site()
            if not address:
                return self.error404("Site Builder is not available")
            self.sendHeader()
            return self.formatRedirect("/%s/builder/editor.html" % address)
        return super(UiRequestPlugin, self).actionWrapper(path, extra_headers)

    @helper.encodeResponse
    def renderStartersPage(self):
        self.sendHeader()
        cards = ""
        for starter in list_starters():
            cards += (
                '<a class="starter" href="/SiteBuilder?starter={id}">'
                '<strong>{title}</strong><span>{description}</span></a>'
            ).format(
                id=html.escape(starter["id"]),
                title=html.escape(starter["title"]),
                description=html.escape(starter["description"])
            )
        return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>New site - Site Builder</title>
<style>
 body {{ font-family: system-ui, sans-serif; background: #f7f7f9; color: #222; margin: 0; padding: 40px 20px; }}
 .wrap {{ max-width: 640px; margin: 0 auto; }}
 h1 {{ font-weight: 700; }}
 .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; margin-top: 20px; }}
 .starter {{ display: flex; flex-direction: column; gap: 4px; padding: 16px; background: #fff; border: 1px solid #e3e3e8; border-radius: 10px; text-decoration: none; color: #222; }}
 .starter:hover {{ border-color: #3563d0; }}
 .starter strong {{ font-size: 1.05rem; }}
 .starter span {{ color: #6b7280; font-size: 0.9rem; }}
</style></head>
<body><div class="wrap">
<h1>Create a new site</h1>
<p>Choose a starter to begin. You can customise everything afterwards.</p>
<div class="grid">{cards}</div>
</div></body></html>""".format(cards=cards)


@PluginManager.registerTo("UiWebsocket")
class UiWebsocketPlugin(object):
    @flag.admin
    def actionSiteBuilder(self, to):
        address = ensure_builder_site()
        if not address:
            return {"error": "Unable to create site builder"}
        favourite_builder(address)
        return {"address": address}

    @flag.admin
    def actionSiteBuilderStarters(self, to):
        return list_starters()

    @flag.admin
    def actionSiteBuilderCreate(self, to, starter="blank"):
        with _builder_lock:
            address = create_builder_site(starter=starter, primary=False)
        favourite_builder(address)
        return {"address": address}
