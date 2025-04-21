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
