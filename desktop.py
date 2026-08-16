#!/usr/bin/env python3
"""Packaged ZeroNet desktop entrypoint for the pywebview2 bundler."""

import sys


if "--webview-child" in sys.argv:
    from src.util.WebView import main as webview_main

    sys.argv.remove("--webview-child")
    webview_main()
else:
    if "--webview" not in sys.argv:
        sys.argv.append("--webview")
    import zeronet

    zeronet.start()
