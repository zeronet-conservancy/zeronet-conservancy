import logging
import os
import sys
import gevent
import time
from Config import config
from Plugin import PluginManager

@PluginManager.acceptPlugins
class Actions:
    def call(self, function_name, kwargs):
        logging.info(f'zeronet-conservancy {config.version_full} on Python {sys.version} Gevent {gevent.__version__}')

        func = getattr(self, function_name, None)
        back = func(**kwargs)
        if back:
            print(back)

    def ipythonThread(self):
        import IPython
        IPython.embed()
        self.gevent_quit.set()

    def initDHT(self):
        import main
        if config.dht:
            from DHT import DHTServer
            main.dht_server = DHTServer()
        else:
            main.dht_server = None

    # Default action: Start serving UiServer and FileServer
    def main(self, p2p=False):
        if p2p:
            return self.mainP2P()

        import main
        from File import FileServer
        from Ui import UiServer

        self.initDHT()

        main.file_server = FileServer()
        logging.info("Creating UiServer....")
        main.ui_server = UiServer()
        main.file_server.ui_server = main.ui_server

        # for startup_error in startup_errors:
            # logging.error("Startup error: %s" % startup_error)

        logging.info("Removing old SSL certs...")
        from Crypt import CryptConnection
        CryptConnection.manager.removeCerts()

        logging.info("Starting servers....")

        import threading
        self.gevent_quit = threading.Event()
        launched_greenlets = [
            gevent.spawn(main.ui_server.start),
            gevent.spawn(main.ui_server.startSiteServer),
            gevent.spawn(main.file_server.start),
        ]
        if main.dht_server is not None:
            launched_greenlets.append(gevent.spawn(main.dht_server.start))

        # if --repl, start ipython thread
        # FIXME: Unfortunately this leads to exceptions on exit so use with care
        if config.repl:
            threading.Thread(target=self.ipythonThread).start()

        stopped = 0
        # Process all greenlets in main thread
        while not self.gevent_quit.is_set() and stopped < len(launched_greenlets):
            stopped += len(gevent.joinall(launched_greenlets, timeout=1))

        # Exited due to repl, so must kill greenlets
        if stopped < len(launched_greenlets):
            gevent.killall(launched_greenlets, exception=KeyboardInterrupt)

        logging.info("All server stopped")

    def mainP2P(self):
        """Phase 10 cutover: run the trio-native P2P stack (P2P/app.py's
        App) through the real, official entrypoint -- `zeronet.py main`
        -- instead of only via the standalone `python -m P2P app`
        launcher. This is now the DEFAULT (config.p2p defaults to True
        as of the Config.py flip; pass --no-p2p for the legacy gevent
        server). Known gaps callers relying on the legacy server should
        know about before dropping --no-p2p: the P2P stack doesn't load
        the legacy plugins/ ecosystem (a genuinely different,
        non-overlapping plugin system -- see P2P/plugins/__init__.py).
        UiPassword (--ui-password, a single shared UI password), Tor
        (both control-port AND SOCKS5 dial-out, see P2P/Tor.py's own
        docstring), and Multiuser's core account isolation (--multiuser,
        each browser cookie-identified to its own persisted account, see
        P2P.UserManager's own docstring) are all closed now -- stale gaps
        corrected here, not still open. Multiuser's account-switching and
        master-seed backup/reveal UI (userSet/userSelectForm/userLogin/
        userLoginForm/userLogout/userShowMasterSeed, see P2P/Ui/commands.py)
        is also closed now -- a browser can log into a DIFFERENT existing
        account, or view/export its own seed, not just the one its cookie
        already points at.
        --no-p2p remains a full, unchanged escape hatch to the exact
        previous default behavior -- nothing about the legacy path
        itself changed, only which one runs when no flag is given.

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
        `main.file_server` isn't set, which it never is here (that's a
        legacy-Actions.main()-only global) -- raising SystemExit through
        whatever trio-internal frame happens to be executing when the
        signal arrives corrupts trio's run loop (surfaces as a "Trio
        guest run got abandoned" RuntimeWarning at shutdown, a real bug
        caught while testing this slice). trio.open_signal_receiver()
        temporarily installs its own handler for the scope of this run
        (restoring whatever was there before on exit) and delivers
        signals as a normal async iterator instead, so cancellation goes
        through trio's own structured-shutdown path.
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
        """Shared plumbing for every siteX(p2p=True)/dbX(p2p=True)
        delegation below: constructs a throwaway P2P.actions.Actions and
        runs one of its methods to completion via P2P.compat.run() (see
        mainP2P()'s own docstring for why that bracketing is needed).
        Each P2P.actions method already handles its own SiteManager/
        UserManager loading and FileServer lifecycle per call, so a
        fresh instance per CLI invocation is correct, not wasteful --
        matches how the legacy methods below already re-derive
        everything from config.data_dir/SiteManager.site_manager.load()
        on each call too."""
        from P2P import compat
        from P2P.PluginManager import plugin_manager as p2p_plugin_manager
        p2p_plugin_manager.loadPlugins()
        from P2P.actions import Actions as P2PActions

        async def _call():
            p2p_actions = P2PActions(config.data_dir)
            return await getattr(p2p_actions, method_name)(**kwargs)

        return compat.run(_call)

    # Site commands

    def siteCreate(self, use_master_seed=True, p2p=False):
        if p2p:
            return self._runP2PAction("siteCreate", use_master_seed=use_master_seed)

        logging.info("Generating new privatekey (use_master_seed: %s)..." % config.use_master_seed)
        from Crypt import CryptBitcoin
        if use_master_seed:
            from User import UserManager
            user = UserManager.user_manager.get()
            if not user:
                user = UserManager.user_manager.create()
            address, address_index, site_data = user.getNewSiteData()
            privatekey = site_data["privatekey"]
            logging.info("Generated using master seed from users.json, site index: %s" % address_index)
        else:
            privatekey = CryptBitcoin.newPrivatekey()
            address = CryptBitcoin.privatekeyToAddress(privatekey)
        logging.info("----------------------------------------------------------------------")
        logging.info("Site private key: %s" % privatekey)
        logging.info("                  !!! ^ Save it now, required to modify the site ^ !!!")
        logging.info("Site address:     %s" % address)
        logging.info("----------------------------------------------------------------------")

        while True and not config.batch and not use_master_seed:
            if input("? Have you secured your private key? (yes, no) > ").lower() == "yes":
                break
            else:
                logging.info("Please, secure it now, you going to need it to modify your site!")

        logging.info("Creating directory structure...")
        from Site.Site import Site
        from Site import SiteManager
        SiteManager.site_manager.load()

        (config.data_dir / address).mkdir()
        (config.data_dir / address / 'index.html').open('w').write(f"Hello {address}!")

        logging.info("Creating content.json...")
        site = Site(address)
        extend = {"postmessage_nonce_security": True}
        if use_master_seed:
            extend["address_index"] = address_index

        site.content_manager.sign(privatekey=privatekey, extend=extend)
        site.settings["own"] = True
        site.saveSettings()

        logging.info("Site created!")

    def siteSign(self, address, privatekey=None, inner_path="content.json", publish=False,
                 remove_missing_optional=False, p2p=False):
        if p2p:
            return self._runP2PAction("siteSign", address=address, privatekey=privatekey, publish=publish)

        from Site.Site import Site
        from Site import SiteManager
        from Debug import Debug
        SiteManager.site_manager.load()
        logging.info("Signing site: %s..." % address)
        site = Site(address, allow_create=False)

        if not privatekey:  # If no privatekey defined
            from User import UserManager
            user = UserManager.user_manager.get()
            if user:
                site_data = user.getSiteData(address)
                privatekey = site_data.get("privatekey")
            else:
                privatekey = None
            if not privatekey:
                # Not found in users.json, ask from console
                import getpass
                privatekey = getpass.getpass("Private key (input hidden):")
        # inner_path can be either relative to site directory or absolute/relative path
        if os.path.isabs(inner_path):
            full_path = os.path.abspath(inner_path)
        else:
            full_path = os.path.abspath(config.working_dir + '/' + inner_path)
        print(full_path)
        if os.path.isfile(full_path):
            if address in full_path:
                # assuming site address is unique, keep only path after it
                inner_path = full_path.split(address+'/')[1]
            else:
                # oops, file that we found seems to be rogue, so reverting to old behaviour
                logging.warning(f'using {inner_path} relative to site directory')
        try:
            succ = site.content_manager.sign(
                inner_path=inner_path, privatekey=privatekey,
                update_changed_files=True, remove_missing_optional=remove_missing_optional
            )
        except Exception as err:
            logging.error("Sign error: %s" % Debug.formatException(err))
            succ = False
        if succ and publish:
            self.sitePublish(address, inner_path=inner_path)

    def siteVerify(self, address, p2p=False):
        if p2p:
            return self._runP2PAction("siteVerify", address=address)

        import time
        from Site.Site import Site
        from Site import SiteManager
        SiteManager.site_manager.load()

        s = time.time()
        logging.info("Verifing site: %s..." % address)
        site = Site(address)
        bad_files = []

        for content_inner_path in site.content_manager.contents:
            s = time.time()
            logging.info("Verifing %s signature..." % content_inner_path)
            error = None
            try:
                file_correct = site.content_manager.verifyFile(
                    content_inner_path, site.storage.open(content_inner_path, "rb"), ignore_same=False
                )
            except Exception as err:
                file_correct = False
                error = err

            if file_correct is True:
                logging.info("[OK] %s (Done in %.3fs)" % (content_inner_path, time.time() - s))
            else:
                logging.error("[ERROR] %s: invalid file: %s!" % (content_inner_path, error))
                input("Continue?")
                bad_files += content_inner_path

        logging.info("Verifying site files...")
        bad_files += site.storage.verifyFiles()["bad_files"]
        if not bad_files:
            logging.info("[OK] All file sha512sum matches! (%.3fs)" % (time.time() - s))
        else:
            logging.error("[ERROR] Error during verifying site files!")

    def dbRebuild(self, address, p2p=False):
        if p2p:
            return self._runP2PAction("dbRebuild", address=address)

        from Site.Site import Site
        from Site import SiteManager
        SiteManager.site_manager.load()

        logging.info("Rebuilding site sql cache: %s..." % address)
        site = SiteManager.site_manager.get(address)
        s = time.time()
        try:
            site.storage.rebuildDb()
            logging.info("Done in %.3fs" % (time.time() - s))
        except Exception as err:
            logging.error(err)

    def dbQuery(self, address, query, p2p=False):
        if p2p:
            return self._runP2PAction("dbQuery", address=address, query=query)

        from Site.Site import Site
        from Site import SiteManager
        SiteManager.site_manager.load()

        import json
        site = Site(address)
        result = []
        for row in site.storage.query(query):
            result.append(dict(row))
        print(json.dumps(result, indent=4))

    def siteAnnounce(self, address, p2p=False):
        if p2p:
            return self._runP2PAction("siteAnnounce", address=address, enable_dht=config.dht)

        import main
        self.initDHT()

        from Site.Site import Site
        from Site import SiteManager
        SiteManager.site_manager.load()

        logging.info("Opening a simple connection server")
        from File import FileServer
        main.file_server = FileServer("127.0.0.1", 1234)
        main.file_server.start()

        logging.info("Announcing site %s to tracker..." % address)
        site = Site(address)

        s = time.time()
        site.announce()
        print("Response time: %.3fs" % (time.time() - s))
        print(site.peers)

    def siteDownload(self, address, p2p=False):
        if p2p:
            return self._runP2PAction("siteDownload", address=address, enable_dht=config.dht)

        import main
        self.initDHT()

        from Site.Site import Site
        from Site import SiteManager
        SiteManager.site_manager.load()

        logging.info("Opening a simple connection server")
        from File import FileServer
        main.file_server = FileServer("127.0.0.1", 1234)

        launched_greenlets = [
            gevent.spawn(main.file_server.start, check_sites=False),
        ]
        if main.dht_server is not None:
            launched_greenlets.append(gevent.spawn(main.dht_server.start))

        site = Site(address)

        on_completed = gevent.event.AsyncResult()

        def onComplete(evt):
            evt.set(True)

        site.onComplete.once(lambda: onComplete(on_completed))
        print("Announcing...")
        site.announce()

        s = time.time()
        print("Downloading...")
        site.downloadContent("content.json", check_modifications=True)

        print("Downloaded in %.3fs" % (time.time()-s))

    def siteNeedFile(self, address, inner_path, p2p=False):
        if p2p:
            return self._runP2PAction("siteNeedFile", address=address, inner_path=inner_path, enable_dht=config.dht)

        import main
        self.initDHT()

        from Site.Site import Site
        from Site import SiteManager
        SiteManager.site_manager.load()

        def checker():
            while 1:
                s = time.time()
                time.sleep(1)
                print("Switch time:", time.time() - s)
        gevent.spawn(checker)

        logging.info("Opening a simple connection server")
        from File import FileServer
        main.file_server = FileServer("127.0.0.1", 1234)
        file_server_thread = gevent.spawn(main.file_server.start, check_sites=False)

        site = Site(address)
        site.announce()
        print(site.needFile(inner_path, update=True))

    def siteCmd(self, address, cmd, parameters, wrapper_key=None, ui_host=None, ui_port=None, p2p=True):
        if p2p:
            if not wrapper_key:
                raise ValueError("siteCmd on the native stack requires --wrapper-key")
            import json
            params = json.loads(parameters.replace("'", '"')) if parameters else {}
            return self._runP2PAction(
                "siteCmd", cmd=cmd, wrapper_key=wrapper_key, params=params,
                ui_host=ui_host or config.ui_ip, ui_port=ui_port or config.ui_port,
            )

        import json
        from Site import SiteManager

        site = SiteManager.site_manager.get(address)

        if not site:
            logging.error("Site not found: %s" % address)
            return None

        ws = self.getWebsocket(site)

        ws.send(json.dumps({"cmd": cmd, "params": parameters, "id": 1}))
        res_raw = ws.recv()

        try:
            res = json.loads(res_raw)
        except Exception as err:
            return {"error": "Invalid result: %s" % err, "res_raw": res_raw}

        if "result" in res:
            return res["result"]
        else:
            return res

    def importBundle(self, bundle, p2p=True):
        if p2p:
            return self._runP2PAction("importBundle", bundle=bundle)

        import main
        main.importBundle(bundle)

    def getWebsocket(self, site):
        import websocket

        ws_address = "ws://%s:%s/Websocket?wrapper_key=%s" % (config.ui_ip, config.ui_port, site.settings["wrapper_key"])
        logging.info("Connecting to %s" % ws_address)
        ws = websocket.create_connection(ws_address)
        return ws

    def sitePublish(self, address, peer_ip=None, peer_port=15441, inner_path="content.json", recursive=False,
                     p2p=False):
        if p2p:
            return self._runP2PAction("sitePublish", address=address, inner_path=inner_path, enable_dht=config.dht)

        from Site import SiteManager
        logging.info("Loading site...")
        site = SiteManager.site_manager.get(address)
        site.settings["serving"] = True  # Serving the site even if its disabled

        if not recursive:
            inner_paths = [inner_path]
        else:
            inner_paths = list(site.content_manager.contents.keys())

        try:
            ws = self.getWebsocket(site)

        except Exception as err:
            self.sitePublishFallback(site, peer_ip, peer_port, inner_paths, err)

        else:
            logging.info("Sending siteReload")
            self.siteCmd(address, "siteReload", inner_path)

            for inner_path in inner_paths:
                logging.info(f"Sending sitePublish for {inner_path}")
                self.siteCmd(address, "sitePublish", {"inner_path": inner_path, "sign": False})
            logging.info("Done.")
            ws.close()

    def sitePublishFallback(self, site, peer_ip, peer_port, inner_paths, err):
        import main
        if err is not None:
            logging.info(f"Can't connect to local websocket client: {err}")
        logging.info("Publish using fallback mechanism. "
                     "Note that there might be not enough time for peer discovery, "
                     "but you can specify target peer on command line.")
        logging.info("Creating FileServer....")
        file_server_thread = gevent.spawn(main.file_server.start, check_sites=False)  # Dont check every site integrity
        time.sleep(0.001)

        # Started fileserver
        main.file_server.portCheck()
        if peer_ip:  # Announce ip specificed
            site.addPeer(peer_ip, peer_port)
        else:  # Just ask the tracker
            logging.info("Gathering peers from tracker")
            site.announce()  # Gather peers

        for inner_path in inner_paths:
            published = site.publish(5, inner_path)  # Push to peers

        if published > 0:
            time.sleep(3)
            logging.info("Serving files (max 60s)...")
            gevent.joinall([file_server_thread], timeout=60)
            logging.info("Done.")
        else:
            logging.info("No peers found, sitePublish command only works if you already have visitors serving your site")

    # Crypto commands
    def cryptPrivatekeyToAddress(self, privatekey=None, p2p=True):
        if p2p:
            if not privatekey:
                import getpass
                privatekey = getpass.getpass("Private key (input hidden):")
            return self._runP2PAction("cryptPrivatekeyToAddress", privatekey=privatekey)

        from Crypt import CryptBitcoin
        if not privatekey:  # If no privatekey in args then ask it now
            import getpass
            privatekey = getpass.getpass("Private key (input hidden):")

        print(CryptBitcoin.privatekeyToAddress(privatekey))

    def cryptSign(self, message, privatekey, p2p=True):
        if p2p:
            return self._runP2PAction("cryptSign", message=message, privatekey=privatekey)

        from Crypt import CryptBitcoin
        print(CryptBitcoin.sign(message, privatekey))

    def cryptVerify(self, message, sign, address, p2p=True):
        if p2p:
            return self._runP2PAction("cryptVerify", message=message, sign=sign, address=address)

        from Crypt import CryptBitcoin
        print(CryptBitcoin.verify(message, address, sign))

    def cryptGetPrivatekey(self, master_seed, site_address_index=None, p2p=True):
        if p2p:
            return self._runP2PAction(
                "cryptGetPrivatekey", master_seed=master_seed,
                site_address_index=site_address_index,
            )

        from Crypt import CryptBitcoin
        if len(master_seed) != 64:
            logging.error("Error: Invalid master seed length: %s (required: 64)" % len(master_seed))
            return False
        privatekey = CryptBitcoin.hdPrivatekey(master_seed, site_address_index)
        print("Requested private key: %s" % privatekey)

    # Peer
    def peerPing(self, peer_ip, peer_port=None, p2p=True):
        if p2p:
            if not peer_port:
                raise ValueError("peerPing on the native stack requires peer_id and multiaddr")
            return self._runP2PAction("peerPing", peer_id=peer_ip, multiaddr=peer_port)

        import main
        if not peer_port:
            peer_port = 15441
        logging.info("Opening a simple connection server")
        from Connection import ConnectionServer
        main.file_server = ConnectionServer("127.0.0.1", 1234)
        main.file_server.start(check_connections=False)
        from Crypt import CryptConnection
        CryptConnection.manager.loadCerts()

        from Peer import Peer
        logging.info("Pinging 5 times peer: %s:%s..." % (peer_ip, int(peer_port)))
        s = time.time()
        peer = Peer(peer_ip, peer_port)
        peer.connect()

        if not peer.connection:
            print("Error: Can't connect to peer (connection error: %s)" % peer.connection_error)
            return False
        if "shared_ciphers" in dir(peer.connection.sock):
            print("Shared ciphers:", peer.connection.sock.shared_ciphers())
        if "cipher" in dir(peer.connection.sock):
            print("Cipher:", peer.connection.sock.cipher()[0])
        if "version" in dir(peer.connection.sock):
            print("TLS version:", peer.connection.sock.version())
        print("Connection time: %.3fs  (connection error: %s)" % (time.time() - s, peer.connection_error))

        for i in range(5):
            ping_delay = peer.ping()
            print("Response time: %.3fs" % ping_delay)
            time.sleep(1)
        peer.remove()
        print("Reconnect test...")
        peer = Peer(peer_ip, peer_port)
        for i in range(5):
            ping_delay = peer.ping()
            print("Response time: %.3fs" % ping_delay)
            time.sleep(1)

    def peerGetFile(self, peer_ip, peer_port, site, filename, benchmark=False, p2p=True):
        if p2p:
            return self._runP2PAction(
                "peerGetFile", peer_id=peer_ip, multiaddr=peer_port,
                site=site, inner_path=filename, benchmark=benchmark,
            )

        import main
        logging.info("Opening a simple connection server")
        from Connection import ConnectionServer
        main.file_server = ConnectionServer("127.0.0.1", 1234)
        main.file_server.start(check_connections=False)
        from Crypt import CryptConnection
        CryptConnection.manager.loadCerts()

        from Peer import Peer
        logging.info("Getting %s/%s from peer: %s:%s..." % (site, filename, peer_ip, peer_port))
        peer = Peer(peer_ip, peer_port)
        s = time.time()
        if benchmark:
            for i in range(10):
                peer.getFile(site, filename),
            print("Response time: %.3fs" % (time.time() - s))
            input("Check memory")
        else:
            print(peer.getFile(site, filename).read())

    def peerCmd(self, peer_ip, peer_port, cmd, parameters, p2p=True):
        if p2p:
            import json
            params = json.loads(parameters.replace("'", '"')) if parameters else {}
            return self._runP2PAction(
                "peerCmd", peer_id=peer_ip, multiaddr=peer_port, cmd=cmd, params=params,
            )

        import main
        logging.info("Opening a simple connection server")
        from Connection import ConnectionServer
        main.file_server = ConnectionServer()
        main.file_server.start(check_connections=False)
        from Crypt import CryptConnection
        CryptConnection.manager.loadCerts()

        from Peer import Peer
        peer = Peer(peer_ip, peer_port)

        import json
        if parameters:
            parameters = json.loads(parameters.replace("'", '"'))
        else:
            parameters = {}
        try:
            res = peer.request(cmd, parameters)
            print(json.dumps(res, indent=2, ensure_ascii=False))
        except Exception as err:
            print("Unknown response (%s): %s" % (err, res))

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
