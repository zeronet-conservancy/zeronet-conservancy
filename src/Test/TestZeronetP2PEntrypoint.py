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

RUNNING_ON_RE = re.compile(r"Running on http://([\d.]+):(\d+)")


def _waitForBoundUiPort(log_path: pathlib.Path, deadline: float) -> tuple[str, int]:
    while time.time() < deadline:
        if log_path.is_file():
            match = RUNNING_ON_RE.search(log_path.read_text(errors="replace"))
            if match:
                return match.group(1), int(match.group(2))
        time.sleep(0.1)
    raise TimeoutError("Server never logged its bound UI address: %s" % log_path.read_text(errors="replace"))


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
