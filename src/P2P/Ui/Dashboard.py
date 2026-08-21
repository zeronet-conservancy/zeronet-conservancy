"""Small native dashboard pages for the server configuration surfaces.

The legacy Config and Plugin Manager pages depend on the gevent-era
ZeroFrame page runtime.  These pages intentionally use the native websocket
API directly, keeping the dashboard usable while the rest of the legacy UI
is being replaced.

All five pages (dashboard.html's config/plugins/sitebuilder/contentfilter,
plus file_manager.html and console.html) extend templates/_layout.html,
which inlines vendored Pico CSS (see vendor/NOTICE.md for why vendored
rather than CDN-linked -- this app is offline-first) directly into the
page's own <style> tag via the pico_css context var below, not a separate
/uimedia-style route: every one of these pages must render standalone,
with zero dependency on any other request succeeding first.
"""
import pathlib

import jinja2


TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"
if not TEMPLATE_DIR.is_dir():
    TEMPLATE_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "P2P" / "Ui" / "templates"
_env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)

_VENDOR_DIR = pathlib.Path(__file__).parent / "vendor"
if not _VENDOR_DIR.is_dir():
    _VENDOR_DIR = pathlib.Path(__file__).resolve().parents[2] / "src" / "P2P" / "Ui" / "vendor"
_PICO_CSS = (_VENDOR_DIR / "pico.min.css").read_text(encoding="utf-8")


_PAGE_TEMPLATES = {
    "config": "dashboard.html",
    "plugins": "dashboard.html",
    "sitebuilder": "dashboard.html",
    "contentfilter": "dashboard.html",
    "files": "file_manager.html",
    "console": "console.html",
}

# Previously unset entirely (dashboard.html referenced {{ title }} with
# nothing in context ever supplying it, so <title>/<h1> silently rendered
# blank) -- found while unifying these pages onto one shared _layout.html,
# which made every page's title block impossible to ignore.
#
# "contentfilter" -> "User management": renamed (route/page key left as
# "contentfilter" -- no reason to touch routing/tests for a label) once
# this page grew a Local names section alongside the existing blocked-
# sites/muted-users tables; blocking was never really the page's own
# subject, just the first per-address action it happened to expose.
_PAGE_TITLES = {
    "config": "Configuration",
    "plugins": "Plugins",
    "sitebuilder": "New site",
    "contentfilter": "User management",
    "files": "Files",
    "console": "Console",
}


def renderDashboard(page: str, websocket_url: str, **context) -> str:
    template = _env.get_template(_PAGE_TEMPLATES[page])
    context.setdefault("title", _PAGE_TITLES[page])
    return template.render(page=page, websocket_url=websocket_url, pico_css=_PICO_CSS, **context)
