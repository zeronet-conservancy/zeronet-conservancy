from .Util import ws_api_call, requires_permission, wrap_api_reply
from Content import ContentDb

@ws_api_call
@requires_permission('ADMIN')
@wrap_api_reply
def signerList(ws, to):
    """List all known public keys/addresses"""
    cdb = ContentDb.getContentDb()
    res = cdb.getAllSigners()
    return res
