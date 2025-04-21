"""Collection of decorators that mark functions as deprecated or unwanted

The particular conditions depends on decorator and whether it throws
an exception or gives a warning depends on config.
"""

from functools import wraps

from Config import config

def wip(f):
    """Decorator that marks function as being WIP and disables in production"""
    @wraps(f)
    def inner(*args, **kwargs):
        if not config.wip:
            raise NotImplementedError(f"Calling WIP function {f.__name__} in production mode")
        return f(*args, **kwargs)
    return inner
