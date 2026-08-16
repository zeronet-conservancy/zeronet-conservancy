#!/usr/bin/env python3
import os
import sys
from src.Config import config

# fix further imports from src dir
sys.modules['Config'] = sys.modules['src.Config']

def pyReq():
    major = sys.version_info.major
    minor = sys.version_info.minor
    if major < 3 or (major == 3 and minor < 8):
        print("Error: Python 3.8+ is required")
        sys.exit(0)
    if major == 3 and minor < 11:
        print(f"Python 3.11+ is recommended (you're running {sys.version})")

def launch():
    '''renamed from main to avoid clashes with main module'''
    pyReq()
    main = None

    if '--silent' not in sys.argv:
        from greet import fancy_greet
        fancy_greet(config.version)

    try:
        try:
            import main
            if not hasattr(main, 'start'):
                raise ImportError('resolved the desktop entrypoint instead of src.main')
        except ImportError:
            from src import main
            # The application historically imports this module as `main` from
            # many subsystems. Keep that compatibility alias when frozen
            # alongside the Android-required root main.py entrypoint.
            sys.modules['main'] = main
        main.start()
    except Exception as err:  # Prevent closing
        import traceback
        try:
            import logging
            logging.exception("Unhandled exception: %s" % err)
        except Exception as log_err:
            print("Failed to log error:", log_err)
            traceback.print_exc()
        error_log_path = config.log_dir / "error.log"
        try:
            with open(error_log_path, 'w') as f:
                traceback.print_exc(file=f)
        except OSError:
            # Keep the original startup error visible when the data directory
            # is read-only (for example, a system-wide installation).
            error_log_path = None
        print("---")
        print("Please report it: https://github.com/zeronet-conservancy/zeronet-conservancy/issues/new?template=bug-report.md")
        if sys.platform.startswith("win") and "python.exe" not in sys.executable:
            displayErrorMessage(err, error_log_path)

    if main and (main.update_after_shutdown or main.restart_after_shutdown):  # Updater
        if main.update_after_shutdown:
            print("Shutting down...")
            prepareShutdown()
            import update
            print("Updating...")
            update.update()
            if main.restart_after_shutdown:
                print("Restarting...")
                restart()
        else:
            print("Shutting down...")
            prepareShutdown()
            print("Restarting...")
            restart()


def displayErrorMessage(err, error_log_path):
    import ctypes
    import urllib.parse
    import subprocess

    MB_YESNOCANCEL = 0x3
    MB_ICONEXCLAIMATION = 0x30

    ID_YES = 0x6
    ID_NO = 0x7
    ID_CANCEL = 0x2

    err_message = "%s: %s" % (type(err).__name__, err)
    err_title = "Unhandled exception: %s\nReport error?" % err_message

    res = ctypes.windll.user32.MessageBoxW(0, err_title, "ZeroNet error", MB_YESNOCANCEL | MB_ICONEXCLAIMATION)
    if res == ID_YES:
        import webbrowser
        report_url = "https://github.com/zeronet-conservancy/zeronet-conservancy/issues/new"
        webbrowser.open(report_url)
    if res in [ID_YES, ID_NO]:
        subprocess.Popen(['notepad.exe', error_log_path])

def prepareShutdown():
    import atexit
    atexit._run_exitfuncs()

    # Close log files
    if "main" in sys.modules:
        logger = sys.modules["main"].logging.getLogger()

        for handler in logger.handlers[:]:
            handler.flush()
            handler.close()
            logger.removeHandler(handler)

    import time
    time.sleep(1)  # Wait for files to close

def restart():
    args = sys.argv[:]

    sys.executable = sys.executable.replace(".pkg", "")  # Frozen mac fix

    if not getattr(sys, 'frozen', False):
        args.insert(0, sys.executable)

    # Don't open browser after restart
    if "--open_browser" in args:
        del args[args.index("--open_browser") + 1]  # argument value
        del args[args.index("--open_browser")]  # argument key

    if getattr(sys, 'frozen', False):
        pos_first_arg = 1  # Only the executable
    else:
        pos_first_arg = 2  # Interpter, .py file path

    args.insert(pos_first_arg, "--open_browser")
    args.insert(pos_first_arg + 1, "False")

    if sys.platform == 'win32':
        args = ['"%s"' % arg for arg in args]

    try:
        print("Executing %s %s" % (sys.executable, args))
        os.execv(sys.executable, args)
    except Exception as err:
        print("Execv error: %s" % err)
    print("Bye.")


def start():
    config.working_dir = os.getcwd()
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)  # Change working dir to zeronet.py dir
    sys.path.insert(0, os.path.join(app_dir, "src/lib"))  # External liblary directory
    sys.path.insert(0, os.path.join(app_dir, "src"))  # Imports relative to src
    if getattr(sys, 'frozen', False):
        # Source modules historically import `util`, `Config`, `Actions`,
        # etc. as top-level names after src/ is added to sys.path. PyInstaller
        # stores the package as src.*, so provide the first compatibility
        # alias before src.main is loaded.
        import importlib
        try:
            # PyInstaller collects the legacy modules under their historical
            # top-level names. Prefer that namespace so plugin imports such as
            # ``from util import helper`` resolve normally.
            util_package = importlib.import_module('util')
            util_prefix = 'util'
        except ImportError:
            util_package = importlib.import_module('src.util')
            util_prefix = 'src.util'

        util_modules = (
            'Cached', 'Diff', 'Electrum', 'Event', 'Flag', 'Git', 'GreenletManager',
            'Msgpack', 'Noparallel', 'OpensslFindPatch', 'Platform', 'Pooled',
            'QueryJson', 'RateLimit', 'SafeRe', 'SocksProxy', 'ThreadPool',
            'WebView', 'argparseCompat', 'compat', 'helper',
        )
        for module_name in util_modules:
            try:
                module = importlib.import_module(f'{util_prefix}.{module_name}')
            except ImportError:
                module = importlib.import_module(f'src.util.{module_name}')
            setattr(util_package, module_name, module)
            sys.modules[f'util.{module_name}'] = module
        sys.modules['util'] = util_package

    if "--update" in sys.argv:
        sys.argv.remove("--update")
        print("Updating...")
        import update
        update.update()
    else:
        launch()


if __name__ == '__main__':
    if '--webview-child' in sys.argv:
        from src.util.WebView import main as webview_main
        sys.argv.remove('--webview-child')
        webview_main()
    else:
        start()
