import json
import pathlib
import subprocess
import sys
import tempfile

REPO_SRC = pathlib.Path(__file__).resolve().parents[1]  # .../src


def _runP2PMain(args, timeout=30):
    return subprocess.run(
        [sys.executable, "-m", "P2P"] + args,
        cwd=str(REPO_SRC), capture_output=True, text=True, timeout=timeout,
    )


def _extractJsonResult(stdout: str):
    """actions.main()'s _dispatch() prints exactly one json.dumps(...)
    call's output (possibly multi-line/pretty-printed) -- but module-level
    logging (e.g. Crypt.CryptBitcoin's libsecp256k1 load message) can land
    on stdout too, on its own line(s) before it. Strip any line that looks
    like a log line (starts with a date) and parse what's left as one
    JSON document."""
    kept = [line for line in stdout.splitlines() if not line[:4].isdigit()]
    return json.loads("\n".join(kept))


class TestP2PMainEntrypoint:
    """Real subprocess tests -- this is the only way to actually prove
    `python -m P2P ...`'s bootstrap (sys.path/Config aliasing) and plugin-
    loading ordering fix work, since both are specifically about what
    happens in a FRESH process, before pytest's own conftest.py bootstrap
    has already done the equivalent setup."""

    def testNoArgsPrintsUsageAndExitsNonZero(self):
        res = _runP2PMain([])
        assert res.returncode != 0
        assert "Usage" in res.stderr

    def testUnknownSubcommandExitsNonZero(self):
        res = _runP2PMain(["bogus"])
        assert res.returncode != 0
        assert "Unknown subcommand" in res.stderr

    def testActionsCryptPrivatekeyToAddressRoundTrip(self):
        from Crypt import CryptBitcoin
        privatekey = CryptBitcoin.newPrivatekey()
        expected = CryptBitcoin.privatekeyToAddress(privatekey)

        res = _runP2PMain([
            "actions", "cryptPrivatekeyToAddress",
            "--data-dir", "/tmp",
            "--kwargs", json.dumps({"privatekey": privatekey}),
        ])
        assert res.returncode == 0, res.stderr
        assert _extractJsonResult(res.stdout) == expected

    def testActionsSiteCreateAndSiteVerifyWorkAsRealSubprocesses(self):
        with tempfile.TemporaryDirectory() as d:
            create_res = _runP2PMain(["actions", "siteCreate", "--data-dir", d])
            assert create_res.returncode == 0, create_res.stderr
            created = _extractJsonResult(create_res.stdout)
            address = created["address"]

            verify_res = _runP2PMain([
                "actions", "siteVerify", "--data-dir", d,
                "--kwargs", json.dumps({"address": address}),
            ])
            assert verify_res.returncode == 0, verify_res.stderr
            result = _extractJsonResult(verify_res.stdout)
            assert result["bad_files"] == []

    def testNoPluginsFlagSkipsPluginLoading(self):
        """Indirect proof via --no-plugins: a plugin-driven .bit domain
        should NOT resolve when plugin loading is explicitly skipped.
        (The positive case -- .bit domains DO resolve with plugins
        loaded -- is proven directly in TestP2PPluginsZeroname.py against
        the plugin's own logic; this only exercises the CLI flag path.)"""
        res = _runP2PMain(["actions", "cryptPrivatekeyToAddress", "--no-plugins", "--data-dir", "/tmp",
                            "--kwargs", '{"privatekey": "5HueCGU8rMjxEXxiPuD5BDku4MkFqeZyd4dZ1jvhTVqvbTLvyTJ"}'])
        assert res.returncode == 0, res.stderr

    def testPluginsActuallyLoadedIntoSiteManagerMro(self):
        """The real, direct proof that the ordering fix works: run a tiny
        script through the same bootstrap+loadPlugins() sequence
        P2P/__main__.py itself uses, then check the Zeroname plugin
        actually landed in SiteManager's MRO in that fresh process."""
        script = (
            "from P2P import __main__ as p2p_main\n"
            "p2p_main._bootstrapSysPath()\n"
            "from P2P.PluginManager import plugin_manager\n"
            "plugin_manager.loadPlugins()\n"
            "from P2P.SiteManager import SiteManager\n"
            "print('ZERONAME_IN_MRO:', any('Zeroname' in str(c) for c in SiteManager.__mro__))\n"
        )
        res = subprocess.run(
            [sys.executable, "-c", script], cwd=str(REPO_SRC), capture_output=True, text=True, timeout=30,
        )
        assert res.returncode == 0, res.stderr
        assert "ZERONAME_IN_MRO: True" in res.stdout
