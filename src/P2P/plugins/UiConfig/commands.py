"""Trio port of a scoped slice of plugins/UiConfig/UiConfigPlugin.py --
configList and configSet for the app's argparse-backed config
values (current, default, and any change pending a restart). Same
"add new websocket commands" pattern established by
P2P/plugins/CryptMessage, P2P/plugins/Newsfeed, P2P/plugins/Sidebar.

Deliberately NOT ported: the original's UiRequestPlugin half (the
/Config HTML page at actionWrapper, its media at actionUiMedia) --
that's an HTTP route, not a websocket command, same category of gap as
the whole UiPluginManager/Stats/Benchmark plugins already set aside.
No config-set counterpart either (the original's config editing lives
in that same HTML page's own JS talking to other websocket commands
not covered by this pass).
"""
from Config import config

from P2P.Ui.commands import _param, _requireAdmin, command


@command("configList")
async def _cmdConfigList(session, params):
    _requireAdmin(session)

    back = {}
    config_values = dict(vars(config.arguments))
    config_values.update(config.pending_changes)
    for key, val in config_values.items():
        if key not in config.keys_api_change_allowed:
            continue
        is_pending = key in config.pending_changes
        if val is None and is_pending:
            val = config.parser.get_default(key)
        back[key] = {
            "value": val,
            "default": config.parser.get_default(key),
            "pending": is_pending,
        }
    return back


@command("configSet")
async def _cmdConfigSet(session, params):
    _requireAdmin(session)
    key = _param(params, "key", 0)
    value = _param(params, "value", 1)
    if key not in config.keys_api_change_allowed:
        raise ValueError("Forbidden: You cannot set this config key")
    if key == "open_browser" and value not in ("default_browser", "False"):
        raise ValueError("Forbidden: Invalid value")
    if isinstance(value, list):
        value = [line for line in value if line]
    config.saveValue(key, value)
    if key in config.keys_restart_need:
        config.need_restart = True
        config.pending_changes[key] = value
    else:
        actual = config.parser.get_default(key) if value is None else value
        setattr(config, key, actual)
        setattr(config.arguments, key, actual)
    return "ok"
