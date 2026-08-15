"""Trio port of a scoped slice of plugins/UiConfig/UiConfigPlugin.py --
just configList, a read-only dump of the app's argparse-backed config
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

from P2P.Ui.commands import _requireAdmin, command


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
