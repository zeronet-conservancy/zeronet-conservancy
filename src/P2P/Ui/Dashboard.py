"""Small native dashboard pages for the server configuration surfaces.

The legacy Config and Plugin Manager pages depend on the gevent-era
ZeroFrame page runtime.  These pages intentionally use the native websocket
API directly, keeping the dashboard usable while the rest of the legacy UI
is being replaced.
"""
import pathlib

import jinja2


TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"
_env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)


def renderDashboard(page: str, websocket_url: str) -> str:
    template = _env.get_template("dashboard.html")
    return template.render(
        page=page,
        websocket_url=websocket_url,
        title="Configuration" if page == "config" else "Plugins",
    )
