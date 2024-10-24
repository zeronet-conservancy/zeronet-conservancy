"""New-style API handlers

Later on, we're likely going to split individual calls and keep this file as
import only.
"""

from .UiWebsocket import ws_api_call, requires_permission
from Content import ContentDb

@ws_api_call('ping')
def ping(ws, to):
    """Ping websocket connection"""
    ws.response(to, 'pong')

@ws_api_call('serverInfo')
def serverInfo(ws, to):
    """Get server info"""
    ws.response(to, ws.formatServerInfo())

## below are size limit rules related calls - to be split out

@ws_api_call('getSizeLimitRules')
@requires_permission('ADMIN')
def getSizeLimitRules(ws, to):
    """Returns all size limit rules"""
    cdb = ContentDb.getContentDb()
    res = cdb.getSizeLimitRules()
    from rich import print
    print(res)
    ws.response(to, res)
