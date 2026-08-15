"""Phase 10 cutover, first slice: proves `zeronet.py main --p2p` -- the
REAL, shipped entrypoint script, not `python -m P2P app` -- actually
boots and serves the trio-native P2P stack. Real subprocess only: this
is specifically about what a fresh process invoked the way an end user
would invoke it does, which pytest's own conftest.py bootstrap doesn't
exercise."""
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]  # .../zeronet-conservancy
ZERONET_PY = REPO_ROOT / "zeronet.py"
REPO_SRC = pathlib.Path(__file__).resolve().parents[1]  # .../src

RUNNING_ON_RE = re.compile(r"Running on http://([\d.]+):(\d+)")


def _createP2PSite(data_dir: pathlib.Path) -> dict:
    """python -m P2P actions siteCreate -- a P2P-native site, listed in
    the data_dir/sites.json P2P.SiteManager itself reads (the legacy
    Actions.siteCreate() writes sites.json to a different location, so a
    legacy-created site wouldn't be visible to a --p2p CLI action against
    the same --data-dir; not a bug, just the two stacks' storage layouts
    not lining up, same "clean break" already accepted for the wire
    protocol)."""
    res = subprocess.run(
        [sys.executable, "-m", "P2P", "actions", "siteCreate", "--data-dir", str(data_dir), "--kwargs", "{}"],
        cwd=str(REPO_SRC), capture_output=True, text=True, timeout=30,
    )
    assert res.returncode == 0, res.stderr
    import json
    return json.loads(res.stdout)


def _runZeronetPy(args, timeout=30):
    return subprocess.run(
        [sys.executable, str(ZERONET_PY)] + args,
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout,
    )


def _waitForBoundUiPort(log_path: pathlib.Path, deadline: float) -> tuple[str, int]:
    while time.time() < deadline:
        if log_path.is_file():
            match = RUNNING_ON_RE.search(log_path.read_text(errors="replace"))
            if match:
                return match.group(1), int(match.group(2))
        time.sleep(0.1)
    raise TimeoutError("Server never logged its bound UI address: %s" % log_path.read_text(errors="replace"))


def _spawnMain(data_dir: pathlib.Path, extra_main_args=(), extra_global_args=()):
    """Launches `zeronet.py main` (plus whatever p2p flags the caller
    wants) as a real subprocess, logging to data_dir/stdout.log. Caller
    is responsible for terminating the returned Popen."""
    log_path = data_dir / "stdout.log"
    log_file = open(log_path, "wb")
    proc = subprocess.Popen(
        [
            sys.executable, str(ZERONET_PY),
            "--data-dir", str(data_dir),
            "--ui-port", "0", "--fileserver-port", "0",
            "--no-dht", "--tor", "disable", "--batch",
            *extra_global_args,
            "main", *extra_main_args,
        ],
        cwd=str(REPO_ROOT), stdout=log_file, stderr=subprocess.STDOUT,
    )
    return proc, log_path


