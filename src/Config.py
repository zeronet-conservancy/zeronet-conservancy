import argparse
from argparse import BooleanOptionalAction
import sys
import os
import platform
import locale
import re
import configparser
import logging
import logging.handlers
import stat
import time
from pathlib import Path
from rich import print

VERSION = "0.8-alpha"

class StartupError(RuntimeError):
    def __init__(self, message, *paths):
        super().__init__(self, f"Startup error: {message}, paths: {paths}")

class Config:
    """Class responsible for storing and loading config.

    Used as singleton `config`
    """

    def __init__(self, argv):
        try:
            from . import BuildInfo
        except ImportError:
            from .util import Git
            self.build_type = 'source'
            self.branch = Git.branch() or 'unknown'
            self.commit = Git.commit() or 'unknown'
            self.version = VERSION
            self.platform = 'source'
        else:
            self.build_type = BuildInfo.build_type
            self.branch = BuildInfo.branch
            self.commit = BuildInfo.commit
            self.version = BuildInfo.version or VERSION
            self.platform = BuildInfo.platform
        self.version_full = f'{self.version} ({self.build_type} from {self.branch}-{self.commit})'
        self.user_agent = "conservancy"
        # for compatibility
        self.user_agent_rev = 8192
        self.argv = argv
        self.action = None
        self.test_parser = None
        self.pending_changes = {}
        self.need_restart = False
        self.keys_api_change_allowed = set([
            "tor", "fileserver_port", "language", "tor_use_bridges", "trackers_proxy", "trackers",
            "trackers_file", "open_browser", "log_level", "fileserver_ip_type", "ip_external", "offline",
            "threads_fs_read", "threads_fs_write", "threads_crypt", "threads_db"
        ])
        self.keys_restart_need = set([
            "tor", "fileserver_port", "fileserver_ip_type", "threads_fs_read", "threads_fs_write", "threads_crypt", "threads_db"
        ])

        self.config_file = None
        self.config_dir = None
        self.data_dir = None
        self.private_dir = None
        self.log_dir = None
        self.configurePaths(argv)

        self.openssl_lib_file = None
        self.openssl_bin_file = None

        self.trackers_file = None
        self.createParser()
        self.createArguments()
        self.parseCommandline('')
        self.setAttributes()

    def createParser(self):
        # Create parser
        self.parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser.register('type', 'bool', self.strToBool)
        self.subparsers = self.parser.add_subparsers(title="Action to perform", dest="action")

    def __str__(self):
        return str(self.arguments).replace("Namespace", "Config")  # Using argparse str output

    def strToBool(self, v):
        """Convert option string to bool"""
        if v.lower() in ('y', 'yes', 'true', 't', '1', 'on'):
            return True
        if v.lower() in ('n', 'no', 'false', 'f', '0', 'off'):
            return False
        raise ValueError(f'Incorrect bool value "{v}"')

    def getStartDirOld(self):
        """Get directory that would have been used by older versions (pre v0.7.11)"""
        this_file = os.path.abspath(__file__).replace("\\", "/").rstrip("cd")

        if "--start-dir" in self.argv:
            start_dir = self.argv[self.argv.index("--start-dir") + 1]
        elif this_file.endswith("/Contents/Resources/core/src/Config.py"):
            # Running as ZeroNet.app
            if this_file.startswith("/Application") or this_file.startswith("/private") or this_file.startswith(os.path.expanduser("~/Library")):
                # Runnig from non-writeable directory, put data to Application Support
                start_dir = os.path.expanduser("~/Library/Application Support/ZeroNet")
            else:
                # Running from writeable directory put data next to .app
                start_dir = re.sub("/[^/]+/Contents/Resources/core/src/Config.py", "", this_file)
        elif this_file.endswith("/core/src/Config.py"):
            # Running as exe or source is at Application Support directory, put var files to outside of core dir
            start_dir = this_file.replace("/core/src/Config.py", "")
        elif not os.access(this_file.replace('/src/Config.py', ''), os.R_OK | os.W_OK):
            # Running from non-writeable location, e.g., AppImage
            start_dir = os.path.expanduser("~/ZeroNet")
        else:
            start_dir = "."
        return start_dir

    def migrateOld(self, source):
        print(f'[bold red]WARNING: found data {source}[/bold red]')
        print( '  It used to be default behaviour to store data there,')
        print( '  but now we default to place data and config in user home directory.')
        print( '')

    def configurePaths(self, argv):
        if '--config-file' in argv:
            self.config_file = argv[argv.index('--config-file') + 1]
        old_dir = Path(self.getStartDirOld())
        new_dir = Path(self.getStartDir())
        # Disable migration by default
        do_migrate = '--migrate' in argv
        no_migrate = not do_migrate
        silent = '--no-migrate' in argv
        try:
            self.start_dir = self.maybeMigrate(old_dir, new_dir, no_migrate, silent)
        except Exception as ex:
            raise ex

        self.updatePaths()

    def updatePaths(self):
        if self.config_file is None:
            self.config_file = self.start_dir / 'znc.conf'
        if self.config_dir is None:
            self.config_dir = self.start_dir
        if self.private_dir is None:
            self.private_dir = self.start_dir / 'private'
        if self.data_dir is None:
            self.data_dir = self.start_dir / 'data'
        if self.log_dir is None:
            self.log_dir = self.start_dir / 'log'

    def createPaths(self):
        self.start_dir.mkdir(parents=True, exist_ok=True)
        self.private_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def checkDir(self, root):
        return (root / 'znc.conf').is_file()

    def doMigrate(self, old_dir, new_dir):
        raise StartupError('Migration not implemented yet')

    def askMigrate(self, old_dir, new_dir, silent):
        if not sys.stdin.isatty():
            raise StartupError("Migration refused: non-interactive shell, can't ask")
        while True:
            r = input(f'You have old data in `{old_dir}`. Migrate to new format to `{new_dir}`? [Y/n]')
            if r.lower().startswith('n'):
                raise StartupError('Migration refused (start with --no-migrate to avoid migration altogether)')
            if r.lower().startswith('y'):
                return self.doMigrate(old_dir, new_dir)

    def createNewConfig(self, new_dir):
        new_dir.mkdir(parents=True, exist_ok=True)
        with (new_dir / 'znc.conf').open('w') as f:
            f.write('# zeronet-conervancy config file')

    def maybeMigrate(self, old_dir, new_dir, no_migrate, silent):
        if (old_dir / 'zeronet.conf').exists() and new_dir.exists():
            if old_dir == new_dir:
                if self.checkDir(new_dir):
                    return new_dir
                elif no_migrate:
                    return StartupError("Migration refused, but new directory should be migrated (old_dir == new_dir)", old_dir)
                else:
                    return askMigrate(old_dir, new_dir, silent_migrate)
            else:
                if self.checkDir(new_dir):
                    if not no_migrate:
                        print("[bold red]WARNING: There's an old starting directory, ignoring[/bold red]")
                    return new_dir
                else:
                    raise StartupError('Bad startup directory')
        elif (old_dir / 'zeronet.conf').exists():
            if no_migrate:
                if not silent:
                    print("[bold red]WARNING: There's an old starting directory, ignoring[/bold red]")
                self.createNewConfig(new_dir)
                return new_dir
            else:
                return self.askMigrate(old_dir, new_dir, silent_migrate)
        elif new_dir.exists():
            if self.checkDir(new_dir):
                return new_dir
            elif not any(new_dir.iterdir()):
                self.createNewConfig(new_dir)
                return new_dir
            else:
                raise StartupError("Bad startup directory", new_dir)
        else:
            self.createNewConfig(new_dir)
            return new_dir

    def getStartDir(self):
        """Return directory with config & data"""
        if "--start-dir" in self.argv:
            return self.argv[self.argv.index("--start-dir") + 1]

        here = os.path.dirname(os.path.abspath(__file__).replace("\\", "/")).rstrip('/src')
        if '--portable' in self.argv or self.build_type == 'portable':
            return here

        MACOSX_DIR = '~/Library/Application Support/zeronet-conservancy'
        WINDOWS_DIR = '~/AppData/zeronet-conservancy'
        LIBREDESKTOP_DIR = '~/.local/share/zeronet-conservancy'
        if self.platform == 'source':
            if platform.system() == 'Darwin':
                path = MACOSX_DIR
            elif platform.system() == 'Windows':
                path = WINDOWS_DIR
            else:
                path = LIBREDESKTOP_DIR
        elif self.platform == 'macosx':
            path = MACOSX_DIR
        elif self.platform == 'windows':
            path = WINDOWS_DIR
        elif self.platform == 'libredesktop':
            path = LIBREDESKTOP_DIR
        else:
            raise RuntimeError(f'UNKNOWN PLATFORM: {self.platform}. Something must have went terribly wrong!')
        return os.path.expanduser(path)

    # Create command line arguments
    def createArguments(self):
        try:
            language, enc = locale.getdefaultlocale()
            language = language.lower().replace("_", "-")
            if language not in ["pt-br", "zh-tw"]:
                language = language.split("-")[0]
        except Exception:
            language = "en"

        use_openssl = True

        if repr(1483108852.565) != "1483108852.565":  # Fix for weird Android issue
            fix_float_decimals = True
        else:
            fix_float_decimals = False

        config_file = self.config_file
        data_dir = self.data_dir
        log_dir = self.log_dir

        ip_local = ["127.0.0.1", "::1"]

        # Main
        action = self.subparsers.add_parser("main", help='Start UiServer and FileServer (default)')

        # SiteCreate
        action = self.subparsers.add_parser("siteCreate", help='Create a new site')
        action.register('type', 'bool', self.strToBool)
        action.add_argument('--use-master_seed', help="Allow created site's private key to be recovered using the master seed in users.json (default: True)", type="bool", choices=[True, False], default=True)

        # SiteNeedFile
        action = self.subparsers.add_parser("siteNeedFile", help='Get a file from site')
        action.add_argument('address', help='Site address')
        action.add_argument('inner_path', help='File inner path')

        # SiteDownload
        action = self.subparsers.add_parser("siteDownload", help='Download a new site')
        action.add_argument('address', help='Site address')

        # SiteSign
        action = self.subparsers.add_parser("siteSign", help='Update and sign content.json: address [privatekey]')
        action.add_argument('address', help='Site to sign')
        action.add_argument('privatekey', help='Private key (default: ask on execute)', nargs='?')
        action.add_argument('--inner-path', help='File you want to sign (default: content.json)',
                            default="content.json", metavar="inner_path")
        action.add_argument('--remove-missing_optional', help='Remove optional files that is not present in the directory', action='store_true')
        action.add_argument('--publish', help='Publish site after the signing', action='store_true')

        # SitePublish
        action = self.subparsers.add_parser("sitePublish", help='Publish site to other peers: address')
        action.add_argument('address', help='Site to publish')
        action.add_argument('peer_ip', help='Peer ip to publish (default: random peers ip from tracker)',
                            default=None, nargs='?')
        action.add_argument('peer_port', help='Peer port to publish (default: random peer port from tracker)',
                            default=15441, nargs='?')
        action.add_argument('--inner-path', help='Content.json you want to publish (default: content.json)',
                            default="content.json", metavar="inner_path")
        action.add_argument('--recursive', help="Whether to publish all of site's content.json. "
                            "Overrides --inner-path. (default: false)", action='store_true', dest='recursive')

        # SiteVerify
        action = self.subparsers.add_parser("siteVerify", help='Verify site files using sha512: address')
        action.add_argument('address', help='Site to verify')

        # SiteCmd
        action = self.subparsers.add_parser("siteCmd", help='Execute a ZeroFrame API command on a site')
        action.add_argument('address', help='Site address')
        action.add_argument('cmd', help='API command name')
        action.add_argument('parameters', help='Parameters of the command', nargs='?')

        # Import bundled sites
        action = self.subparsers.add_parser("importBundle", help='Import sites from a .zip bundle')
        action.add_argument('bundle', help='Path to a data bundle')

        # dbRebuild
        action = self.subparsers.add_parser("dbRebuild", help='Rebuild site database cache')
        action.add_argument('address', help='Site to rebuild')

        # dbQuery
        action = self.subparsers.add_parser("dbQuery", help='Query site sql cache')
        action.add_argument('address', help='Site to query')
        action.add_argument('query', help='Sql query')

        # PeerPing
        action = self.subparsers.add_parser("peerPing", help='Send Ping command to peer')
        action.add_argument('peer_ip', help='Peer ip')
        action.add_argument('peer_port', help='Peer port', nargs='?')

        # PeerGetFile
        action = self.subparsers.add_parser("peerGetFile", help='Request and print a file content from peer')
        action.add_argument('peer_ip', help='Peer ip')
        action.add_argument('peer_port', help='Peer port')
        action.add_argument('site', help='Site address')
        action.add_argument('filename', help='File name to request')
        action.add_argument('--benchmark', help='Request file 10x then displays the total time', action='store_true')

        # PeerCmd
        action = self.subparsers.add_parser("peerCmd", help='Request and print a file content from peer')
        action.add_argument('peer_ip', help='Peer ip')
        action.add_argument('peer_port', help='Peer port')
        action.add_argument('cmd', help='Command to execute')
        action.add_argument('parameters', help='Parameters to command', nargs='?')

        # CryptSign
        action = self.subparsers.add_parser("cryptSign", help='Sign message using Bitcoin private key')
        action.add_argument('message', help='Message to sign')
        action.add_argument('privatekey', help='Private key')

        # Crypt Verify
        action = self.subparsers.add_parser("cryptVerify", help='Verify message using Bitcoin public address')
        action.add_argument('message', help='Message to verify')
        action.add_argument('sign', help='Signiture for message')
        action.add_argument('address', help='Signer\'s address')

        # Crypt GetPrivatekey
        action = self.subparsers.add_parser("cryptGetPrivatekey", help='Generate a privatekey from master seed')
        action.add_argument('master_seed', help='Source master seed')
        action.add_argument('site_address_index', help='Site address index', type=int)

        action = self.subparsers.add_parser("getConfig", help='Return json-encoded info')
        action = self.subparsers.add_parser("testConnection", help='Testing')
        action = self.subparsers.add_parser("testAnnounce", help='Testing')

        self.test_parser = self.subparsers.add_parser("test", help='Run a test')
        self.test_parser.add_argument('test_name', help='Test name', nargs="?")
        # self.test_parser.add_argument('--benchmark', help='Run the tests multiple times to measure the performance', action='store_true')

        # Config parameters
        self.parser.add_argument('--silent', help="Only log errors to terminal output", action='store_true')
        self.parser.add_argument('--verbose', help="More detailed logging", action='store_true')
        self.parser.add_argument('--debug', help="Debug mode", action='store_true')
        self.parser.add_argument('--debug-unsafe', help="Disable safety checks which impede debugging", action=BooleanOptionalAction, default=False)
        self.parser.add_argument('--unsafe-inlines-csp', help="Disable CSPolicy breaking inline script", action=BooleanOptionalAction, default=False)
        self.parser.add_argument('--debug-socket', help="Debug socket connections", action='store_true')
        self.parser.add_argument('--wip', help="Enable WIP features", action=BooleanOptionalAction, default=False)
        self.parser.add_argument('--deprecated', help="Enable deprecated features", action=BooleanOptionalAction, default=True)

        self.parser.add_argument('--batch', help="Batch mode (No interactive input for commands)", action='store_true')

        self.parser.add_argument('--no-plugins', help="Disable all plugins", action='store_true')
        self.parser.add_argument('--portable', action=BooleanOptionalAction)
        self.parser.add_argument('--start-dir', help='Path of working dir for variable content (data, log, config)', default=self.start_dir, metavar="path")
        self.parser.add_argument('--config-file', help='Path of config file', default=config_file, metavar="path")
        self.parser.add_argument('--data-dir', help='Path of data directory', default=data_dir, metavar="path")
        self.parser.add_argument('--migrate', help="Try to migrate data from old 0net versions (not implemented yet)", action=BooleanOptionalAction, default=False)

        self.parser.add_argument('--console-log-level', help='Level of logging to console', default="default", choices=["default", "DEBUG", "INFO", "ERROR", "off"])

        self.parser.add_argument('--log-dir', help='Path of logging directory', default=log_dir, metavar="path")
        self.parser.add_argument('--log-level', help='Level of logging to file', default="DEBUG", choices=["DEBUG", "INFO", "ERROR", "off"])
        self.parser.add_argument('--log-rotate', help='Log rotate interval', default="daily", choices=["hourly", "daily", "weekly", "off"])
        self.parser.add_argument('--log-rotate-backup-count', help='Log rotate backup count', default=5, type=int)

        self.parser.add_argument('--language', help='Web interface language', default=language, metavar='language')
        self.parser.add_argument('--ui-ip-protect', help="Protect UI server from being accessed through third-party pages and on unauthorized cross-origin pages (enabled by default when serving on localhost IPs; doesn't work with non-local IPs, need testing with host names)", choices=['always', 'local', 'off'], default='local')
        self.parser.add_argument('--ui-ip', help='Web interface bind address', default="127.0.0.1", metavar='ip')
        self.parser.add_argument('--ui-port', help='Web interface bind port', default=43110, type=int, metavar='port')
        self.parser.add_argument('--ui-site-port', help='Port for serving site content, defaults to ui_port+1', default=None, metavar='port')
        self.parser.add_argument('--ui-restrict', help='Restrict web access', default=False, metavar='ip', nargs='*')
        self.parser.add_argument('--ui-host', help='Allow access using this hosts', metavar='host', nargs='*')
        self.parser.add_argument('--ui-trans-proxy', help='Allow access using a transparent proxy', action='store_true')

        self.parser.add_argument('--open-browser', help='Open homepage in web browser automatically',
                                 nargs='?', const="default_browser", metavar='browser_name')
        self.parser.add_argument('--homepage', help='Web interface Homepage', default='191CazMVNaAcT9Y1zhkxd9ixMBPs59g2um',
                                 metavar='address')
        # self.parser.add_argument('--updatesite', help='Source code update site', default='1uPDaT3uSyWAPdCv1WkMb5hBQjWSNNACf',
                                 # metavar='address')
        self.parser.add_argument('--admin-pages', help='Pages with admin privileges', default=[], metavar='address', nargs='*')
        self.parser.add_argument('--dist-type', help='Type of installed distribution', default='source')

        self.parser.add_argument('--size-limit', help='Default site size limit in MB', default=10, type=int, metavar='limit')
        self.parser.add_argument('--file-size-limit', help='Maximum per file size limit in MB', default=10, type=int, metavar='limit')
        self.parser.add_argument('--connected-limit', help='Max connected peer per site', default=8, type=int, metavar='connected_limit')
        self.parser.add_argument('--global-connected-limit', help='Max connections', default=512, type=int, metavar='global_connected_limit')
        self.parser.add_argument('--workers', help='Download workers per site', default=5, type=int, metavar='workers')

        self.parser.add_argument('--fileserver-ip', help='FileServer bind address', default="*", metavar='ip')
        self.parser.add_argument('--fileserver-port', help='FileServer bind port (0: randomize)', default=0, type=int, metavar='port')
        self.parser.add_argument('--fileserver-port-range', help='FileServer randomization range', default="10000-40000", metavar='port')
        self.parser.add_argument('--fileserver-ip-type', help='FileServer ip type', default="dual", choices=["ipv4", "ipv6", "dual"])
        self.parser.add_argument('--ip-local', help='My local ips', default=ip_local, type=int, metavar='ip', nargs='*')
        self.parser.add_argument('--ip-external', help='Set reported external ip (tested on start if None)', metavar='ip', nargs='*')
        self.parser.add_argument('--offline', help='Disable network communication', action='store_true')
        self.parser.add_argument('--disable-port-check', help='Disable checking port', action='store_true')
        self.parser.add_argument('--dht', help="Use DHT for peer discovery (experimental)", action=BooleanOptionalAction, default=True)
        self.parser.add_argument('--use-trackers', help="Use classic trackers for peer discovery", action=BooleanOptionalAction, default=True)

        self.parser.add_argument('--disable-udp', help='Disable UDP connections', action='store_true')
        self.parser.add_argument('--proxy', help='Socks proxy address', metavar='ip:port')
        self.parser.add_argument('--bind', help='Bind outgoing sockets to this address', metavar='ip')
        self.parser.add_argument('--bootstrap-url', help='URL of file with link to bootstrap bundle', default='https://raw.githubusercontent.com/zeronet-conservancy/zeronet-conservancy/master/bootstrap.url', type=str)
        self.parser.add_argument('--bootstrap', help="Enable downloading bootstrap information from clearnet", action=BooleanOptionalAction, default=True)
        self.parser.add_argument('--trackers', help='Bootstraping torrent trackers', default=[], metavar='protocol://address', nargs='*')
        self.parser.add_argument('--trackers-file', help='Load torrent trackers dynamically from a file (using Syncronite by default)', default=['{data_dir}/15CEFKBRHFfAP9rmL6hhLmHoXrrgmw4B5o/cache/1/Syncronite.html'], metavar='path', nargs='*')
        self.parser.add_argument('--trackers-proxy', help='Force use proxy to connect to trackers (disable, tor, ip:port)', default="disable")
        self.parser.add_argument('--use-libsecp256k1', help='Use Libsecp256k1 liblary for speedup', type='bool', choices=[True, False], default=True)
        self.parser.add_argument('--use-openssl', help='Use OpenSSL liblary for speedup', type='bool', choices=[True, False], default=True)
        self.parser.add_argument('--openssl-lib-file', help='Path for OpenSSL library file (default: detect)', default=argparse.SUPPRESS, metavar="path")
        self.parser.add_argument('--openssl-bin-file', help='Path for OpenSSL binary file (default: detect)', default=argparse.SUPPRESS, metavar="path")
        self.parser.add_argument('--disable-db', help='Disable database updating', action='store_true')
        self.parser.add_argument('--disable-encryption', help='Disable connection encryption', action='store_true')
        self.parser.add_argument('--force-encryption', help="Enforce encryption to all peer connections", action='store_true')
        self.parser.add_argument('--disable-sslcompression', help='Disable SSL compression to save memory',
                                 type='bool', choices=[True, False], default=True)
        self.parser.add_argument('--keep-ssl-cert', help='Disable new SSL cert generation on startup', action='store_true')
        self.parser.add_argument('--max-files-opened', help='Change maximum opened files allowed by OS to this value on startup',
                                 default=2048, type=int, metavar='limit')
        self.parser.add_argument('--stack-size', help='Change thread stack size', default=None, type=int, metavar='thread_stack_size')
        self.parser.add_argument('--use-tempfiles', help='Use temporary files when downloading (experimental)',
                                 type='bool', choices=[True, False], default=False)
        self.parser.add_argument('--stream-downloads', help='Stream download directly to files (experimental)',
                                 type='bool', choices=[True, False], default=False)
        self.parser.add_argument('--msgpack-purepython', help='Use less memory, but a bit more CPU power',
                                 type='bool', choices=[True, False], default=False)
        self.parser.add_argument('--fix-float-decimals', help='Fix content.json modification date float precision on verification',
                                 type='bool', choices=[True, False], default=fix_float_decimals)
        self.parser.add_argument('--db-mode', choices=["speed", "security"], default="speed")

        self.parser.add_argument('--threads-fs-read', help='Number of threads for file read operations', default=1, type=int)
        self.parser.add_argument('--threads-fs-write', help='Number of threads for file write operations', default=1, type=int)
        self.parser.add_argument('--threads-crypt', help='Number of threads for cryptographic operations', default=2, type=int)
        self.parser.add_argument('--threads-db', help='Number of threads for database operations', default=1, type=int)

        self.parser.add_argument('--download-optional', choices=["manual", "auto"], default="manual")

        self.parser.add_argument('--lax-cert-check', action=BooleanOptionalAction, default=True, help="Enabling lax cert check allows users getting site writing priviledges by employing compromized (i.e. with leaked private keys) cert issuer. Disable for spam protection")
        self.parser.add_argument('--nocert-everywhere', action=BooleanOptionalAction, default=False, help="Allow user content signed by locally whitelisted users (NOTE: when enabled you may see user content not visible in earlier versions (pre-v0.8))")

        self.parser.add_argument('--tor', help='enable: Use only for Tor peers, always: Use Tor for every connection', choices=["disable", "enable", "always"], default='enable')
        self.parser.add_argument('--tor-controller', help='Tor controller address', metavar='ip:port', default='127.0.0.1:9051')
        self.parser.add_argument('--tor-proxy', help='Tor proxy address', metavar='ip:port', default='127.0.0.1:9050')
        self.parser.add_argument('--tor-password', help='Tor controller password', metavar='password')
        self.parser.add_argument('--tor-use-bridges', help='Use obfuscated bridge relays to avoid Tor block', action='store_true')
        self.parser.add_argument('--tor-hs-limit', help='Maximum number of hidden services in Tor always mode', metavar='limit', type=int, default=10)
        self.parser.add_argument('--tor-hs-port', help='Hidden service port in Tor always mode', metavar='limit', type=int, default=15441)

        self.parser.add_argument('--repl', help='Instead of printing logs in console, drop into REPL after initialization', action='store_true')
        self.parser.add_argument('--version', action='version', version=f'zeronet-conservancy {self.version_full}')
        self.parser.add_argument('--end', help='Stop multi value argument parsing', action='store_true')

        return self.parser

    def loadTrackersFile(self):
        if self.trackers_file is None:
            return None

        self.trackers = self.arguments.trackers[:]

        for trackers_file in self.trackers_file:
            try:
                if trackers_file.startswith("/"):  # Absolute
                    trackers_file_path = trackers_file
                elif trackers_file.startswith("{data_dir}"):  # Relative to data_dir
                    trackers_file_path = trackers_file.replace('{data_dir}', str(self.data_dir))
                else:
                    # Relative to zeronet.py or something else, unsupported
                    raise RuntimeError(f'trackers_file should be relative to {{data_dir}} or absolute path (not {trackers_file})')

                for line in open(trackers_file_path):
                    tracker = line.strip()
                    if "://" in tracker and tracker not in self.trackers:
                        self.trackers.append(tracker)
            except Exception as err:
                print(f'Error loading trackers file: {err}')

    # Find arguments specified for current action
    def getActionArguments(self):
        back = {}
        arguments = self.parser._subparsers._group_actions[0].choices[self.action]._actions[1:]  # First is --version
        for argument in arguments:
            back[argument.dest] = getattr(self, argument.dest)
        return back

    # Try to find action from argv
    def getAction(self, argv):
        actions = [list(action.choices.keys()) for action in self.parser._actions if action.dest == "action"][0]  # Valid actions
        found_action = False
        for action in actions:  # See if any in argv
            if action in argv:
                found_action = action
                break
        return found_action

    # Move plugin parameters to end of argument list
    def moveUnknownToEnd(self, argv, default_action):
        valid_actions = sum([action.option_strings for action in self.parser._actions], [])
        valid_parameters = []
        plugin_parameters = []
        plugin = False
        for arg in argv:
            if arg.startswith("--"):
                if arg not in valid_actions:
                    plugin = True
                else:
                    plugin = False
            elif arg == default_action:
                plugin = False

            if plugin:
                plugin_parameters.append(arg)
            else:
                valid_parameters.append(arg)
        return valid_parameters + plugin_parameters

    def getParser(self, argv):
        action = self.getAction(argv)
        if not action:
            return self.parser
        else:
            return self.subparsers.choices[action]

    # Parse arguments from config file and command line
    def parse(self, silent=False, parse_config=True):
        argv = self.argv[:]  # Copy command line arguments
        current_parser = self.getParser(argv)
        if silent:  # Don't display messages or quit on unknown parameter
            original_print_message = self.parser._print_message
            original_exit = self.parser.exit

            def silencer(parser, function_name):
                parser.exited = True
                return None
            current_parser.exited = False
            current_parser._print_message = lambda *args, **kwargs: silencer(current_parser, "_print_message")
            current_parser.exit = lambda *args, **kwargs: silencer(current_parser, "exit")

        self.parseCommandline(argv, silent)  # Parse argv
        self.setAttributes()
        self.updatePaths()
        self.createPaths()
        if parse_config:
            argv = self.parseConfig(argv)  # Add arguments from config file

        self.parseCommandline(argv, silent)  # Parse argv
        self.setAttributes()

        if not silent:
            if self.fileserver_ip != "*" and self.fileserver_ip not in self.ip_local:
                self.ip_local.append(self.fileserver_ip)

        if silent:  # Restore original functions
            if current_parser.exited and self.action == "main":  # Argument parsing halted, don't start ZeroNet with main action
                self.action = None
            current_parser._print_message = original_print_message
            current_parser.exit = original_exit

        self.loadTrackersFile()

    def fixArgs(self, args):
        "Fix old-style flags and issue a warning"
        res = []
        for arg in args:
            if arg.startswith('--') and '_' in arg:
                farg = arg.replace('_', '-')
                print(f'[bold red]WARNING: using deprecated flag in command line: {arg} should be {farg}[/bold red]')
                print('Support for deprecated flags might be removed in the future')
            else:
                farg = arg
            res.append(farg)
        return res

    def parseCommandline(self, argv, silent=False):
        argv = self.fixArgs(argv)
        # Find out if action is specificed on start
        action = self.getAction(argv)
        if not action:
            argv.append("--end")
            argv.append("main")
            action = "main"
        argv = self.moveUnknownToEnd(argv, action)
        if silent:
            res = self.parser.parse_known_args(argv[1:])
            if res:
                self.arguments = res[0]
            else:
                self.arguments = {}
        else:
            self.arguments = self.parser.parse_args(argv[1:])
        if self.arguments.ui_site_port is None:
            self.arguments.ui_site_port = self.arguments.ui_port + 1
        if self.arguments.ui_ip_protect == 'always':
            self.arguments.ui_check_cors = True
        elif self.arguments.ui_ip_protect == 'off':
            self.arguments.ui_check_cors = False
        elif self.arguments.ui_ip_protect == 'local':
            self.arguments.ui_check_cors = self.arguments.ui_ip == '127.0.0.1' or self.arguments.ui_ip == '::1'
        else:
            raise Exception("Wrong argparse result")

    def parseConfig(self, argv):
        argv = self.fixArgs(argv)
        # Load config file
        if os.path.isfile(self.config_file):
            config = configparser.RawConfigParser(allow_no_value=True, strict=False)
            config.read(self.config_file)
            for section in config.sections():
                for key, val in config.items(section):
                    if val == "True":
                        val = None
                    if section != "global":  # If not global prefix key with section
                        key = section + "_" + key
                    key = key.replace('_', '-')

                    argv_extend = [f'--{key}']
                    if val:
                        for line in val.strip().split("\n"):  # Allow multi-line values
                            argv_extend.append(line)
                        if "\n" in val:
                            argv_extend.append("--end")

                    argv = argv[:1] + argv_extend + argv[1:]
        return argv

    # Return command line value of given argument
    def getCmdlineValue(self, key):
        if key not in self.argv:
            return None
        argv_index = self.argv.index(key)
        if argv_index == len(self.argv) - 1:  # last arg, test not specified
            return None

        return self.argv[argv_index + 1]

    def setAttributes(self):
        """Expose arguments as class attributes"""
        if self.arguments:
            args = vars(self.arguments)
            for key, val in args.items():
                if type(val) is list:
                    val = val[:]
                if key in ("data_dir", "log_dir", "start_dir", "openssl_bin_file", "openssl_lib_file"):
                    if val:
                        val = Path(val)
                setattr(self, key, val)

    def loadPlugins(self):
        from Plugin import PluginManager

        @PluginManager.acceptPlugins
        class ConfigPlugin(object):
            def __init__(self, config):
                self.argv = config.argv
                self.parser = config.parser
                self.subparsers = config.subparsers
                self.test_parser = config.test_parser
                self.getCmdlineValue = config.getCmdlineValue
                self.createArguments()

            def createArguments(self):
                pass

        ConfigPlugin(self)

    def saveValue(self, key, value):
        if not os.path.isfile(self.config_file):
            content = ""
        else:
            content = open(self.config_file).read()
        lines = content.splitlines()

        global_line_i = None
        key_line_i = None
        i = 0
        for line in lines:
            if line.strip() == "[global]":
                global_line_i = i
            if line.startswith(key + " =") or line == key:
                key_line_i = i
            i += 1

        if key_line_i and len(lines) > key_line_i + 1:
            while True:  # Delete previous multiline values
                is_value_line = lines[key_line_i + 1].startswith(" ") or lines[key_line_i + 1].startswith("\t")
                if not is_value_line:
                    break
                del lines[key_line_i + 1]

        if value is None:  # Delete line
            if key_line_i:
                del lines[key_line_i]

        else:  # Add / update
            if type(value) is list:
                value_lines = [""] + [str(line).replace("\n", "").replace("\r", "") for line in value]
            else:
                value_lines = [str(value).replace("\n", "").replace("\r", "")]
            new_line = "%s = %s" % (key, "\n ".join(value_lines))
            if key_line_i:  # Already in the config, change the line
                lines[key_line_i] = new_line
            elif global_line_i is None:  # No global section yet, append to end of file
                lines.append("[global]")
                lines.append(new_line)
            else:  # Has global section, append the line after it
                lines.insert(global_line_i + 1, new_line)

        open(self.config_file, "w").write("\n".join(lines))

    def getServerInfo(self):
        from Plugin import PluginManager
        import main

        info = {
            "platform": sys.platform,
            "fileserver_ip": self.fileserver_ip,
            "fileserver_port": self.fileserver_port,
            "ui_ip": self.ui_ip,
            "ui_port": self.ui_port,
            "version": self.version,
            "rev": self.rev,
            "language": self.language,
            "debug": self.debug,
            "plugins": PluginManager.plugin_manager.plugin_names,

            "log_dir": os.path.abspath(self.log_dir),
            "data_dir": os.path.abspath(self.data_dir),
            "src_dir": os.path.dirname(os.path.abspath(__file__))
        }

        try:
            info["ip_external"] = main.file_server.port_opened
            info["tor_enabled"] = main.file_server.tor_manager.enabled
            info["tor_status"] = main.file_server.tor_manager.status
        except Exception:
            pass

        return info

    def initConsoleLogger(self):
        if self.action == "main":
            format = '[%(asctime)s] %(name)s %(message)s'
        else:
            format = '%(name)s %(message)s'

        if self.console_log_level == "default":
            if self.silent or self.repl:
                level = logging.ERROR
            elif self.debug:
                level = logging.DEBUG
            else:
                level = logging.INFO
        else:
            level = logging.getLevelName(self.console_log_level)

        console_logger = logging.StreamHandler()
        console_logger.setFormatter(logging.Formatter(format, "%H:%M:%S"))
        console_logger.setLevel(level)
        logging.getLogger('').addHandler(console_logger)

    def initFileLogger(self):
        if self.action == "main":
            log_file_path = "%s/debug.log" % self.log_dir
        else:
            log_file_path = "%s/cmd.log" % self.log_dir

        if self.log_rotate == "off":
            file_logger = logging.FileHandler(log_file_path, "w", "utf-8")
        else:
            when_names = {"weekly": "w", "daily": "d", "hourly": "h"}
            file_logger = logging.handlers.TimedRotatingFileHandler(
                log_file_path, when=when_names[self.log_rotate], interval=1, backupCount=self.log_rotate_backup_count,
                encoding="utf8"
            )

            if os.path.isfile(log_file_path):
                file_logger.doRollover()  # Always start with empty log file
        file_logger.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)-8s %(name)s %(message)s'))
        file_logger.setLevel(logging.getLevelName(self.log_level))
        logging.getLogger('').setLevel(logging.getLevelName(self.log_level))
        logging.getLogger('').addHandler(file_logger)

    def initLogging(self, console_logging=None, file_logging=None):
        if console_logging == None:
            console_logging = self.console_log_level != "off"

        if file_logging == None:
            file_logging = self.log_level != "off"

        # Create necessary files and dirs
        if not os.path.isdir(self.log_dir):
            os.mkdir(self.log_dir)
            try:
                os.chmod(self.log_dir, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
            except Exception as err:
                print("Can't change permission of %s: %s" % (self.log_dir, err))

        logging.getLogger('').name = "-"  # Remove root prefix

        self.error_logger = ErrorLogHandler()
        self.error_logger.setLevel(logging.getLevelName("ERROR"))
        logging.getLogger('').addHandler(self.error_logger)

        if console_logging:
            self.initConsoleLogger()
        if file_logging:
            self.initFileLogger()

    def tor_proxy_split(self):
        if self.tor_proxy:
            if ':' in config.tor_proxy:
                ip, port = config.tor_proxy.rsplit(":", 1)
            else:
                ip = 'localhost'
                port = config.tor_proxy
            return ip, int(port)
        else:
            return 'localhost', 9050

    def tor_controller_split(self):
        if self.tor_controller:
            if ':' in config.tor_controller:
                ip, port = config.tor_controller.rsplit(":", 1)
            else:
                ip = 'localhost'
                port = config.tor_controller
            return ip, int(port)
        else:
            return 'localhost', 9051


class ErrorLogHandler(logging.StreamHandler):
    def __init__(self):
        self.lines = []
        return super().__init__()

    def emit(self, record):
        self.lines.append([time.time(), record.levelname, self.format(record)])

    def onNewRecord(self, record):
        pass


config = Config(sys.argv)
