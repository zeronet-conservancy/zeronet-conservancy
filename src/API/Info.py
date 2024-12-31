from Ui.UiWebsocket import ws_api_call, requires_permission

@ws_api_call('ping')
def ping(ws, to):
    """Ping websocket connection"""
    ws.response(to, 'pong')

@ws_api_call('serverInfo')
def serverInfo(ws, to):
    """Get server info"""
    ws.response(to, ws.formatServerInfo())
