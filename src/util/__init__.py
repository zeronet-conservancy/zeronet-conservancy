from .Cached import Cached
from .Event import Event
from .Noparallel import Noparallel
from .Pooled import Pooled


# A number of legacy plugins use ``from util import helper`` while the
# packaged application loads this package as ``src.util``. Keep those imports
# working without eagerly importing helper (which imports Config during
# startup and would create a cycle).
def __getattr__(name):
    if name in {
        'Cached', 'Diff', 'Electrum', 'Event', 'Flag', 'Git', 'GreenletManager',
        'Msgpack', 'Noparallel', 'OpensslFindPatch', 'Platform', 'Pooled',
        'QueryJson', 'RateLimit', 'SafeRe', 'SocksProxy', 'ThreadPool',
        'UpnpPunch', 'WebView', 'argparseCompat', 'compat', 'helper',
    }:
        import importlib
        module = importlib.import_module(f'{__name__}.{name}')
        globals()[name] = module
        return module
    raise AttributeError(name)
