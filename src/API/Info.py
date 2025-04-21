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
