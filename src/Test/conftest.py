import os
import sys
import urllib.request
import time
import logging
import json
import shutil
import gc
import datetime
import atexit
import threading
import socket
from pathlib import Path

import pytest
import mock

# trio/libp2p MUST be imported before gevent monkey-patches -- see the comment
# in src/main.py above the matching import for why (trio's socket subclass
# bakes in socket.SocketType at its own import time, not dynamically). Without
# this, P2P tests only pass by accident, if some pytest plugin (e.g. anyio's)
# happens to import trio first during plugin discovery.
import trio  # noqa: F401
import libp2p  # noqa: F401

import gevent
if "libev" not in str(gevent.config.loop):
    # Workaround for random crash when libuv used with threads
    gevent.config.loop = "libev-cext"

import gevent.event
from gevent import monkey
monkey.patch_all(thread=False)

# NOTE: P2P/* tests that call trio.run() need select.epoll/socket.socket
# temporarily restored to their real (non-gevent-patched) versions -- see
# P2P/compat.py's run(), which brackets that restoration around each
# trio.run() call and swaps gevent's patched versions back immediately
# after, rather than restoring them process-wide here. A process-wide
# restore breaks gevent's own cooperative networking permanently for the
# rest of the test session (confirmed while building this) -- it is not
# thread-liveness-dependent, so don't reintroduce it here.

atexit_register = atexit.register
atexit.register = lambda func, *args, **kwargs: ""  # Don't register shutdown functions to avoid IO error on exit

def pytest_addoption(parser):
    parser.addoption("--slow", action='store_true', default=False, help="Also run slow tests")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--slow"):
        # --runslow given in cli: do not skip slow tests
        return
    skip_slow = pytest.mark.skip(reason="need --slow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)

# Config
if sys.platform == "win32":
    CHROMEDRIVER_PATH = "tools/chrome/chromedriver.exe"
else:
    CHROMEDRIVER_PATH = "chromedriver"
SITE_URL = "http://127.0.0.1:43110"

TEST_DATA_PATH = 'src/Test/testdata'
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/../lib"))  # External modules directory
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/.."))  # Imports relative to src dir
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__) + "/../.."))  # Repo root for src package

import src.Config  # noqa: F401
sys.modules['Config'] = sys.modules['src.Config']

from Config import config
config.argv = ["none"]  # Dont pass any argv to config parser
config.parse(silent=True, parse_config=False)  # Plugins need to access the configuration
config.action = "test"

config.data_dir = Path(TEST_DATA_PATH)  # Use test data for unittests
config.private_dir = Path(TEST_DATA_PATH)  # Use test data for private files (users.json, sites.json)
config.debug = True

os.chdir(os.path.abspath(os.path.dirname(__file__) + "/../.."))  # Set working dir

config.action = "test"
config.debug = True
config.debug_socket = True  # Use test data for unittests
config.verbose = True  # Use test data for unittests
config.tor = "disable"  # Don't start Tor client
config.trackers = []
config.data_dir = Path(TEST_DATA_PATH)  # Use test data for unittests
config.private_dir = Path(TEST_DATA_PATH)  # Use test data for private files (users.json, sites.json)
if "ZERONET_LOG_DIR" in os.environ:
    config.log_dir = os.environ["ZERONET_LOG_DIR"]
config.initLogging(console_logging=False)

# Set custom formatter with realative time format (via: https://stackoverflow.com/questions/31521859/python-logging-module-time-since-last-log)
time_start = time.time()
class TimeFilter(logging.Filter):
    def __init__(self, *args, **kwargs):
        self.time_last = time.time()
        self.main_thread_id = threading.current_thread().ident
        super().__init__(*args, **kwargs)

    def filter(self, record):
        if threading.current_thread().ident != self.main_thread_id:
            record.thread_marker = "T"
            record.thread_title = "(Thread#%s)" % self.main_thread_id
        else:
            record.thread_marker = " "
            record.thread_title = ""

        since_last = time.time() - self.time_last
        if since_last > 0.1:
            line_marker = "!"
        elif since_last > 0.02:
            line_marker = "*"
        elif since_last > 0.01:
            line_marker = "-"
        else:
            line_marker = " "

        since_start = time.time() - time_start
        record.since_start = "%s%.3fs" % (line_marker, since_start)

        self.time_last = time.time()
        return True

log = logging.getLogger()
fmt = logging.Formatter(fmt='%(since_start)s %(thread_marker)s %(levelname)-8s %(name)s %(message)s %(thread_title)s')
[hndl.addFilter(TimeFilter()) for hndl in log.handlers]
[hndl.setFormatter(fmt) for hndl in log.handlers]

from Crypt import CryptBitcoin
from util import RateLimit
from Db import Db
from Debug import Debug

gevent.get_hub().NOT_ERROR += (Debug.Notify,)

