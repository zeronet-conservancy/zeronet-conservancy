import sys

if sys.version_info.major == 3 and sys.version_info.minor < 9:
    def removeprefix(s, prefix, /):
        if s.startswith(prefix):
            return s[len(prefix):]
        return s
    def removesuffix(s, suffix, /):
        if s.endswith(suffix):
            return s[:-len(suffix)]
        return s
else:
    def removeprefix(s, prefix, /):
        return s.removeprefix(prefix)
    def removesuffix(s, suffix, /):
        return s.removesuffix(suffix)

import argparse

if not hasattr(argparse, 'BooleanOptionalAction'):
    from .argparseCompat import BooleanOptionalAction
    argparse.BooleanOptionalAction = BooleanOptionalAction
