from .Util import ws_api_call, requires_permission, wrap_api_reply

@ws_api_call
@wrap_api_reply
def ping(ws, to):
    """Ping websocket connection"""
    return 'pong'

@ws_api_call
@wrap_api_reply
def serverInfo(ws, to):
    """Get basic server info"""
    return ws.formatServerInfo()

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
def remoteConnectionList(ws, to):
    """List remote connections (ref old Stats plugin)"""
    import main
    return [
        {
            'id': conn.id,
            'dir': conn.type,
            'address': f"{conn.ip}:{conn.port}",
            'port_open': conn.handshake.get("port_opened"),
            'ping': conn.last_ping_delay,
            'version': f"{conn.handshake.get('version')} r{conn.handshake.get('rev', 0)}",
            'bytes_sent': conn.bytes_sent,
            'bytes_recieved': conn.bytes_recv,
            'num_sites': conn.sites,
        }
        for conn in main.file_server.connections()
    ]
