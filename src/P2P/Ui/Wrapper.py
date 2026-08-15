"""Wrapper-HTML rendering, ported from UiRequest.renderWrapper() onto
Jinja2 instead of the original's regex-substitution render().

templates/wrapper.html is the *actual* production template
(src/Ui/template/wrapper.html), converted to Jinja2 syntax and verified
byte-identical outside that conversion -- not a rewrite, so none of the
real page's markup/JS/CSS changed. Jinja2's own autoescaping replaces the
original's hand-rolled xescape() (which combined HTML-escaping with
regex-char-escaping, the latter only needed because the original
substituted via re.sub()). A handful of fields are pre-serialized
JS values, not HTML text, and are marked `| safe` in the template to skip
escaping: meta_tags (a raw HTML block), and postmessage_nonce_security/
permissions/show_loadingscreen (JS boolean/array literals built with
json.dumps(), exactly like the original).

Scoped down from the original in a few real ways, matching this whole
migration's "narrow but real" pattern rather than faking values:
- No multi-user theme system (UserManager isn't ported) -- always "light".
- No nonce-security/postmessage validation system -- postmessage_nonce_security
  stays "false" unless a site's content.json explicitly requests it, same
  computation as the original, just without the broader nonce-tracking
  system around it.
- server_url/homepage are built from the request directly rather than
  through isProxyRequest()'s reverse-proxy detection (CORS §08's job).
- No separate site_file_server_port: the original avoids ever re-wrapping
  the inner iframe's own request by serving raw site content on a SECOND
  port (ui_site_port, typically ui_port+1) so the iframe's absolute URL
  never lands back on the wrapper-serving port at all. This stack only
  binds one port, so file_url instead carries an explicit `?wrapper=0` --
  UiApp._handleSite() already honors that query param (wants_wrapper),
  it just wasn't being set here. A real bug, not a stylistic choice: found
  live -- the iframe's src pointed at the exact same address+path as the
  parent frame with no wrapper=0, so it got wrapped AGAIN, and the nested
  wrapper's own "escape from iframe" script (window.self !== window.top)
  forced a top-level reload every single time, reloading the outer
  wrapper, which re-embedded the iframe, forever.
"""
import html
import json
import pathlib

import jinja2

from Crypt import CryptHash

TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=True,
)


def _xescape(value: str) -> str:
    """HTML-escape only -- Jinja2's autoescaping already handles this for
    every non-`| safe` field, so this exists just for the couple of values
    built by hand before being handed to the template (e.g. inside
    meta_tags, which is itself `| safe` and so responsible for its own
    escaping of any values it embeds)."""
    return html.escape(value, quote=True)


def renderWrapper(
    site,
    scheme: str,
    host: str,
    site_file_server_port: int,
    address: str,
    inner_path: str,
    title: str,
    homepage: str = "/",
    server_url: str = "",
    script_nonce: str = "",
    show_loadingscreen: bool | None = None,
) -> str:
    file_inner_path = inner_path or "index.html"
    if file_inner_path.endswith("/"):
        file_inner_path += "index.html"

    file_url = "/%s/%s?wrapper=0" % (address, inner_path)

    wrapper_nonce = CryptHash.random()

    theme = "light"  # No multi-user theme system ported yet -- see module docstring
    themeclass = "theme-%-6s" % theme

    body_style = ""
    meta_tags = ""
    postmessage_nonce_security = "false"

    content = site.content_manager.contents.get("content.json")
    if content:
        if content.get("background-color"):
            background_color = content.get("background-color-%s" % theme, content["background-color"])
            body_style += "background-color: %s;" % _xescape(background_color)
        if content.get("viewport"):
            meta_tags += '<meta name="viewport" id="viewport" content="%s">' % _xescape(content["viewport"])
        if content.get("favicon"):
            meta_tags += '<link rel="icon" href="/%s%s">' % (address, _xescape(content["favicon"]))
        if content.get("postmessage_nonce_security"):
            postmessage_nonce_security = "true"

    sandbox_permissions = " allow-same-origin" if "NOSANDBOX" in site.permissions else ""

    if show_loadingscreen is None:
        show_loadingscreen = not site.storage.isFile(file_inner_path)

    template = _env.get_template("wrapper.html")
    return template.render(
        site_file_server="%s://%s:%s" % (scheme, host, site_file_server_port),
        server_url=server_url,
        file_url=file_url,
        file_inner_path=file_inner_path,
        address=address,
        title=title,
        body_style=body_style,
        meta_tags=meta_tags,
        query_string="",
        wrapper_key=site.wrapper_key,
        ajax_key=site.ajax_key,
        wrapper_nonce=wrapper_nonce,
        postmessage_nonce_security=postmessage_nonce_security,
        permissions=json.dumps(site.permissions),
        show_loadingscreen=json.dumps(show_loadingscreen),
        sandbox_permissions=sandbox_permissions,
        rev="",
        lang="en",
        homepage=homepage,
        themeclass=themeclass,
        script_nonce=script_nonce,
    )
