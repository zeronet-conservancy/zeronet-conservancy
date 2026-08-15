"""Trio port of a scoped slice of plugins/UiPluginManager/UiPluginManagerPlugin.py --
pluginList/pluginConfigSet only. Same "add new commands" pattern
P2P/plugins/CryptMessage established -- no import-ordering ceremony
needed. Previously set aside entirely (the whole plugin needs
UiRequestPlugin-level HTTP wrapper/media hooks and config-driven
enable/disable with restart semantics) -- re-surveyed once
P2P.PluginManager turned out to already have everything this slice
needs: listPlugins()/config/saveConfig() were all built in Phase 8,
just never exposed over the websocket command surface.

Ported: pluginList (wraps P2P.PluginManager.plugin_manager.listPlugins()
directly) and pluginConfigSet (writes to plugin_manager.config/
saveConfig() -- toggling "enabled" takes effect on next process start,
same restart-required semantics the original already has; there's
nothing to hot-reload here in either stack).

Deliberately NOT ported:
  - actionWrapper/actionUiMedia -- the /Plugins HTML management page and
    its assets. An HTTP route, not a websocket command; same category
    of gap as UiConfig's own UiRequestPlugin half, already set aside
    there.
  - plugin_info.json enrichment (per-plugin metadata merged into the
    list) and the "source"/site-hosted-plugin distinction -- both
    assume a convention (a plugin_info.json file per plugin dir, and
    plugins hosted inside a ZeroNet site rather than shipped with the
    app) that doesn't exist for anything under P2P/plugins/ yet. Every
    P2P plugin is what the original would call "builtin"; pluginConfigSet
    here only takes a plugin dir_name, not source+inner_path.
  - Hot install/uninstall of a plugin from a live site (the original's
    site-hosted-plugin half again) -- P2P.PluginManager only ever scans
    its own P2P/plugins/ directory on disk, matching how loadPlugins()
    already works everywhere else in this stack.
"""
from P2P.PluginManager import plugin_manager
from P2P.Ui.commands import _requireAdmin, _param, command


@command("pluginList")
async def _cmdPluginList(session, params):
    _requireAdmin(session)
    return {"plugins": plugin_manager.listPlugins(list_disabled=True)}


@command("pluginConfigSet")
async def _cmdPluginConfigSet(session, params):
    _requireAdmin(session)
    dir_name = _param(params, "dir_name", 0)
    key = _param(params, "key", 1)
    value = _param(params, "value", 2)

    plugin_name = dir_name[len("disabled-"):] if dir_name.startswith("disabled-") else dir_name
    known_names = {plugin["dir_name"] for plugin in plugin_manager.listPlugins(list_disabled=True)}
    if dir_name not in known_names and ("disabled-" + dir_name) not in known_names:
        return {"error": "Plugin not found"}

    config_plugin = plugin_manager.config["builtin"].setdefault(plugin_name, {})
    if key in config_plugin and value is None:
        del config_plugin[key]
    else:
        config_plugin[key] = value
    plugin_manager.saveConfig()

    return "ok"
