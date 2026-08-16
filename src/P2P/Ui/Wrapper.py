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
- file_url also carries `&wrapper_nonce=<value>` -- the SAME value this
  render embeds as the wrapper page's own `window.wrapper_nonce` (see
  templates/wrapper.html). Found live, once a real site whose content.json
  actually requests postmessage_nonce_security got far enough to hit this
  path (ZeroHello's does; ContentManager.loadContent() not being called
  for already-on-disk sites at boot -- fixed in SiteManager.load() -- had
  been silently masking it): the real, unmodified site JS's own
  ZeroFrame.constructor reads `wrapper_nonce` out of *its own* URL
  (`document.location.href`) and echoes it back on every outgoing
  message; without it in file_url, every message the site sent carried an
  empty nonce and got rejected ("Message nonce error"), so nothing the
  site's own JS asked the wrapper to do (including just rendering) ever
  went through. What's still NOT ported: the original's server-side
  single-use tracking of issued nonces (self.server.wrapper_nonces,
  checked and consumed on the site's own page request) -- this only
  fixes the client-side nonce match the wrapper.html/ZeroFrame pair
  actually enforces; a real CSRF-hardening gap, not faked, just not
  needed to unblock the crash this was found chasing.
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
    wrapper_nonce: str | None = None,
) -> str:
    file_inner_path = inner_path or "index.html"
    if file_inner_path.endswith("/"):
        file_inner_path += "index.html"

    wrapper_nonce = wrapper_nonce or CryptHash.random()

    # Leading bare "&" is deliberate, not a typo -- found live, loading a
    # real site (ZeroMe): its own router (Text.queryParse in its bundled
    # all.js) only ever populates params.urls from a query segment that
    # has NO "=" in it (treating that lone segment as the app's own route
    # path); every other "&"-joined segment is parsed as key=value and
    # skipped for that purpose. Since wrapper=0/wrapper_nonce are both
    # key=value, a query string starting with either of them left
    # params.urls permanently undefined, crashing the site's own
    # ZeroMe.route() on page load -- not a bug in this stack's http
    # handling, but a real incompatibility this single-port
    # wrapper=0/wrapper_nonce substitute introduces for any site whose
    # router makes that same "first bare segment is the route" assumption
    # (a real, if naive, convention -- an empty first segment is exactly
    # what a plain "no deep link" visit's query would look like without
    # our added flags at all). The empty leading segment restores that:
    # split on "&" yields "" first, which queryParse treats as an empty
    # bare route (site's own default view) exactly as if no query string
    # had been added here, while wrapper=0/wrapper_nonce still parse
    # correctly as ordinary key=value pairs right after it.
    file_url = "/%s/%s?&wrapper=0&wrapper_nonce=%s" % (address, inner_path, wrapper_nonce)

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
