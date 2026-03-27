import logging
import re
import socket
import binascii
import sys
import os
import time
import random
import subprocess
import atexit

import gevent

from Config import config
from Crypt import CryptRsa
from Crypt import ed25519
from Site import SiteManager
import socks
from gevent.lock import RLock
from Debug import Debug
from Plugin import PluginManager


@PluginManager.acceptPlugins
class TorManager(object):
    def __init__(self, fileserver_ip=None, fileserver_port=None):
        self.privatekeys = {}  # Onion: Privatekey
        self.site_onions = {}  # Site address: Onion
        # Handle PyInstaller bundled paths (_internal directory on Windows)
        # Determine the correct Tor executable name based on platform
        if sys.platform.startswith("win"):
            tor_exe_name = "tor.exe"
            meek_client_name = "meek-client.exe"
        elif sys.platform == "darwin":
            tor_exe_name = "tor"
            meek_client_name = "meek-client"
        else:  # Linux and other Unix-like systems
            tor_exe_name = "tor"
            meek_client_name = "meek-client"

        if hasattr(sys, '_MEIPASS'):
            # Running as frozen PyInstaller executable
            self.tor_exe = os.path.join(sys._MEIPASS, "tools", "tor", tor_exe_name)
        else:
            # Running from source
            self.tor_exe = os.path.join("tools", "tor", tor_exe_name)
        self.has_meek_bridges = os.path.isfile(os.path.join(os.path.dirname(self.tor_exe), "PluggableTransports", meek_client_name))
        self.tor_process = None
        self.log = logging.getLogger("TorManager")
        self.start_onions = None
        self.conn = None
        self.lock = RLock()
        self.starting = True
        self.connecting = True
        self.status = None
        self.event_started = gevent.event.AsyncResult()

        if config.tor == "disable":
            self.enabled = False
            self.start_onions = False
            self.setStatus("Disabled")
        else:
            self.enabled = True
            self.setStatus("Waiting")

        if fileserver_port:
            self.fileserver_port = fileserver_port
        else:
            self.fileserver_port = config.fileserver_port

        self.ip, self.port = config.tor_controller_split()
        self.proxy_ip, self.proxy_port = config.tor_proxy_split()

    def start(self):
        self.log.debug("Starting (Tor: %s)" % config.tor)
        self.starting = True
        try:
            if not self.connect():
                raise Exception(self.status)
            self.log.debug("Tor proxy port %s check ok" % config.tor_proxy)
        except Exception as err:
            if sys.platform.startswith("win") and os.path.isfile(self.tor_exe):
                self.log.info("Starting self-bundled Tor, due to Tor proxy port %s check error: %s" % (config.tor_proxy, err))
                # Change to self-bundled Tor ports
                self.port = 49051
                self.proxy_port = 49050
                if config.tor == "always":
                    socks.setdefaultproxy(socks.PROXY_TYPE_SOCKS5, "127.0.0.1", self.proxy_port)
                self.enabled = True
                if not self.connect():
                    self.startTor()
            else:
                self.log.info("Disabling Tor, because error while accessing Tor proxy at port %s: %s" % (config.tor_proxy, err))
                self.enabled = False

    def setStatus(self, status):
        self.status = status
        if "main" in sys.modules: # import main has side-effects, breaks tests
            import main
            if "ui_server" in dir(main):
                main.ui_server.updateWebsocket()

    def startTor(self):
        if sys.platform.startswith("win") or sys.platform == "darwin" or sys.platform.startswith("linux"):
            try:
                self.log.info("Starting Tor client %s..." % self.tor_exe)
                tor_dir = os.path.dirname(self.tor_exe)

                # Create data directory in user's writable data directory, not in bundled tools
                # This avoids permission issues when installed in Program Files on Windows
                data_dir = os.path.join(config.data_dir, "tor")
                os.makedirs(data_dir, exist_ok=True)

                # Build command based on platform
                if sys.platform.startswith("win"):
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    cmd = r'"%s" --defaults-torrc torrc-defaults --ignore-missing-torrc' % self.tor_exe
                    cmd += r' --DataDirectory "%s"' % data_dir
                    cmd += r' --ControlPort 127.0.0.1:%d' % self.port
                    cmd += r' --SocksPort 127.0.0.1:%d' % self.proxy_port
                    cmd += r' --CookieAuthentication 1'
                    # Add log file path to avoid issues with relative paths in torrc-defaults
                    log_file = os.path.join(data_dir, "notice.log")
                    cmd += r' --Log "notice file %s"' % log_file
                    if config.tor_use_bridges:
                        cmd += " --UseBridges 1"
                    self.log.debug("Tor command: %s" % cmd)
                    self.tor_process = subprocess.Popen(cmd, cwd=tor_dir, close_fds=True, startupinfo=startupinfo)
                else:
                    # Mac and Linux
                    cmd = [self.tor_exe, "--defaults-torrc", "torrc-defaults", "--ignore-missing-torrc"]
                    cmd += ["--DataDirectory", data_dir]
                    cmd += ["--ControlPort", "127.0.0.1:%d" % self.port]
                    cmd += ["--SocksPort", "127.0.0.1:%d" % self.proxy_port]
                    cmd += ["--CookieAuthentication", "1"]
                    # Add log file path to avoid issues with relative paths in torrc-defaults
                    log_file = os.path.join(data_dir, "notice.log")
                    cmd += ["--Log", "notice file %s" % log_file]
                    if config.tor_use_bridges:
                        cmd += ["--UseBridges", "1"]
                    self.log.debug("Tor command: %s" % " ".join(cmd))
                    self.tor_process = subprocess.Popen(cmd, cwd=tor_dir, close_fds=True)

                for wait in range(1, 3):  # Wait for startup
                    time.sleep(wait * 0.5)
                    self.enabled = True
                    if self.connect():
                        if self.isSubprocessRunning():
                            self.request("TAKEOWNERSHIP")  # Shut down Tor client when controll connection closed
                        break
                # Terminate on exit
                atexit.register(self.stopTor)
            except Exception as err:
                self.log.error("Error starting Tor client: %s" % Debug.formatException(str(err)))
                self.enabled = False
        self.starting = False
        self.event_started.set(False)
        return False

    def isSubprocessRunning(self):
        return self.tor_process and self.tor_process.pid and self.tor_process.poll() is None

    def stopTor(self):
        self.log.debug("Stopping...")
        try:
            if self.isSubprocessRunning():
                self.request("SIGNAL SHUTDOWN")
        except Exception as err:
            self.log.error("Error stopping Tor: %s" % err)

    def connect(self):
        if not self.enabled:
            return False
        self.site_onions = {}
        self.privatekeys = {}

        return self.connectController()

    def connectController(self):
        if "socket_noproxy" in dir(socket):  # Socket proxy-patched, use non-proxy one
            conn = socket.socket_noproxy(socket.AF_INET, socket.SOCK_STREAM)
        else:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.log.debug("Connecting to Tor Controller %s:%s" % (self.ip, self.port))
        self.connecting = True
        try:
            with self.lock:
                conn.connect((self.ip, self.port))

                # Auth cookie file
                res_protocol = self.send("PROTOCOLINFO", conn)
                if not res_protocol:
                    raise Exception("PROTOCOLINFO timeout")
                cookie_match = re.search('COOKIEFILE="(.*?)"', res_protocol)

                if config.tor_password:
                    res_auth = self.send('AUTHENTICATE "%s"' % config.tor_password, conn)
                elif cookie_match:
                    cookie_file = cookie_match.group(1).encode("ascii").decode("unicode_escape")

                    # Build list of cookie file locations to try
                    cookie_locations = []

                    # On Windows, if cookie path looks like a Linux/WSL path, try WSL first
                    wsl_cookie = None
                    if sys.platform.startswith("win") and cookie_file.startswith("/"):
                        wsl_cookie = cookie_file

                    if os.path.isfile(cookie_file):
                        cookie_locations.append(cookie_file)

                    if self.tor_process:
                        # Workaround for tor client cookie auth file utf8 encoding bug
                        if sys.platform.startswith("win"):
                            cookie_locations.append(os.path.dirname(self.tor_exe) + "\\data\\control_auth_cookie")
                        else:
                            cookie_locations.append(os.path.join(os.path.dirname(self.tor_exe), "data", "control_auth_cookie"))

                    # Try each location until we find one that works
                    auth_success = False

                    # Try WSL path FIRST if detected (for Windows with WSL Tor)
                    if wsl_cookie:
                        try:
                            self.log.debug("Trying WSL cookie file: %s" % wsl_cookie)
                            # Use WSL to read the cookie file
                            import subprocess
                            cookie_data = subprocess.check_output(["wsl", "-e", "cat", wsl_cookie])
                            auth_hex = binascii.b2a_hex(cookie_data)
                            res_auth = self.send("AUTHENTICATE %s" % auth_hex.decode("utf8"), conn)
                            if res_auth and "250 OK" in res_auth:
                                self.log.info("Tor cookie authentication successful using WSL path: %s" % wsl_cookie)
                                auth_success = True
                        except Exception as err:
                            self.log.debug("WSL cookie file failed: %s" % err)

                    # Try regular file locations if WSL didn't work
                    if not auth_success:
                        for location in cookie_locations:
                            try:
                                if os.path.isfile(location):
                                    self.log.debug("Trying cookie file: %s" % location)
                                    auth_hex = binascii.b2a_hex(open(location, "rb").read())
                                    res_auth = self.send("AUTHENTICATE %s" % auth_hex.decode("utf8"), conn)
                                    if res_auth and "250 OK" in res_auth:
                                        self.log.info("Tor cookie authentication successful using: %s" % location)
                                        auth_success = True
                                        break
                            except Exception as err:
                                self.log.debug("Cookie file %s failed: %s" % (location, err))
                                continue

                    if not auth_success:
                        # Check if no-auth is supported
                        if "METHODS=NULL" in res_protocol:
                            self.log.debug("No accessible cookie file found, trying NULL authentication")
                            res_auth = self.send("AUTHENTICATE", conn)
                        else:
                            raise Exception("Cookie authentication required but no accessible cookie file found")
                else:
                    res_auth = self.send("AUTHENTICATE", conn)

                if not res_auth or "250 OK" not in res_auth:
                    raise Exception("Authenticate error: %s" % (res_auth or "timeout"))

                # Version 0.2.7.5 required because ADD_ONION support
                res_version = self.send("GETINFO version", conn)
                version = re.search(r'version=([0-9\.]+)', res_version).group(1)
                if float(version.replace(".", "0", 2)) < 207.5:
                    raise Exception("Tor version >=0.2.7.5 required, found: %s" % version)

                self.setStatus("Connected (%s)" % res_auth)
                self.event_started.set(True)
                self.starting = False
                self.connecting = False
                self.conn = conn
        except Exception as err:
            self.conn = None
            self.setStatus("Error (%s)" % str(err))
            self.log.warning("Tor controller connect error: %s" % Debug.formatException(str(err)))
            self.enabled = False
        return self.conn

    def disconnect(self):
        if self.conn:
            self.conn.close()
        self.conn = None

    def startOnions(self):
        if self.enabled:
            self.log.debug("Start onions")
            self.start_onions = True
            self.getOnion("global")

    # Get new exit node ip
    def resetCircuits(self):
        res = self.request("SIGNAL NEWNYM")
        if "250 OK" not in res:
            self.setStatus("Reset circuits error (%s)" % res)
            self.log.error("Tor reset circuits error: %s" % res)

    def addOnion(self):
        if len(self.privatekeys) >= config.tor_hs_limit:
            return random.choice([key for key in list(self.privatekeys.keys()) if key != self.site_onions.get("global")])

        result = self.makeOnionAndKey()
        if result:
            onion_address, onion_privatekey = result
            self.privatekeys[onion_address] = onion_privatekey
            self.setStatus("OK (%s onions running)" % len(self.privatekeys))
            SiteManager.peer_blacklist.append((onion_address + ".onion", self.fileserver_port))
            return onion_address
        else:
            return False

    def makeOnionAndKey(self):
        res = self.request(f"ADD_ONION NEW:ED25519-V3 port={self.fileserver_port}")
        match = re.search("ServiceID=([A-Za-z0-9]+).*PrivateKey=ED25519-V3:(.*?)[\r\n]", res, re.DOTALL)
        if match:
            onion_address, onion_privatekey = match.groups()
            return (onion_address, onion_privatekey)
        else:
            self.setStatus("AddOnion error (%s)" % res)
            self.log.error("Tor addOnion error: %s" % res)
            return False

    def delOnion(self, address):
        res = self.request("DEL_ONION %s" % address)
        if "250 OK" in res:
            del self.privatekeys[address]
            self.setStatus("OK (%s onion running)" % len(self.privatekeys))
            return True
        else:
            self.setStatus("DelOnion error (%s)" % res)
            self.log.error("Tor delOnion error: %s" % res)
            self.disconnect()
            return False

    def request(self, cmd):
        with self.lock:
            if not self.enabled:
                return False
            if not self.conn:
                if not self.connect():
                    return ""
            return self.send(cmd)

    def send(self, cmd, conn=None, timeout=5.0):
        if not conn:
            conn = self.conn
        self.log.debug("> %s" % cmd)
        back = ""

        for retry in range(2):
            try:
                # Use gevent timeout for better compatibility with gevent sockets
                with gevent.Timeout(timeout):
                    conn.sendall(b"%s\r\n" % cmd.encode("utf8"))
                    # Wait for response ending with \r\n and starting with a digit (Tor response code)
                    while True:
                        chunk = conn.recv(1024 * 64).decode("utf8")
                        if not chunk:
                            break
                        back += chunk
                        # Check if we have a complete response (ends with \r\n and has response code)
                        if back.endswith("\r\n") and back and back[0].isdigit():
                            break
                break
            except gevent.Timeout:
                self.log.warning("Tor command timed out after %ss: %s" % (timeout, cmd))
                if not self.connecting:
                    self.disconnect()
                back = None
                break  # Don't retry on timeout
            except Exception as err:
                self.log.error("Tor send error: %s, reconnecting..." % err)
                if not self.connecting:
                    self.disconnect()
                    time.sleep(1)
                    self.connect()
                back = None

        if back:
            self.log.debug("< %s" % back.strip())
        return back

    def getPrivatekey(self, address):
        return self.privatekeys[address]

    def getPublickey(self, address):
        return CryptRsa.privatekeyToPublickey(self.privatekeys[address])

    def getOnion(self, site_address):
        if not self.enabled:
            return None

        if config.tor == "always":  # Different onion for every site
            onion = self.site_onions.get(site_address)
        else:  # Same onion for every site
            onion = self.site_onions.get("global")
            site_address = "global"

        if not onion:
            with self.lock:
                self.site_onions[site_address] = self.addOnion()
                onion = self.site_onions[site_address]
                self.log.debug("Created new hidden service for %s: %s" % (site_address, onion))

        return onion

    # Creates and returns a
    # socket that has connected to the Tor Network
    def createSocket(self, onion, port):
        if not self.enabled:
            return False
        self.log.debug("Creating new Tor socket to %s:%s" % (onion, port))
        if self.starting:
            self.log.debug("Waiting for startup...")
            self.event_started.get()
        if config.tor == "always":  # Every socket is proxied by default, in this mode
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        else:
            sock = socks.socksocket()
            sock.set_proxy(socks.SOCKS5, self.proxy_ip, self.proxy_port)
        return sock
