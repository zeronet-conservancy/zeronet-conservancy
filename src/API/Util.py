import Ui.UiWebsocket as UiWebsocket

def requires_permission(permission):
    """Decorator for adding required permissions to API handlers"""
    def wrapper(f):
        if not hasattr(f, 'required_permissions'):
            f.required_permissions = set()
        f.required_permissions.add(permission)
        return f
    return wrapper

def ws_api_call(f):
    """Decorator for websocket API handler functions

    Usage:
    @ws_api_call
    def myCoolApi(args):
        pass

    NOTE that the function name is used as API call name
    """
    UiWebsocket.registerApiCall(f.__name__, f)
    return f

def wrap_api_ok(f):
    def inner(ws, to, *args, **kwargs):
        try:
            f(ws, to, *args, **kwargs)
        except Exception as err:
            print(err)
            res = {
                'error': f"Error on API call `{f.__name__}`: {err}",
            }
        else:
            res = {
                'ok': True,
            }
        ws.response(to, res)
    inner.__name__ = f.__name__
    return inner
