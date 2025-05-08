"""API related to peer information and manipulation"""

from .Util import ws_api_call, requires_permission, wrap_api_reply
from typeguard import typechecked

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
@typechecked
def connectionSiteList(ws, to, conn_id: int):
    """List sites available from peer via connection"""
    import main
    conn = main.file_server.getConnectionById(conn_id)
    return [peer.site.address for peer in conn.peers]
