from .Util import ws_api_call, requires_permission
from Content import ContentDb

@ws_api_call
@requires_permission('ADMIN')
def getSizeLimitRules(ws, to):
    """Returns all size limit rules"""
    cdb = ContentDb.getContentDb()
    res = cdb.getSizeLimitRules()
    from rich import print
    print(res)
    ws.response(to, res)

@ws_api_call
@requires_permission('ADMIN')
def addPrivateSizeLimitRule(ws, to, address, rule, value, priority):
    cdb = ContentDb.getContentDb()
    try:
        cdb.addPrivateSizeLimitRule(address, rule, value, priority)
    except Exception as err:
        res = {
            'error': f"Error while adding: {err}",
        }
    else:
        res = {
            'ok': True,
        }
    ws.response(to, res)
