"""Various utils related to JSON handling"""

class ToJSONError(TypeError):
    def __init__(self, obj, reason):
        self.obj = obj
        super().__init__(f"Object `{obj}` has incorrect/unknown type ({type(obj)}) to {reason}")

def toJSONKey(key) -> str:
    """Converts key-like object to json key (aka str)"""
    if type(key) is str:
        return key
    if type(key) is Path:
        return str(key)
    raise ToJSONError(key, "convert to JSON key")

def toJSONValue(x):
    if type(x) is dict:
        return toJSONDict(x)
    if type(x) in (list, tuple):
        return toJSONList(x)
    if type(x) in (str, int, float, bool, type(None)):
        return x
    if type(x) is bytes:
        return '0x' + x.hex()
    raise ToJSONError(x, "convert to JSON value")

def toJSONList(xs: list | tuple) -> list:
    return [
        toJSONValue(x)
        for x in xs
    ]

def toJSONDict(d: dict) -> dict:
    """Converts arbitrary dict to JSON-compatible one"""
    return {
        toJSONKey(key): toJSONValue(value)
        for key, value in d.items()
    }

class Delete:
    pass

def walkJSON(target, onDict=None, onDictElement=None, onList=None, onValue=None):
    def walk(obj):
        if isinstance(obj, dict):
            if onDict:
                res = onDict(obj)
                if res is None:
                    pass
                elif res is Delete:
                    return None
                else:
                    return res
            res = {}
            for k, v in obj.items():
                if onDictElement and (kv := onDictElement(k, v)):
                    if kv is Delete:
                        continue
                    k, v = kv
                else:
                    v = walk(v)
                    if v is None:
                        continue
                res[k] = v
            return res
        elif isinstance(obj, list):
            if onList:
                res = onList(obj)
                if res is None:
                    pass
                elif res is Delete:
                    return None
                else:
                    return res
            res = []
            for x in obj:
                y = walk(x)
                if y is not None:
                    res.append(y)
            return res
        else:
            if onValue and (res := onValue(obj)):
                if res is Delete:
                    return None
                return res
            return obj
    return walk(target)
