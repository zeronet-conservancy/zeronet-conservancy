"""Trio port of a scoped slice of plugins/Chart/ChartPlugin.py --
chartDbQuery only, the admin-only raw-SELECT command the real dashboard
site's own Charts page uses. Found live, auditing every bundled site's
own Page.cmd() calls against this stack's registered commands (the same
investigation that found fileRules missing for ZeroMail).

NOT ported:
  - ChartCollector (the periodic background sampler that actually writes
    rows -- bandwidth/peer-count/site-size samples across many separate
    metric types, each with its own "what changed since last sample"
    logic). A genuinely large, separate undertaking, not a small
    addition on top of chartDbQuery itself. Without it, chart.db (see
    chart_db.py) is real but empty -- chartDbQuery returns real (empty)
    results, not a lie, same "genuine no-op until the producer exists"
    contract announcerStats already documents for its own no-tracker-
    plugin case.
  - chartGetPeerLocations -- depends on GeoLite2 IP geolocation lookup,
    already a deliberate, documented exclusion elsewhere in this stack
    (see plugins/Sidebar/render.py's own module docstring: "a large,
    separate, network-egress-heavy feature nothing else in this stack
    depends on"). Porting it here would contradict that existing
    decision, not extend it.
"""
from P2P.Ui.commands import _param, _requireAdmin, command

from .chart_db import getChartDb


@command("chartDbQuery")
async def _cmdChartDbQuery(session, params):
    _requireAdmin(session)
    query = _param(params, "query", 0)
    query_params = _param(params, "params", 1)
    if not query or not query.strip().upper().startswith("SELECT"):
        return {"error": "Only SELECT query supported"}

    db = await getChartDb(session)
    try:
        res = await db.execute(query, query_params)
        rows = [dict(row) for row in res.fetchall()]
    except Exception as err:
        return {"error": str(err)}
    return rows
