import types
import sys
import pytest

class DummyConfig:
    def __init__(self, wip, deprecated):
        self.wip = wip
        self.deprecated = deprecated

@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    dummy_config = types.ModuleType("Config")
    dummy_config.config = DummyConfig(False, False)
    monkeypatch.setitem(sys.modules, "Config", dummy_config)

def foo():
    return True

def test_wip_use_ok():
    from . import deprecate
    deprecate.config.wip = True
    assert deprecate.wip(foo)()

def test_wip_raise():
    from . import deprecate
    deprecate.config.wip = False
    with pytest.raises(NotImplementedError):
        deprecate.wip(foo)()

def test_deprecate_ok():
    from . import deprecate
    deprecate.config.deprecated = True
    assert deprecate.deprecated(foo)()

def test_wip_raise():
    from . import deprecate
    deprecate.config.deprecated = False
    with pytest.raises(deprecate.DeprecatedError):
        deprecate.deprecated(foo)()
