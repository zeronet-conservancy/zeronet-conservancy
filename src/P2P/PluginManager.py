"""Trio port of Plugin/PluginManager.py's plugin loading/registration
mechanism. PluginManager.py itself has zero gevent references -- it's
pure filesystem scanning, dynamic import, and multiple-inheritance class
composition -- so this is a real port of the loading logic, not a
gevent-to-trio rewrite. What changes is decoupling from the legacy
global Config singleton: this takes an explicit optional config_path
instead of reading config.config_dir/plugins.json, matching this
package's established convention (SiteManager/UserManager take explicit
paths too).

Still a module-level singleton, same as the original, because it has to
be: acceptPlugins()/registerTo() are decorators, so they run at class-
definition time, and there's no way to make plugin loading fully lazy or
parameterized without losing the decorator syntax.

Points at P2P/plugins/ (a new, separate package), NOT the repo-root
plugins/ directory the legacy PluginManager scans -- those are two
different, incompatible plugin ecosystems now, not one shared set. A
trio-native plugin under P2P/plugins/Foo registers against P2P.Site/
P2P.SiteManager/etc via this module's registerTo(); the existing
gevent-era plugins under repo-root plugins/ register against the legacy
Site/SiteManager/etc via Plugin.PluginManager, and main.py/Actions.py
(the still-live legacy entrypoint) still imports and runs those. Pointing
this module's default at the same directory the legacy loader scans
would mean any trio-native rewrite of a plugin file silently breaks the
legacy app still using it -- see the module docstring in
P2P/plugins/__init__.py for the rest of this split's reasoning.

Ordering caveat (inherited from the original, not introduced by this
port): registerTo("SomeClass") only affects a class decorated with
@acceptPlugins AFTER that registration happened -- so plugin modules
must be imported (via loadPlugins()) before the classes they target are
themselves defined/imported. The original handles this by calling
loadPlugins() very early in main.py, before importing Site/User/etc.
Wiring loadPlugins() into P2P/app.py's or P2P/actions.py's bootstrap
sequence early enough is real, separate follow-up work -- not done here.
Decorating a class with @acceptPlugins before any plugin loading has
happened is still safe and a no-op (matches the original's own fallback:
no registered plugins for that class name just returns the base class
unchanged), so pluggable classes can be marked now without requiring the
full bootstrap wiring to land first.

NOT ported:
  - reloadPlugins() -- hot class-patching via gc.get_objects() over every
    live instance in the process, for debug-mode auto-reload-on-file-
    change. Genuinely complex, debug-tooling-only, and depends on
    DebugReloader (itself not ported). A real gap for interactive plugin
    development, not for actually running plugins.
  - migratePlugins() -- a one-off "delete the old Mute plugin directory"
    migration for a plugin renamed years ago. Nothing to migrate here.
"""
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from . import plugins as p2p_plugins

log = logging.getLogger("P2P.PluginManager")


class PluginManager:
    def __init__(self, config_path: Path | None = None, path_plugins: str | None = None):
        self.path_plugins = path_plugins or os.path.abspath(os.path.dirname(p2p_plugins.__file__))
        self.plugins: dict[str, list] = defaultdict(list)  # class name -> list of plugin classes
        self.pluggable: dict[str, type] = {}  # class name -> original (undecorated) base class
        self.plugin_names: list[str] = []
        self.after_load: list = []
        self.config_path = config_path
        self.config: dict = {}
        self.loadConfig()
        self.config.setdefault("builtin", {})

        if self.path_plugins not in sys.path:
            sys.path.append(self.path_plugins)

    def loadConfig(self) -> None:
        if self.config_path and self.config_path.is_file():
            try:
                self.config = json.loads(self.config_path.read_text(encoding="utf8"))
            except Exception as err:
                log.error("Error loading %s: %s", self.config_path, err)
                self.config = {}
        else:
            self.config = {}

    def saveConfig(self) -> None:
        if not self.config_path:
            return
        self.config_path.write_text(
            json.dumps(self.config, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf8"
        )

    def listPlugins(self, list_disabled: bool = False) -> list:
        found = []
        for dir_name in sorted(os.listdir(self.path_plugins)):
            dir_path = os.path.join(self.path_plugins, dir_name)
            if dir_name == "__pycache__" or not os.path.isdir(dir_path):
                continue

            plugin_name = dir_name[len("disabled-"):] if dir_name.startswith("disabled-") else dir_name
            is_enabled = not dir_name.startswith("disabled")
            plugin_config = self.config["builtin"].get(plugin_name, {})
            if "enabled" in plugin_config:
                is_enabled = plugin_config["enabled"]

            if not is_enabled and not list_disabled:
                continue

            found.append({
                "name": plugin_name,
                "dir_name": dir_name,
                "dir_path": dir_path,
                "enabled": is_enabled,
                "loaded": plugin_name in self.plugin_names,
            })
        return found

    def loadPlugins(self) -> bool:
        all_loaded = True
        s = time.time()
        for plugin in self.listPlugins():
            log.debug("Loading plugin: %s", plugin["name"])
            try:
                sys.modules[plugin["name"]] = __import__(plugin["dir_name"])
            except Exception as err:
                log.error("Plugin %s load error: %s", plugin["name"], err)
                all_loaded = False
            if plugin["name"] not in self.plugin_names:
                self.plugin_names.append(plugin["name"])

        log.debug("Plugins loaded in %.3fs", time.time() - s)
        for func in self.after_load:
            func()
        return all_loaded


plugin_manager = PluginManager()


def acceptPlugins(base_class):
    class_name = base_class.__name__
    plugin_manager.pluggable[class_name] = base_class
    if class_name in plugin_manager.plugins and plugin_manager.plugins[class_name]:
        classes = plugin_manager.plugins[class_name][:]
        classes.reverse()
        classes.append(base_class)  # Base class goes last in MRO
        plugined_class = type(class_name, tuple(classes), dict())
        log.debug("New class accepts plugins: %s (loaded plugins: %s)", class_name, classes)
    else:
        plugined_class = base_class
    return plugined_class


def registerTo(class_name: str):
    log.debug("New plugin registered to: %s", class_name)
    if class_name not in plugin_manager.plugins:
        plugin_manager.plugins[class_name] = []

    def classDecorator(cls):
        plugin_manager.plugins[class_name].append(cls)
        return cls
    return classDecorator


def afterLoad(func):
    plugin_manager.after_load.append(func)
    return func