def _terminate(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


class TestZeronetP2PDefaultFlip:
    """Phase 10 default flip: `zeronet.py main` with no flags at all now
    runs the trio-native stack (Config.py's --p2p defaults to True as of
    this change), and --no-p2p is the escape hatch back to the exact
    previous default behavior. See Actions.mainP2P()'s own docstring for
    what --no-p2p is still needed for (repo-root plugins/, Multiuser,
    UiPassword, Tor SOCKS5 dial-out)."""

    def testMainWithNoFlagsDefaultsToP2P(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            proc, log_path = _spawnMain(data_dir)
            try:
                _waitForBoundUiPort(log_path, time.time() + 20)
            finally:
                _terminate(proc)
            log_text = log_path.read_text(errors="replace")

        assert "P2P app running" in log_text

    def testMainWithNoP2PFlagRunsLegacyServer(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            proc, log_path = _spawnMain(data_dir, extra_main_args=["--no-p2p"])
            try:
                deadline = time.time() + 20
                while time.time() < deadline:
                    if log_path.is_file() and "Starting servers" in log_path.read_text(errors="replace"):
                        break
                    time.sleep(0.1)
                else:
                    raise TimeoutError("Legacy server never logged its startup line")
            finally:
                _terminate(proc)
            log_text = log_path.read_text(errors="replace")

        assert "Starting servers" in log_text
        assert "P2P app running" not in log_text


class TestZeronetP2PEntrypoint:
    def testMainWithP2PFlagBootsAndServesRealHttp(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            log_path = data_dir / "stdout.log"

            with open(log_path, "wb") as log_file:
                proc = subprocess.Popen(
                    [
                        sys.executable, str(ZERONET_PY),
                        "--data-dir", str(data_dir),
                        "--ui-port", "0", "--fileserver-port", "0",
                        "--no-dht", "--tor", "disable", "--batch",
                        "main", "--p2p",
                    ],
                    cwd=str(REPO_ROOT), stdout=log_file, stderr=subprocess.STDOUT,
                )
            try:
                ip, port = _waitForBoundUiPort(log_path, time.time() + 20)

                try:
                    with urllib.request.urlopen("http://%s:%s/uimedia/" % (ip, port), timeout=5) as resp:
                        status = resp.status
                except urllib.error.HTTPError as err:
                    status = err.code
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)

            log_text = log_path.read_text(errors="replace")

        assert status in (200, 403, 404)  # Real HTTP response, whatever the route decides
        assert "P2P app running" in log_text
        assert "Shutting down (signal: SIGTERM)" in log_text
        assert "guest run" not in log_text  # The bug this signal handling fixed -- see mainP2P()'s own docstring

    def testMainWithP2PFlagLoadsP2PPlugins(self):
        """P2P/plugins/ (CryptMessage, Newsfeed, Sidebar, UiConfig,
        ContentFilter, OptionalManager, Zeroname -- everything ported
        this migration) has its own separate loader (P2P.PluginManager)
        from the legacy plugins/ ecosystem (Plugin.PluginManager, which
        main.py's own init() always loads regardless of --p2p). This is
        the one that matters for the new stack: mainP2P() has to call it
        before importing P2P.app, or none of those commands would be
        registered -- see Actions.mainP2P()'s own docstring for why."""
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            log_path = data_dir / "stdout.log"

            with open(log_path, "wb") as log_file:
                proc = subprocess.Popen(
                    [
                        sys.executable, str(ZERONET_PY),
                        "--data-dir", str(data_dir),
                        "--ui-port", "0", "--fileserver-port", "0",
                        "--no-dht", "--tor", "disable", "--batch",
                        "--console-log-level", "DEBUG",
                        "main", "--p2p",
                    ],
                    cwd=str(REPO_ROOT), stdout=log_file, stderr=subprocess.STDOUT,
                )
            try:
                _waitForBoundUiPort(log_path, time.time() + 20)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)

            log_text = log_path.read_text(errors="replace")

        assert "[P2P.PluginManager] Loading plugin: ContentFilter" in log_text
        assert "[P2P.PluginManager] Loading plugin: Zeroname" in log_text


class TestZeronetP2PCliActions:
    """Beyond `main`, several one-shot CLI actions also gained a --p2p
    flag (Actions._runP2PAction()) delegating to P2P.actions.Actions
    instead of the legacy gevent implementation. Real subprocesses
    against a real P2P-native site (see _createP2PSite()'s own
    docstring for why it has to be P2P-created, not legacy-created)."""

    def testSiteVerifyWithP2PFlag(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            site = _createP2PSite(data_dir)

            res = _runZeronetPy([
                "--data-dir", str(data_dir), "--batch", "siteVerify", site["address"], "--p2p",
            ])

        assert res.returncode == 0, res.stderr
        assert "bad_files" in res.stdout
        assert "'bad_files': []" in res.stdout

    def testSiteSignWithP2PFlag(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            site = _createP2PSite(data_dir)

            res = _runZeronetPy([
                "--data-dir", str(data_dir), "--batch", "siteSign",
                site["address"], site["privatekey"], "--p2p",
            ])

        assert res.returncode == 0, res.stderr
        assert "Site signed!" in res.stdout

    def testDbRebuildWithP2PFlag(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)
            site = _createP2PSite(data_dir)

            res = _runZeronetPy([
                "--data-dir", str(data_dir), "--batch", "dbRebuild", site["address"], "--p2p",
            ])

        assert res.returncode == 0, res.stderr
        assert "Done." in res.stdout

    def testSiteCreateWithP2PFlagThenVerifyRoundTrip(self):
        """Unlike the other tests here, this creates the site through
        zeronet.py itself (`siteCreate --p2p`), not the _createP2PSite()
        helper -- proving siteCreate's own --p2p delegation works, then
        chaining straight into `siteVerify --p2p` against the address it
        printed, a real create-then-verify round trip through the actual
        entrypoint alone."""
        create_re = re.compile(r"'address': '([^']+)'")

        with tempfile.TemporaryDirectory() as d:
            data_dir = pathlib.Path(d)

            create_res = _runZeronetPy([
                "--data-dir", str(data_dir), "--batch", "siteCreate", "--p2p",
            ])
            assert create_res.returncode == 0, create_res.stderr
            match = create_re.search(create_res.stdout)
            assert match, create_res.stdout
            address = match.group(1)

            verify_res = _runZeronetPy([
                "--data-dir", str(data_dir), "--batch", "siteVerify", address, "--p2p",
            ])

        assert verify_res.returncode == 0, verify_res.stderr
        assert "'bad_files': []" in verify_res.stdout
