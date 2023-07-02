import argparse
import sys
import os
import locale
import re
import configparser
import logging
import logging.handlers
import stat
import time

trackers = [
    'zero://188.242.242.224:26474',
    'zero://2001:19f0:8001:1d2f:5400:2ff:fe83:5bf7:23141',
    'zero://200:1e7a:5100:ef7c:6fa4:d8ae:b91c:a74:15441',
    'zero://23.184.48.134:15441',
    'zero://57hzgtu62yzxqgbvgxs7g3lfck3za4zrda7qkskar3tlak5recxcebyd.onion:15445',
    'zero://6i54dd5th73oelv636ivix6sjnwfgk2qsltnyvswagwphub375t3xcad.onion:15441',
    'zero://f2hnjbggc3c2u2apvxdugirnk6bral54ibdoul3hhvu7pd4fso5fq3yd.onion:15441',
    'zero://gugt43coc5tkyrhrc3esf6t6aeycvcqzw7qafxrjpqbwt4ssz5czgzyd.onion:15441',
    'zero://k5w77dozo3hy5zualyhni6vrh73iwfkaofa64abbilwyhhd3wgenbjqd.onion:15441',
    'zero://ow7in4ftwsix5klcbdfqvfqjvimqshbm2o75rhtpdnsderrcbx74wbad.onion:15441',
    'zero://pn4q2zzt2pw4nk7yidxvsxmydko7dfibuzxdswi6gu6ninjpofvqs2id.onion:15441',
    'zero://skdeywpgm5xncpxbbr4cuiip6ey4dkambpanog6nruvmef4f3e7o47qd.onion:15441',
    'zero://wlxav3szbrdhest4j7dib2vgbrd7uj7u7rnuzg22cxbih7yxyg2hsmid.onion:15441',
    'zero://zy7wttvjtsijt5uwmlar4yguvjc2gppzbdj4v6bujng6xwjmkdg7uvqd.onion:15441',
    'http://bt.okmp3.ru:2710/announce',
    'http://fxtt.ru:80/announce',
    'http://incine.ru:6969/announce',
    'http://moeweb.pw:6969/announce',
    'http://open.acgnxtracker.com:80/announce',
    'http://t.acg.rip:6699/announce',
    'http://t.nyaatracker.com:80/announce',
    'http://t.overflow.biz:6969/announce',
    'http://tracker.files.fm:6969/announce',
    'http://tracker.mywaifu.best:6969/announce',
    'http://tracker.vrpnet.org:6969/announce',
    'http://vps02.net.orel.ru:80/announce',
    'udp://960303.xyz:6969/announce',
    'udp://aarsen.me:6969/announce',
    'udp://astrr.ru:6969/announce',
    'udp://ben.kerbertools.xyz:6969/announce',
    'udp://bt1.archive.org:6969/announce',
    'udp://bt2.archive.org:6969/announce',
    'udp://bt.ktrackers.com:6666/announce',
    'udp://bubu.mapfactor.com:6969/announce',
    'udp://c.ns.cluefone.com:6969/announce',
    'udp://cutscloud.duckdns.org:6969/announce',
    'udp://download.nerocloud.me:6969/announce',
    'udp://epider.me:6969/announce',
    'udp://exodus.desync.com:6969/announce',
    'udp://htz3.noho.st:6969/announce',
    'udp://ipv4.tracker.harry.lu:80/announce',
    'udp://laze.cc:6969/announce',
    'udp://mail.artixlinux.org:6969/announce',
    'udp://mirror.aptus.co.tz:6969/announce',
    'udp://moonburrow.club:6969/announce',
    'udp://movies.zsw.ca:6969/announce',
    'udp://mts.tvbit.co:6969/announce',
    'udp://new-line.net:6969/announce',
    'udp://open.demonii.com:1337/announce',
    'udp://open.stealth.si:80/announce',
    'udp://opentracker.i2p.rocks:6969/announce',
    'udp://p4p.arenabg.com:1337/announce',
    'udp://psyco.fr:6969/announce',
    'udp://public.publictracker.xyz:6969/announce',
    'udp://rep-art.ynh.fr:6969/announce',
    'udp://run.publictracker.xyz:6969/announce',
    'udp://sanincode.com:6969/announce',
    'udp://slicie.icon256.com:8000/announce',
    'udp://tamas3.ynh.fr:6969/announce',
    'udp://thouvenin.cloud:6969/announce',
    'udp://torrentclub.space:6969/announce',
    'udp://tracker.0x.tf:6969/announce',
    'udp://tracker1.bt.moack.co.kr:80/announce',
    'udp://tracker.4.babico.name.tr:3131/announce',
    'udp://tracker.altrosky.nl:6969/announce',
    'udp://tracker.artixlinux.org:6969/announce',
    'udp://tracker.farted.net:6969/announce',
    'udp://tracker.jonaslsa.com:6969/announce',
    'udp://tracker.joybomb.tw:6969/announce',
    'udp://tracker.monitorit4.me:6969/announce',
    'udp://tracker.opentrackr.org:1337/announce',
    'udp://tracker.pomf.se:80/announce',
    'udp://tracker.publictracker.xyz:6969/announce',
    'udp://tracker.srv00.com:6969/announce',
    'udp://tracker.tcp.exchange:6969/announce',
    'udp://tracker.theoks.net:6969/announce',
    'udp://transkaroo.joustasie.net:6969/announce',
    'udp://uploads.gamecoast.net:6969/announce',
    'udp://v2.iperson.xyz:6969/announce',
    'udp://vibe.sleepyinternetfun.xyz:1738/announce',
    'udp://www.skynetcenter.me:6969/announce',
    'udp://www.torrent.eu.org:451/announce',
    'zero://194.5.98.39:15441',
    'zero://145.239.95.38:15441',
    'zero://178.128.34.249:26117',
    'zero://217.18.217.143:39288',
    'zero://83.246.141.203:22207',
    'zero://syncronite.loki:15441',
    'zero://2a05:dfc1:4000:1e00::a:15441',
    'zero://2400:6180:100:d0::8fd:8001:21697',
    'zero://2001:19f0:8001:1d2f:5400:2ff:fe83:5bf7:30530',
    'zero://73pyhfwfwsrhfw76knkjfnw6o3lk53zfo7hlxdmxbj75sjcnol5cioad.onion:15442',
    'zero://fzlzmxuz2bust72cuy5g4w6d62tx624xcjaupf2kp7ffuitbiniy2hqd.onion:15441',
    'zero://rlcjomszyitxpwv7kzopmqgzk3bdpsxeull4c3s6goszkk6h2sotfoad.onion:15441',
    'zero://tqmo2nffqo4qc5jgmz3me5eri3zpgf3v2zciufzmhnvznjve5c3argad.onion:15441',
    'http://107.189.31.134:6969/announce',
    'http://119.28.71.45:8080/announce',
    'http://129.146.193.240:6699/announce',
    'http://159.69.65.157:6969/announce',
    'http://163.172.29.130:80/announce',
    'http://185.130.47.2:6969/announce',
    'http://45.67.35.111:6969/announce',
    'http://61.222.178.254:6969/announce',
    'http://83.31.30.182:6969/announce',
    'http://93.158.213.92:1337/announce',
    'http://95.217.167.10:6969/announce',
    'udp://102.223.180.235:6969/announce',
    'udp://103.122.21.50:6969/announce',
    'udp://104.131.98.232:6969/announce',
    'udp://104.244.77.87:6969/announce',
    'udp://107.189.11.58:6969/announce',
    'udp://107.189.31.134:6969/announce',
    'udp://139.144.68.88:6969/announce',
    'udp://149.28.239.70:6969/announce',
    'udp://15.204.205.14:6969/announce',
    'udp://156.234.201.18:80/announce',
    'udp://158.101.161.60:3131/announce',
    'udp://163.172.29.130:80/announce',
    'udp://167.99.185.219:6969/announce',
    'udp://176.31.250.174:6969/announce',
    'udp://176.56.4.238:6969/announce',
    'udp://178.32.222.98:3391/announce',
    'udp://184.105.151.166:6969/announce',
    'udp://185.102.219.163:6969/announce',
    'udp://185.181.60.155:80/announce',
    'udp://185.217.199.21:6969/announce',
    'udp://185.44.82.25:1337/announce',
    'udp://185.68.21.244:6969/announce',
    'udp://192.3.165.191:6969/announce',
    'udp://192.3.165.198:6969/announce',
    'udp://192.95.46.115:6969/announce',
    'udp://193.176.158.162:6969/announce',
    'udp://193.37.214.12:6969/announce',
    'udp://193.42.111.57:9337/announce',
    'udp://198.100.149.66:6969/announce',
    'udp://20.100.205.229:6969/announce',
    'udp://207.241.226.111:6969/announce',
    'udp://207.241.231.226:6969/announce',
    'udp://209.141.59.16:6969/announce',
    'udp://212.237.53.230:6969/announce',
    'udp://23.153.248.2:6969/announce',
    'udp://23.254.228.89:6969/announce',
    'udp://37.187.111.136:6969/announce',
    'udp://37.27.4.53:6969/announce',
    'udp://38.7.201.142:6969/announce',
    'udp://45.154.253.6:6969/announce',
    'udp://45.63.30.114:6969/announce',
    'udp://45.9.60.30:6969/announce',
    'udp://46.38.238.105:6969/announce',
    'udp://49.12.76.8:8080/announce',
    'udp://5.102.159.190:6969/announce',
    'udp://5.196.89.204:6969/announce',
    'udp://51.15.79.209:6969/announce',
    'udp://51.159.54.68:6666/announce',
    'udp://51.68.174.87:6969/announce',
    'udp://51.81.222.188:6969/announce',
    'udp://52.58.128.163:6969/announce',
    'udp://61.222.178.254:6969/announce',
    'udp://77.73.69.230:6969/announce',
    'udp://83.102.180.21:80/announce',
    'udp://83.31.30.182:6969/announce',
    'udp://85.206.172.159:6969/announce',
    'udp://85.239.33.28:6969/announce',
    'udp://86.57.161.157:6969/announce',
    'udp://91.216.110.52:451/announce',
    'udp://93.158.213.92:1337/announce',
    'udp://94.103.87.87:6969/announce',
    'udp://95.216.74.39:6969/announce',
    'udp://95.31.11.224:6969/announce',
]

