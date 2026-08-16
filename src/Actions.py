import logging
import sys
import time
import gevent
from Config import config


class Actions:
    """CLI action dispatcher. Legacy-removal note: every action here now
    only runs the trio/libp2p stack -- the gevent implementation this
    class used to fall back to when called with p2p=False has been
    removed (see P2P/app.py's own module docstring for what superseded
    it). The p2p keyword argument survives on each method purely because
    Config.py's argparse layer still supplies it as a kwarg via
    getActionArguments() for every subcommand; passing p2p=False now
    raises rather than silently doing nothing."""

    def call(self, function_name, kwargs):
        logging.info(f'zeronet-conservancy {config.version_full} on Python {sys.version} Gevent {gevent.__version__}')

        func = getattr(self, function_name, None)
        back = func(**kwargs)
        if back:
            print(back)

    def _requireP2P(self, p2p):
        if not p2p:
            raise RuntimeError(
                "The legacy gevent implementation has been removed -- "
                "pass p2p=True (the default) to use the trio/libp2p stack."
            )

    # Default action: Start serving UiServer and FileServer
    def main(self, p2p=True):
        self._requireP2P(p2p)
        return self.mainP2P()

    def mainP2P(self):
        """Phase 10 cutover: run the trio-native P2P stack (P2P/app.py's
        App) through the real, official entrypoint -- `zeronet.py main`
        -- instead of only via the standalone `python -m P2P app`
        launcher. This is now the ONLY implementation (the legacy gevent
        server this used to fall back to via --no-p2p has been removed
        entirely -- see this module's own docstring). UiPassword
        (--ui-password, a single shared UI password), Tor (both
        control-port AND SOCKS5 dial-out, see P2P/Tor.py's own
        docstring), and Multiuser's core account isolation (--multiuser,
        each browser cookie-identified to its own persisted account, see
        P2P.UserManager's own docstring) are all closed now -- stale gaps
        corrected here, not still open. Multiuser's account-switching and
        master-seed backup/reveal UI (userSet/userSelectForm/userLogin/
        userLoginForm/userLogout/userShowMasterSeed, see P2P/Ui/commands.py)
        is also closed now -- a browser can log into a DIFFERENT existing
        account, or view/export its own seed, not just the one its cookie
        already points at.

        Runs via P2P.compat.run(), the same bracketed-monkey-patch-
        restoration helper every P2P test uses -- main.py already
        gevent.monkey.patch_all()'d before Actions.call() ever runs, and
        this is one long trio.run() for the server's entire lifetime, so
        the same "restore real sockets around this one call" pattern
        applies directly. See P2P/compat.py's own docstring for why this
        is necessary and why it's safe here specifically.

        Shuts down on SIGTERM/SIGINT via trio.open_signal_receiver()
        rather than relying on Debug/DebugHook.py's own SIGTERM handler
        (installed unconditionally at import time by main.py's own
        init()): that handler's fallback path is `sys.exit(0)` whenever
        `main.file_server` isn't set, which it never is here (that was a
        legacy-Actions.main()-only global, now removed) -- raising
        SystemExit through whatever trio-internal frame happens to be
        executing when the signal arrives corrupts trio's run loop
        (surfaces as a "Trio guest run got abandoned" RuntimeWarning at
        shutdown, a real bug caught while testing this slice).
        trio.open_signal_receiver() temporarily installs its own handler
        for the scope of this run (restoring whatever was there before
        on exit) and delivers signals as a normal async iterator instead,
        so cancellation goes through trio's own structured-shutdown path.
        """
        import signal

        from P2P import compat
        from P2P.PluginManager import plugin_manager as p2p_plugin_manager
        p2p_plugin_manager.loadPlugins()  # Must happen before P2P.app's own
        # `from .SiteManager import SiteManager` import below decorates it --
        # see P2P.PluginManager's own docstring on this ordering requirement.
        from P2P.app import App

        async def _run():
            import trio

            app = App(
                config.data_dir,
                tcp_port=config.fileserver_port,
                ui_host=config.ui_ip,
                ui_port=config.ui_port,
                enable_dht=config.dht,
                enable_tor=(config.tor != "disable"),
                homepage=config.homepage,
                ui_password=config.ui_password,
                multiuser=config.multiuser,
            )
            await app.loadSites()
            await app.loadUsers()

            window_process = None

            async def wait_for_window(process):
                while process.poll() is None:
                    await trio.sleep(0.2)
                logging.info("ZeroNet window closed; shutting down the P2P server")
                shutdown_event.set()

            async def wait_for_signal():
                with trio.open_signal_receiver(signal.SIGTERM, signal.SIGINT) as signal_aiter:
                    async for signum in signal_aiter:
                        logging.info("Shutting down (signal: %s)...", signal.Signals(signum).name)
                        shutdown_event.set()
                        return

            async with trio.open_nursery() as nursery:
                shutdown_event = trio.Event()
                nursery.start_soon(app.run)  # Logs "P2P app running: peer_id=..." once bound

                if config.open_browser in ("webview", "pywebview", "pywebview2"):
                    # The native P2P path does not pass through the legacy
                    # helper.openBrowser() call. Wait for the UI listener and
                    # launch the packaged pywebview2 child explicitly.
                    for _ in range(200):
                        if app.ui_server.bound_addresses:
                            break
                        await trio.sleep(0.05)
                    if app.ui_server.bound_addresses:
                        from util.WebView import open_window
                        window_process = open_window(app.ui_server.bound_addresses[0] + "/")
                        nursery.start_soon(wait_for_window, window_process)

                nursery.start_soon(wait_for_signal)
                await shutdown_event.wait()
                nursery.cancel_scope.cancel()

        compat.run(_run)

    def _runP2PAction(self, method_name, **kwargs):
        """Shared plumbing for every siteX/dbX/crypt*/peer* action below:
        constructs a throwaway P2P.actions.Actions and runs one of its
        methods to completion via P2P.compat.run() (see mainP2P()'s own
        docstring for why that bracketing is needed). Each P2P.actions
        method already handles its own SiteManager/UserManager loading
        and FileServer lifecycle per call, so a fresh instance per CLI
        invocation is correct, not wasteful."""
        from P2P import compat
        from P2P.PluginManager import plugin_manager as p2p_plugin_manager
        p2p_plugin_manager.loadPlugins()
        from P2P.actions import Actions as P2PActions

        async def _call():
            p2p_actions = P2PActions(config.data_dir)
            return await getattr(p2p_actions, method_name)(**kwargs)

        return compat.run(_call)

    # Site commands

    def siteCreate(self, use_master_seed=True, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("siteCreate", use_master_seed=use_master_seed)

    def siteSign(self, address, privatekey=None, inner_path="content.json", publish=False,
                 remove_missing_optional=False, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("siteSign", address=address, privatekey=privatekey, publish=publish)

    def siteVerify(self, address, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("siteVerify", address=address)

    def dbRebuild(self, address, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("dbRebuild", address=address)

    def dbQuery(self, address, query, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("dbQuery", address=address, query=query)

    def siteAnnounce(self, address, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("siteAnnounce", address=address, enable_dht=config.dht)

    def siteDownload(self, address, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("siteDownload", address=address, enable_dht=config.dht)

    def siteNeedFile(self, address, inner_path, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("siteNeedFile", address=address, inner_path=inner_path, enable_dht=config.dht)

    def siteCmd(self, address, cmd, parameters, wrapper_key=None, ui_host=None, ui_port=None, p2p=True):
        self._requireP2P(p2p)
        if not wrapper_key:
            raise ValueError("siteCmd on the native stack requires --wrapper-key")
        import json
        params = json.loads(parameters.replace("'", '"')) if parameters else {}
        return self._runP2PAction(
            "siteCmd", cmd=cmd, wrapper_key=wrapper_key, params=params,
            ui_host=ui_host or config.ui_ip, ui_port=ui_port or config.ui_port,
        )

    def importBundle(self, bundle, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("importBundle", bundle=bundle)

    def sitePublish(self, address, peer_ip=None, peer_port=15441, inner_path="content.json", recursive=False,
                     p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("sitePublish", address=address, inner_path=inner_path, enable_dht=config.dht)

    # Crypto commands
    def cryptPrivatekeyToAddress(self, privatekey=None, p2p=True):
        self._requireP2P(p2p)
        if not privatekey:
            import getpass
            privatekey = getpass.getpass("Private key (input hidden):")
        return self._runP2PAction("cryptPrivatekeyToAddress", privatekey=privatekey)

    def cryptSign(self, message, privatekey, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("cryptSign", message=message, privatekey=privatekey)

    def cryptVerify(self, message, sign, address, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction("cryptVerify", message=message, sign=sign, address=address)

    def cryptGetPrivatekey(self, master_seed, site_address_index=None, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction(
            "cryptGetPrivatekey", master_seed=master_seed,
            site_address_index=site_address_index,
        )

    # Peer
    def peerPing(self, peer_ip, peer_port=None, p2p=True):
        self._requireP2P(p2p)
        if not peer_port:
            raise ValueError("peerPing on the native stack requires peer_id and multiaddr")
        return self._runP2PAction("peerPing", peer_id=peer_ip, multiaddr=peer_port)

    def peerGetFile(self, peer_ip, peer_port, site, filename, benchmark=False, p2p=True):
        self._requireP2P(p2p)
        return self._runP2PAction(
            "peerGetFile", peer_id=peer_ip, multiaddr=peer_port,
            site=site, inner_path=filename, benchmark=benchmark,
        )

    def peerCmd(self, peer_ip, peer_port, cmd, parameters, p2p=True):
        self._requireP2P(p2p)
        import json
        params = json.loads(parameters.replace("'", '"')) if parameters else {}
        return self._runP2PAction(
            "peerCmd", peer_id=peer_ip, multiaddr=peer_port, cmd=cmd, params=params,
        )

    def getConfig(self, p2p=True):
        import json
        print(json.dumps(config.getServerInfo(), indent=2, ensure_ascii=False))

    def test(self, test_name, *args, **kwargs):
        import types
        def funcToName(func_name):
            test_name = func_name.replace("test", "")
            return test_name[0].lower() + test_name[1:]

        test_names = [funcToName(name) for name in dir(self) if name.startswith("test") and name != "test"]
        if not test_name:
            # No test specificed, list tests
            print("\nNo test specified, possible tests:")
            for test_name in test_names:
                func_name = "test" + test_name[0].upper() + test_name[1:]
                func = getattr(self, func_name)
                if func.__doc__:
                    print("- %s: %s" % (test_name, func.__doc__.strip()))
                else:
                    print("- %s" % test_name)
            return None

        # Run tests
        func_name = "test" + test_name[0].upper() + test_name[1:]
        if hasattr(self, func_name):
            func = getattr(self, func_name)
            print("- Running test: %s" % test_name, end="")
            s = time.time()
            ret = func(*args, **kwargs)
            if type(ret) is types.GeneratorType:
                for progress in ret:
                    print(progress, end="")
                    sys.stdout.flush()
            print("\n* Test %s done in %.3fs" % (test_name, time.time() - s))
        else:
            print("Unknown test: %r (choose from: %s)" % (
                test_name, test_names
            ))
