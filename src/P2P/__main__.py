"""The real process entrypoint for this package: `python -m P2P <app|actions> ...`.

Two separate bootstrapping problems this file exists to solve, neither
fixable from inside P2P/app.py's or P2P/actions.py's own main():

1. Plugin registration only affects a class decorated with @acceptPlugins
   if the plugin module was imported first (see PluginManager.py's own
   docstring). `python -m P2P.app` runs app.py top-to-bottom BEFORE
   reaching its bottom `if __name__ == "__main__": main()` line -- and
   app.py's own top-level `from .SiteManager import SiteManager` (which
   decorates SiteManager) already ran by then. There is no way for
   app.py's own main() to load plugins early enough; the only fix is a
   launcher that loads plugins before importing app.py (or actions.py)
   at all. This is that launcher.

2. Several legacy-descended modules this stack still depends on
   (Config.py notably, reached via P2P.SiteManager -> P2P.Site ->
   P2P.ContentManager -> Crypt.CryptBitcoin -> Config) do relative
   imports assuming they're part of the `src` package (Config.py:
   `from . import Build`), while everything else in this codebase
   (including every P2P/*.py file) imports them as bare top-level names
   (`from Config import config`). Both have to resolve to the SAME
   loaded module, not two separate Config instances -- so this imports
   Config once as `src.Config` (where its own relative imports work)
   and aliases sys.modules['Config'] to that, exactly like
   Test/conftest.py does for the pytest process. Without this,
   `python -m P2P ...` fails on Config.py's own `from . import Build`
   the first time anything needs it -- a real, standalone-process-only
   gap that pytest's own bootstrapping papered over until now, since
   nothing has run this package as its own process before.

`python -m P2P.app` / `python -m P2P.actions` still work directly and are
harmless to use -- they just won't have any plugins active (problem 1),
and will fail outright on the Config import (problem 2) unless something
else already set up sys.path/sys.modules the way this file does. Always
use `python -m P2P <subcommand>`.
"""
import os
import sys


def _bootstrapSysPath() -> None:
    here = os.path.dirname(os.path.abspath(__file__))  # .../src/P2P
    src_dir = os.path.dirname(here)  # .../src
    repo_root = os.path.dirname(src_dir)
    for path in (os.path.join(src_dir, "lib"), src_dir, repo_root):
        if path not in sys.path:
            sys.path.insert(0, path)

    import src.Config  # noqa: F401
    sys.modules.setdefault("Config", sys.modules["src.Config"])


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        sys.exit("Usage: python -m P2P <app|actions> [--no-plugins] ...")

    subcommand = sys.argv[1]
    del sys.argv[1]

    _bootstrapSysPath()

    if "--no-plugins" in sys.argv:
        sys.argv.remove("--no-plugins")
    else:
        from .PluginManager import plugin_manager
        plugin_manager.loadPlugins()

    if subcommand == "app":
        from .app import main as app_main
        app_main()
    elif subcommand == "actions":
        from .actions import main as actions_main
        actions_main()
    else:
        sys.exit("Unknown subcommand: %s (expected 'app' or 'actions')" % subcommand)


if __name__ == "__main__":
    main()
