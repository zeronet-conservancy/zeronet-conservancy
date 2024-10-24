"""New-style API handlers

Later on, we're likely going to split individual calls and keep this file as
import only.
"""

from .UiWebsocket import ws_api_call

@ws_api_call('ping')
def ping(ws, to):
    """Ping websocket connection"""
    ws.response(to, 'pong')

@ws_api_call('serverInfo')
def serverInfo(ws, to):
    """Get server info"""
    ws.response(to, ws.formatServerInfo())
