"""Trio port of a scoped slice of plugins/UiSiteBuilder/UiSiteBuilderPlugin.py
-- the actual site-creation flow (siteBuilderStarters/siteBuilderCreate),
not the whole plugin. Absolute import for `command` -- P2P.PluginManager's
loadPlugins() imports plugin packages as bare top-level modules, so a
relative import beyond this package's own top level fails; see
P2P/plugins/CryptMessage/commands.py's own docstring, which hit and
documented this same gotcha first.

Reuses the legacy plugin's own bundled media/{template,starters} verbatim
(copied into this package's own media/ directory) -- pure static site
content (HTML/JS/CSS/JSON) with zero gevent dependency, same "real asset,
no rewrite needed" precedent as UiPassword's login.html and the Sidebar
plugin's media reuse. The site-creation LOGIC itself is genuinely simple
file-copying plus the same sign()/SiteManager.add() primitives siteCreate/
siteClone already established -- no legacy internals to translate beyond
that.

Narrower than the original two ways:
  - No "primary builder site" concept (ensure_builder_site(), the
    sitebuilder.json state file, the /SiteBuilder HTTP redirect route,
    or the SiteManager.load()-time auto-creation hook). Those exist in
    the original purely to give ZeroProxy-style deployments a single,
    always-available, lazily-created "scratch" site reachable by URL
    without going through the dashboard first -- a convenience layer on
    top of site creation, not site creation itself. siteBuilderCreate
    below IS the real feature (what the dashboard's own "New site"
    button actually calls); the lazy-singleton wrapper around it is a
    real, separate, smaller follow-up if ever needed.
  - No live "notify open websockets a new site appeared" push (the
    original's _notify_new_site(), iterating every OTHER admin
    websocket). This stack's siteCreate/siteClone don't broadcast either
    (the calling session gets the new address directly in the RPC
    response, which is what the real dashboard JS acts on) -- consistent
    with those, not a regression specific to this command.
"""
import json
from pathlib import Path

from P2P.Ui.commands import CommandError, _param, _requireAdmin, _requireSiteManager, _requireUser, command

_MEDIA_DIR = Path(__file__).resolve().parent / "media"
_TEMPLATE_DIR = _MEDIA_DIR / "template"
_STARTERS_DIR = _MEDIA_DIR / "starters"

# Paths under _TEMPLATE_DIR that get handled separately (starter content
# and the seed-only content.json-default), not copied verbatim.
_TEMPLATE_SKIP_PREFIXES = ("data/", "data-default/")
_TEMPLATE_SKIP_NAMES = {"content.json-default"}


def _starterDir(starter: str) -> Path:
    starter_dir = _STARTERS_DIR / starter
    if not starter_dir.is_dir():
        starter_dir = _STARTERS_DIR / "blank"
    return starter_dir


def _listStarters() -> list:
    starters = []
    for entry in sorted(_STARTERS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        try:
            settings = json.loads((entry / "settings.json").read_text())
        except Exception:
            continue
        starters.append({
            "id": entry.name,
            "title": settings.get("title", entry.name),
            "description": settings.get("description", ""),
        })
    return starters


async def _copyTree(site, source_dir: Path, dest_prefix: str = "") -> None:
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(source_dir).as_posix()
        await site.storage.write(dest_prefix + relative, path.read_bytes())


@command("siteBuilderStarters")
async def _cmdSiteBuilderStarters(session, params):
    _requireAdmin(session)
    return _listStarters()


@command("siteBuilderCreate")
async def _cmdSiteBuilderCreate(session, params):
    """Create a fresh site from a starter template, signed by the user's
    master seed, registered as owned -- same construction shape as
    siteCreate/siteClone (getNewSiteData() for the address, sign() for
    the real signature, SiteManager.add(own=True) + save() to persist),
    with the file content coming from this package's own bundled
    template/starter directories instead of a blank index.html or an
    existing loaded site."""
    _requireAdmin(session)
    starter = _param(params, "starter", 0, "blank") or "blank"

    user = await _requireUser(session)
    address, address_index, site_data = await user.getNewSiteData()
    privatekey = site_data["privatekey"]

    site_manager = _requireSiteManager(session)
    add_site = getattr(session.app, "addSite", None)
    site = add_site(address, own=True) if add_site else site_manager.add(address, own=True)
    if site is None:
        raise CommandError("Unable to create site")

    starter_dir = _starterDir(starter)

    for path in sorted(_TEMPLATE_DIR.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(_TEMPLATE_DIR).as_posix()
        if relative in _TEMPLATE_SKIP_NAMES or relative.startswith(_TEMPLATE_SKIP_PREFIXES):
            continue
        await site.storage.write(relative, path.read_bytes())

    await _copyTree(site, starter_dir, "data/")
    await _copyTree(site, starter_dir, "data-default/")

    default_content = json.loads((_TEMPLATE_DIR / "content.json-default").read_text())
    try:
        starter_settings = json.loads((starter_dir / "settings.json").read_text())
    except Exception:
        starter_settings = {}
    for key in ("title", "description"):
        value = starter_settings.get(key)
        if value:
            default_content[key] = value
    await site.storage.writeJson("content.json", default_content)
    await site.content_manager.loadContent("content.json")

    extend = {"postmessage_nonce_security": True}
    if address_index is not None:
        extend["address_index"] = address_index
    await site.content_manager.sign(privatekey, extend=extend)
    await site.storage.rebuildDb(site.content_manager, reason="site builder create")

    await site_manager.save()

    dashboard = getattr(session.app, "homepage", None)
    if dashboard:
        settings = user.getSiteData(dashboard).get("settings", {})
        settings.setdefault("favorite_sites", {})[address] = True
        user.setSiteSettings(dashboard, settings)
        await user.save()

    return {"address": address}
