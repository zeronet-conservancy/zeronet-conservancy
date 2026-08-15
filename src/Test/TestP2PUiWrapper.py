import pathlib
import tempfile

from P2P.Site import Site
from P2P.Ui.Wrapper import renderWrapper


class TestP2PUiWrapper:
    def testRendersRealTemplateWithSiteValues(self):
        with tempfile.TemporaryDirectory() as root:
            site = Site("1TestWrapperSite", pathlib.Path(root))
            site.content_manager.contents["content.json"] = {
                "background-color": "#fff",
                "viewport": "width=device-width",
                "favicon": "favicon.ico",
            }

            html = renderWrapper(
                site, scheme="http", host="127.0.0.1", site_file_server_port=43111,
                address="1TestWrapperSite", inner_path="index.html", title="My Test Site",
            )

        assert "<!DOCTYPE html>" in html
        assert "My Test Site - ZeroNet" in html
        assert 'address = "1TestWrapperSite"' in html
        assert "background-color: #fff;" in html
        assert '<meta name="viewport" id="viewport" content="width=device-width">' in html
        assert '<link rel="icon" href="/1TestWrapperSite favicon.ico">'.replace(" ", "") in html.replace(" ", "")
        assert site.wrapper_key in html
        assert site.ajax_key in html

    def testEscapesTitleAgainstXss(self):
        with tempfile.TemporaryDirectory() as root:
            site = Site("1TestWrapperSite2", pathlib.Path(root))
            html = renderWrapper(
                site, scheme="http", host="127.0.0.1", site_file_server_port=43111,
                address="1TestWrapperSite2", inner_path="index.html",
                title='<script>alert(1)</script>',
            )

        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def testPermissionsAndShowLoadingscreenAreRawJsNotEscaped(self):
        with tempfile.TemporaryDirectory() as root:
            site = Site("1TestWrapperSite3", pathlib.Path(root))
            site.permissions = ["ADMIN", "NOSANDBOX"]

            html = renderWrapper(
                site, scheme="http", host="127.0.0.1", site_file_server_port=43111,
                address="1TestWrapperSite3", inner_path="index.html", title="X",
                show_loadingscreen=True,
            )

        assert 'permissions = ["ADMIN", "NOSANDBOX"]' in html
        assert "permissions = &#34;" not in html  # not HTML-escaped
        assert "show_loadingscreen = true" in html
        assert "allow-same-origin" in html  # NOSANDBOX permission reflected in sandbox_permissions

    def testDefaultShowLoadingscreenBasedOnFileExistence(self):
        with tempfile.TemporaryDirectory() as root:
            site = Site("1TestWrapperSite4", pathlib.Path(root))
            # index.html does not exist on disk -- default should show the loading screen
            html = renderWrapper(
                site, scheme="http", host="127.0.0.1", site_file_server_port=43111,
                address="1TestWrapperSite4", inner_path="index.html", title="X",
            )
        assert "show_loadingscreen = true" in html

    def testJsBracesInTemplateSurviveUntouched(self):
        """The real safety check: inline JS like `if (x) { ... }` must not
        get mangled by the Jinja2 conversion (this was the actual risk
        with using brace-based templating on this specific file)."""
        with tempfile.TemporaryDirectory() as root:
            site = Site("1TestWrapperSite5", pathlib.Path(root))
            html = renderWrapper(
                site, scheme="http", host="127.0.0.1", site_file_server_port=43111,
                address="1TestWrapperSite5", inner_path="index.html", title="X",
            )
        assert "if (window.self !== window.top) {" in html
        assert "document.execCommand(\"Stop\", false);" in html
