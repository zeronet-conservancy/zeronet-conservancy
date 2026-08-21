import json
import pathlib
import tempfile

from P2P.PluginManager import PluginManager, acceptPlugins, registerTo, plugin_manager


def _makePluginDir(root: pathlib.Path, name: str, code: str) -> None:
    plugin_dir = root / name
    plugin_dir.mkdir()
    (plugin_dir / "__init__.py").write_text(code)


class TestP2PPluginManagerListing:
    def testListPluginsFindsEnabledDirs(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            _makePluginDir(root, "Foo", "")
            _makePluginDir(root, "disabled-Bar", "")
            pm = PluginManager(path_plugins=str(root))

            enabled = pm.listPlugins()
            assert [p["name"] for p in enabled] == ["Foo"]

    def testListPluginsWithDisabledIncludesBoth(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            _makePluginDir(root, "Foo", "")
            _makePluginDir(root, "disabled-Bar", "")
            pm = PluginManager(path_plugins=str(root))

            all_plugins = pm.listPlugins(list_disabled=True)
            names = {(p["name"], p["enabled"]) for p in all_plugins}
            assert names == {("Foo", True), ("Bar", False)}

    def testConfigOverrideCanEnableDisabledPlugin(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            _makePluginDir(root, "disabled-Bar", "")
            pm = PluginManager(path_plugins=str(root))
            pm.config["builtin"]["Bar"] = {"enabled": True}

            enabled = pm.listPlugins()
            assert [p["name"] for p in enabled] == ["Bar"]

    def testSkipsPycacheAndNonDirs(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / "__pycache__").mkdir()
            (root / "stray_file.py").write_text("")
            _makePluginDir(root, "Foo", "")
            pm = PluginManager(path_plugins=str(root))

            assert [p["name"] for p in pm.listPlugins()] == ["Foo"]


class TestP2PPluginManagerConfigPersistence:
    def testSaveThenLoadRoundTrips(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            config_path = root / "plugins.json"
            pm1 = PluginManager(config_path=config_path, path_plugins=str(root))
            pm1.config["builtin"]["Something"] = {"enabled": False}
            pm1.saveConfig()

            pm2 = PluginManager(config_path=config_path, path_plugins=str(root))
            assert pm2.config["builtin"]["Something"] == {"enabled": False}

    def testSaveConfigWithoutPathIsNoop(self):
        with tempfile.TemporaryDirectory() as d:
            pm = PluginManager(path_plugins=d)
            pm.saveConfig()  # Must not raise

    def testLoadConfigWithMissingFileStartsEmpty(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            pm = PluginManager(config_path=root / "does-not-exist.json", path_plugins=d)
            assert pm.config == {"builtin": {}}


class TestP2PPluginManagerLoading:
    def testLoadPluginsImportsEachEnabledDir(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            _makePluginDir(root, "P2PTestPluginLoadA", "loaded_marker = True\n")
            pm = PluginManager(path_plugins=str(root))

            all_loaded = pm.loadPlugins()
            assert all_loaded is True
            assert "P2PTestPluginLoadA" in pm.plugin_names

    def testLoadPluginsRunsAfterLoadHooks(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            pm = PluginManager(path_plugins=str(root))
            calls = []
            pm.after_load.append(lambda: calls.append("ran"))
            pm.loadPlugins()
            assert calls == ["ran"]

    def testLoadPluginsSurvivesImportError(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            _makePluginDir(root, "P2PTestPluginBroken", "raise RuntimeError('boom')\n")
            pm = PluginManager(path_plugins=str(root))

            all_loaded = pm.loadPlugins()
            assert all_loaded is False
            # Still recorded as an attempted load, matching the original's behavior
            assert "P2PTestPluginBroken" in pm.plugin_names


class TestP2PPluginManagerRegistration:
    """The real end-to-end proof: a plugin class registered via
    registerTo() actually ends up in a class decorated with
    @acceptPlugins's MRO, and method overriding (super() calling through
    to the base class) works. Uses the real module-level plugin_manager
    singleton, same as every actual pluggable class in this package --
    unique class names per test avoid cross-test interference."""

    def testRegisteredPluginOverridesMethod(self):
        @registerTo("P2PTestWidgetA")
        class WidgetPluginA:
            def greet(self):
                base = super().greet()
                return base + ", plugin was here"

        @acceptPlugins
        class P2PTestWidgetA:
            def greet(self):
                return "hello"

        assert P2PTestWidgetA().greet() == "hello, plugin was here"

    def testMultiplePluginsChainInRegistrationOrder(self):
        @registerTo("P2PTestWidgetB")
        class WidgetPluginB1:
            def greet(self):
                return super().greet() + "-1"

        @registerTo("P2PTestWidgetB")
        class WidgetPluginB2:
            def greet(self):
                return super().greet() + "-2"

        @acceptPlugins
        class P2PTestWidgetB:
            def greet(self):
                return "base"

        assert P2PTestWidgetB().greet() == "base-1-2"

    def testNoPluginsRegisteredIsANoop(self):
        @acceptPlugins
        class P2PTestWidgetUnplugged:
            def greet(self):
                return "unmodified"

        # No @registerTo("P2PTestWidgetUnplugged") anywhere -- acceptPlugins
        # must return the class completely unchanged.
        assert P2PTestWidgetUnplugged is plugin_manager.pluggable["P2PTestWidgetUnplugged"]
        assert P2PTestWidgetUnplugged().greet() == "unmodified"

    def testPluggableRegistryTracksBaseClass(self):
        @acceptPlugins
        class P2PTestWidgetC:
            pass

        assert plugin_manager.pluggable["P2PTestWidgetC"] is P2PTestWidgetC