def cleanup():
    Db.dbCloseAll()
    for dir_path in [config.data_dir, Path(str(config.data_dir) + "-temp")]:
        if os.path.isdir(dir_path):
            for file_name in os.listdir(dir_path):
                ext = file_name.rsplit(".", 1)[-1]
                if ext not in ["csr", "pem", "srl", "db", "json", "tmp"]:
                    continue
                file_path = os.path.join(dir_path, file_name)
                if os.path.isfile(file_path):
                    os.unlink(file_path)

atexit_register(cleanup)

@pytest.fixture(scope="session")
def resetSettings(request):
    open("%s/sites.json" % config.data_dir, "w").write("{}")
    open("%s/filters.json" % config.data_dir, "w").write("{}")
    open("%s/users.json" % config.data_dir, "w").write("""
        {
            "15E5rhcAUD69WbiYsYARh4YHJ4sLm2JEyc": {
                "certs": {},
                "master_seed": "024bceac1105483d66585d8a60eaf20aa8c3254b0f266e0d626ddb6114e2949a",
                "sites": {}
            }
        }
    """)


@pytest.fixture(scope="session")
def resetTempSettings(request):
    data_dir_temp = Path(str(config.data_dir) + "-temp")
    if not os.path.isdir(data_dir_temp):
        os.mkdir(data_dir_temp)
    open("%s/sites.json" % data_dir_temp, "w").write("{}")
    open("%s/filters.json" % data_dir_temp, "w").write("{}")
    open("%s/users.json" % data_dir_temp, "w").write("""
        {
            "15E5rhcAUD69WbiYsYARh4YHJ4sLm2JEyc": {
                "certs": {},
                "master_seed": "024bceac1105483d66585d8a60eaf20aa8c3254b0f266e0d626ddb6114e2949a",
                "sites": {}
            }
        }
    """)

    def cleanup():
        os.unlink("%s/sites.json" % data_dir_temp)
        os.unlink("%s/users.json" % data_dir_temp)
        os.unlink("%s/filters.json" % data_dir_temp)
    request.addfinalizer(cleanup)


@pytest.fixture()
def db(request):
    db_path = "%s/zeronet.db" % config.data_dir
    schema = {
        "db_name": "TestDb",
        "db_file": "%s/zeronet.db" % config.data_dir,
        "maps": {
            "data.json": {
                "to_table": [
                    "test",
                    {"node": "test", "table": "test_importfilter", "import_cols": ["test_id", "title"]}
                ]
            }
        },
        "tables": {
            "test": {
                "cols": [
                    ["test_id", "INTEGER"],
                    ["title", "TEXT"],
                    ["json_id", "INTEGER REFERENCES json (json_id)"]
                ],
                "indexes": ["CREATE UNIQUE INDEX test_id ON test(test_id)"],
                "schema_changed": 1426195822
            },
            "test_importfilter": {
                "cols": [
                    ["test_id", "INTEGER"],
                    ["title", "TEXT"],
                    ["json_id", "INTEGER REFERENCES json (json_id)"]
                ],
                "indexes": ["CREATE UNIQUE INDEX test_importfilter_id ON test_importfilter(test_id)"],
                "schema_changed": 1426195822
            }
        }
    }

    if os.path.isfile(db_path):
        os.unlink(db_path)
    db = Db.Db(schema, db_path)
    db.checkTables()

    def stop():
        db.close("Test db cleanup")
        os.unlink(db_path)

    request.addfinalizer(stop)
    return db


@pytest.fixture(params=["sslcrypto", "sslcrypto_fallback", "libsecp256k1"])
def crypt_bitcoin_lib(request, monkeypatch):
    monkeypatch.setattr(CryptBitcoin, "lib_verify_best", request.param)
    CryptBitcoin.loadLib(request.param)
    return CryptBitcoin

@pytest.fixture(scope='function', autouse=True)
def logCaseStart(request):
    global time_start
    time_start = time.time()
    logging.debug("---- Start test case: %s ----" % request._pyfuncitem)
    yield None  # Wait until all test done


# Workaround for pytest bug when logging in atexit/post-fixture handlers (I/O operation on closed file)
def workaroundPytestLogError():
    import _pytest.capture
    write_original = _pytest.capture.EncodedFile.write

    def write_patched(obj, *args, **kwargs):
        try:
            write_original(obj, *args, **kwargs)
        except ValueError as err:
            if str(err) == "I/O operation on closed file":
                pass
            else:
                raise err

    def flush_patched(obj, *args, **kwargs):
        try:
            obj.buffer.flush(*args, **kwargs)
        except ValueError as err:
            if str(err).startswith("I/O operation on closed file"):
                pass
            else:
                raise err

    _pytest.capture.EncodedFile.write = write_patched
    _pytest.capture.EncodedFile.flush = flush_patched


workaroundPytestLogError()

@pytest.fixture(scope='session', autouse=True)
def disableLog():
    yield None  # Wait until all test done
    logging.getLogger('').setLevel(logging.getLevelName(logging.CRITICAL))

