from numbers import Number

from .JSONWalk import walkJSON, Delete

def test_sanity():
    pass

samples = {
    'mix1': [1, 2, {"a": 3}, [4, 5], "six"],
    'mix2': [1, 2, {"a": 3}, [4, 5, {6: {7: 8}}], "nine"]
}

def test_identity():
    for obj in samples.values():
        assert obj == walkJSON(obj)

def incValue(x):
    if isinstance(x, Number):
        return x + 1
    return x

def test_value_increment():
    obj = samples['mix1']
    res = walkJSON(obj, onValue=incValue)
    assert res == [2, 3, {"a": 4}, [5, 6], "six"]

def test_delete():
    obj = samples['mix2']
    n = 0
    def countAndDelete(*args):
        nonlocal n
        n += 1
        return Delete
    res = walkJSON(obj, onDict=countAndDelete)
    assert res == [1, 2, [4, 5], "nine"]
    assert n == 2
    n = 0
    res = walkJSON(obj, onList=countAndDelete)
    assert res == None
    assert n == 1
    n = 0
    res = walkJSON(obj, onDictElement=countAndDelete)
    assert res == [1, 2, {}, [4, 5, {}], "nine"]
    assert n == 2

def test_capitalize():
    obj = samples['mix2']
    def capitalize(k, v):
        if isinstance(k, str):
            return k.upper(), v
        return None
    res = walkJSON(obj, onDictElement = capitalize)
    assert res == [1, 2, {"A": 3}, [4, 5, {6: {7: 8}}], "nine"]