class Config(object):

    def __init__(self, argv):
        self.version = "0.7.9"
        self.user_agent = "conservancy"
        # DEPRECATED ; replace with git-generated commit
        self.rev = 5100
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
        self.start_dir = self.getStartDir()

        self.config_file = self.start_dir + "/zeronet.conf"
        self.data_dir = self.start_dir + "/data"
        self.log_dir = self.start_dir + "/log"
        self.openssl_lib_file = None
        self.openssl_bin_file = None

        self.trackers_file = False
        self.createParser()
        self.createArguments()

    def createParser(self):
        # Create parser
        self.parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
        self.parser.register('type', 'bool', self.strToBool)
        self.subparsers = self.parser.add_subparsers(title="Action to perform", dest="action")

    def __str__(self):
        return str(self.arguments).replace("Namespace", "Config")  # Using argparse str output

    # Convert string to bool
    def strToBool(self, v):
        return v.lower() in ("yes", "true", "t", "1")

    def getStartDir(self):
        this_file = os.path.abspath(__file__).replace("\\", "/").rstrip("cd")

        if "--start_dir" in self.argv:
            start_dir = self.argv[self.argv.index("--start_dir") + 1]
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
        elif this_file.endswith("usr/share/zeronet/src/Config.py"):
            # Running from non-writeable location, e.g., AppImage
            start_dir = os.path.expanduser("~/ZeroNet")
        else:
            start_dir = "."

        return start_dir

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

        config_file = self.start_dir + "/zeronet.conf"
        data_dir = self.start_dir + "/data"
        log_dir = self.start_dir + "/log"

        ip_local = ["127.0.0.1", "::1"]

        # Main
        action = self.subparsers.add_parser("main", help='Start UiServer and FileServer (default)')

        # SiteCreate
        action = self.subparsers.add_parser("siteCreate", help='Create a new site')
        action.register('type', 'bool', self.strToBool)
        action.add_argument('--use_master_seed', help="Allow created site's private key to be recovered using the master seed in users.json (default: True)", type="bool", choices=[True, False], default=True)

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
        action.add_argument('--inner_path', help='File you want to sign (default: content.json)',
                            default="content.json", metavar="inner_path")
        action.add_argument('--remove_missing_optional', help='Remove optional files that is not present in the directory', action='store_true')
        action.add_argument('--publish', help='Publish site after the signing', action='store_true')

        # SitePublish
        action = self.subparsers.add_parser("sitePublish", help='Publish site to other peers: address')
        action.add_argument('address', help='Site to publish')
        action.add_argument('peer_ip', help='Peer ip to publish (default: random peers ip from tracker)',
                            default=None, nargs='?')
        action.add_argument('peer_port', help='Peer port to publish (default: random peer port from tracker)',
                            default=15441, nargs='?')
        action.add_argument('--inner_path', help='Content.json you want to publish (default: content.json)',
                            default="content.json", metavar="inner_path")

        # SiteVerify
        action = self.subparsers.add_parser("siteVerify", help='Verify site files using sha512: address')
        action.add_argument('address', help='Site to verify')

        # SiteCmd
        action = self.subparsers.add_parser("siteCmd", help='Execute a ZeroFrame API command on a site')
        action.add_argument('address', help='Site address')
        action.add_argument('cmd', help='API command name')
        action.add_argument('parameters', help='Parameters of the command', nargs='?')

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
        self.parser.add_argument('--verbose', help='More detailed logging', action='store_true')
        self.parser.add_argument('--debug', help='Debug mode', action='store_true')
        self.parser.add_argument('--silent', help='Only log errors to terminal output', action='store_true')
        self.parser.add_argument('--debug_socket', help='Debug socket connections', action='store_true')
        self.parser.add_argument('--merge_media', help='Merge all.js and all.css', action='store_true')

        self.parser.add_argument('--batch', help="Batch mode (No interactive input for commands)", action='store_true')

        self.parser.add_argument('--start_dir', help='Path of working dir for variable content (data, log, .conf)', default=self.start_dir, metavar="path")
        self.parser.add_argument('--config_file', help='Path of config file', default=config_file, metavar="path")
        self.parser.add_argument('--data_dir', help='Path of data directory', default=data_dir, metavar="path")

        self.parser.add_argument('--console_log_level', help='Level of logging to console', default="default", choices=["default", "DEBUG", "INFO", "ERROR", "off"])

        self.parser.add_argument('--log_dir', help='Path of logging directory', default=log_dir, metavar="path")
        self.parser.add_argument('--log_level', help='Level of logging to file', default="DEBUG", choices=["DEBUG", "INFO", "ERROR", "off"])
        self.parser.add_argument('--log_rotate', help='Log rotate interval', default="daily", choices=["hourly", "daily", "weekly", "off"])
        self.parser.add_argument('--log_rotate_backup_count', help='Log rotate backup count', default=5, type=int)

        self.parser.add_argument('--language', help='Web interface language', default=language, metavar='language')
        self.parser.add_argument('--ui_ip', help='Web interface bind address', default="127.0.0.1", metavar='ip')
        self.parser.add_argument('--ui_port', help='Web interface bind port', default=43110, type=int, metavar='port')
        self.parser.add_argument('--ui_restrict', help='Restrict web access', default=False, metavar='ip', nargs='*')
        self.parser.add_argument('--ui_host', help='Allow access using this hosts', metavar='host', nargs='*')
        self.parser.add_argument('--ui_trans_proxy', help='Allow access using a transparent proxy', action='store_true')

        self.parser.add_argument('--open_browser', help='Open homepage in web browser automatically',
                                 nargs='?', const="default_browser", metavar='browser_name')
        self.parser.add_argument('--homepage', help='Web interface Homepage', default='191CazMVNaAcT9Y1zhkxd9ixMBPs59g2um',
                                 metavar='address')
        # self.parser.add_argument('--updatesite', help='Source code update site', default='1uPDaT3uSyWAPdCv1WkMb5hBQjWSNNACf',
                                 # metavar='address')
        self.parser.add_argument('--admin_pages', help='Pages with admin privileges', default=[], metavar='address', nargs='*')
        self.parser.add_argument('--dist_type', help='Type of installed distribution', default='source')

        self.parser.add_argument('--size_limit', help='Default site size limit in MB', default=10, type=int, metavar='limit')
        self.parser.add_argument('--file_size_limit', help='Maximum per file size limit in MB', default=10, type=int, metavar='limit')
        self.parser.add_argument('--connected_limit', help='Max connected peer per site', default=8, type=int, metavar='connected_limit')
        self.parser.add_argument('--global_connected_limit', help='Max connections', default=512, type=int, metavar='global_connected_limit')
        self.parser.add_argument('--workers', help='Download workers per site', default=5, type=int, metavar='workers')

        self.parser.add_argument('--fileserver_ip', help='FileServer bind address', default="*", metavar='ip')
        self.parser.add_argument('--fileserver_port', help='FileServer bind port (0: randomize)', default=0, type=int, metavar='port')
        self.parser.add_argument('--fileserver_port_range', help='FileServer randomization range', default="10000-40000", metavar='port')
        self.parser.add_argument('--fileserver_ip_type', help='FileServer ip type', default="dual", choices=["ipv4", "ipv6", "dual"])
        self.parser.add_argument('--ip_local', help='My local ips', default=ip_local, type=int, metavar='ip', nargs='*')
        self.parser.add_argument('--ip_external', help='Set reported external ip (tested on start if None)', metavar='ip', nargs='*')
        self.parser.add_argument('--offline', help='Disable network communication', action='store_true')

        self.parser.add_argument('--disable_udp', help='Disable UDP connections', action='store_true')
        self.parser.add_argument('--proxy', help='Socks proxy address', metavar='ip:port')
        self.parser.add_argument('--bind', help='Bind outgoing sockets to this address', metavar='ip')
        self.parser.add_argument('--trackers', help='Bootstraping torrent trackers', default=trackers, metavar='protocol://address', nargs='*')
        self.parser.add_argument('--trackers_file', help='Load torrent trackers dynamically from a file', metavar='path', nargs='*')
        self.parser.add_argument('--trackers_proxy', help='Force use proxy to connect to trackers (disable, tor, ip:port)', default="disable")
        self.parser.add_argument('--use_libsecp256k1', help='Use Libsecp256k1 liblary for speedup', type='bool', choices=[True, False], default=True)
        self.parser.add_argument('--use_openssl', help='Use OpenSSL liblary for speedup', type='bool', choices=[True, False], default=True)
        self.parser.add_argument('--openssl_lib_file', help='Path for OpenSSL library file (default: detect)', default=argparse.SUPPRESS, metavar="path")
        self.parser.add_argument('--openssl_bin_file', help='Path for OpenSSL binary file (default: detect)', default=argparse.SUPPRESS, metavar="path")
        self.parser.add_argument('--disable_db', help='Disable database updating', action='store_true')
        self.parser.add_argument('--disable_encryption', help='Disable connection encryption', action='store_true')
        self.parser.add_argument('--force_encryption', help="Enforce encryption to all peer connections", action='store_true')
        self.parser.add_argument('--disable_sslcompression', help='Disable SSL compression to save memory',
                                 type='bool', choices=[True, False], default=True)
        self.parser.add_argument('--keep_ssl_cert', help='Disable new SSL cert generation on startup', action='store_true')
        self.parser.add_argument('--max_files_opened', help='Change maximum opened files allowed by OS to this value on startup',
                                 default=2048, type=int, metavar='limit')
        self.parser.add_argument('--stack_size', help='Change thread stack size', default=None, type=int, metavar='thread_stack_size')
        self.parser.add_argument('--use_tempfiles', help='Use temporary files when downloading (experimental)',
                                 type='bool', choices=[True, False], default=False)
        self.parser.add_argument('--stream_downloads', help='Stream download directly to files (experimental)',
                                 type='bool', choices=[True, False], default=False)
        self.parser.add_argument("--msgpack_purepython", help='Use less memory, but a bit more CPU power',
                                 type='bool', choices=[True, False], default=False)
        self.parser.add_argument("--fix_float_decimals", help='Fix content.json modification date float precision on verification',
                                 type='bool', choices=[True, False], default=fix_float_decimals)
        self.parser.add_argument("--db_mode", choices=["speed", "security"], default="speed")

        self.parser.add_argument('--threads_fs_read', help='Number of threads for file read operations', default=1, type=int)
        self.parser.add_argument('--threads_fs_write', help='Number of threads for file write operations', default=1, type=int)
        self.parser.add_argument('--threads_crypt', help='Number of threads for cryptographic operations', default=2, type=int)
        self.parser.add_argument('--threads_db', help='Number of threads for database operations', default=1, type=int)

        self.parser.add_argument("--download_optional", choices=["manual", "auto"], default="manual")

        self.parser.add_argument('--tor', help='enable: Use only for Tor peers, always: Use Tor for every connection', choices=["disable", "enable", "always"], default='enable')
        self.parser.add_argument('--tor_controller', help='Tor controller address', metavar='ip:port', default='127.0.0.1:9051')
        self.parser.add_argument('--tor_proxy', help='Tor proxy address', metavar='ip:port', default='127.0.0.1:9050')
        self.parser.add_argument('--tor_password', help='Tor controller password', metavar='password')
        self.parser.add_argument('--tor_use_bridges', help='Use obfuscated bridge relays to avoid Tor block', action='store_true')
        self.parser.add_argument('--tor_hs_limit', help='Maximum number of hidden services in Tor always mode', metavar='limit', type=int, default=10)
        self.parser.add_argument('--tor_hs_port', help='Hidden service port in Tor always mode', metavar='limit', type=int, default=15441)

        self.parser.add_argument('--version', action='version', version=f'zeronet-conservancy {self.version} r{self.rev}')
        self.parser.add_argument('--end', help='Stop multi value argument parsing', action='store_true')

        return self.parser

    def loadTrackersFile(self):
        if not self.trackers_file:
            return None

        self.trackers = self.arguments.trackers[:]

        for trackers_file in self.trackers_file:
            try:
                if trackers_file.startswith("/"):  # Absolute
                    trackers_file_path = trackers_file
                elif trackers_file.startswith("{data_dir}"):  # Relative to data_dir
                    trackers_file_path = trackers_file.replace("{data_dir}", self.data_dir)
                else:  # Relative to zeronet.py
                    trackers_file_path = self.start_dir + "/" + trackers_file

                for line in open(trackers_file_path):
                    tracker = line.strip()
                    if "://" in tracker and tracker not in self.trackers:
                        self.trackers.append(tracker)
            except Exception as err:
                print("Error loading trackers file: %s" % err)

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

    # Parse command line arguments
    def parseCommandline(self, argv, silent=False):
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

    # Parse config file
    def parseConfig(self, argv):
        # Find config file path from parameters
        if "--config_file" in argv:
            self.config_file = argv[argv.index("--config_file") + 1]
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

                    if key == "open_browser":  # Prefer config file value over cli argument
                        while "--%s" % key in argv:
                            pos = argv.index("--open_browser")
                            del argv[pos:pos + 2]

                    argv_extend = ["--%s" % key]
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

    # Expose arguments as class attributes
    def setAttributes(self):
        # Set attributes from arguments
        if self.arguments:
            args = vars(self.arguments)
            for key, val in args.items():
                if type(val) is list:
                    val = val[:]
                if key in ("data_dir", "log_dir", "start_dir", "openssl_bin_file", "openssl_lib_file"):
                    if val:
                        val = val.replace("\\", "/")
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
            if self.silent:
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

        # Make warning hidden from console
        logging.WARNING = 15  # Don't display warnings if not in debug mode
        logging.addLevelName(15, "WARNING")

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
