"""Launch the ZeroNet UI in an optional native webview process.

The GUI loop belongs in a child process. This keeps it out of gevent/trio's
event loop and lets macOS run the GUI loop on that process' main thread while
ZeroNet continues serving HTTP and WebSocket requests normally.
"""

from __future__ import annotations

import subprocess
import sys
from urllib.parse import urlparse


def _is_local_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}


def open_window(url: str):
    """Start a pywebview2 child process for a local URL."""
    if not _is_local_http_url(url):
        raise ValueError("Webview URL must be a local HTTP URL")
    if getattr(sys, "frozen", False):
        return subprocess.Popen([sys.executable, "--webview-child", url])
    return subprocess.Popen([sys.executable, "-m", "src.util.WebView", url])


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m src.util.WebView URL")
    try:
        import webview
    except ImportError as err:
        raise SystemExit(
            "Desktop webview support requires `pip install pywebview2` "
            "and the native platform dependencies documented by pywebview2."
        ) from err
    # Every pywebview2 backend used to tie the native right-click context
    # menu (copy/paste, etc.) to the debug flag, so packaged builds
    # (debug=False) lost basic copy/paste entirely, not just devtools.
    # This turns the context menu back on without enabling debug/devtools.
    # Guarded: ENABLE_CONTEXT_MENU only exists in pywebview2 releases that
    # carry this fix -- webview.settings is an ImmutableDict that raises
    # KeyError on unknown keys, and older/PyPI-published pywebview2 builds
    # must keep starting (with the pre-existing context-menu bug) rather
    # than crash on startup.
    if "ENABLE_CONTEXT_MENU" in webview.settings:
        webview.settings["ENABLE_CONTEXT_MENU"] = True
    webview.create_window("ZeroNet", sys.argv[1], width=1280, height=800)
    webview.start()


if __name__ == "__main__":
    main()
