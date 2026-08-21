import sys
import logging
import signal
import importlib

import gevent
import gevent.hub

from Config import config
from . import Debug

last_error = None

def shutdown(reason="Unknown"):
    logging.info("Shutting down (reason: %s)..." % reason)
    import main
    if "file_server" in dir(main):
        try:
            gevent.spawn(main.file_server.stop)
            if "ui_server" in dir(main):
                gevent.spawn(main.ui_server.stop)
        except Exception as err:
            print("Proper shutdown error: %s" % err)
            sys.exit(0)
    else:
        sys.exit(0)

# Store last error, ignore notify, allow manual error logging
def handleError(*args, **kwargs):
    global last_error
    if not args:  # Manual called
        args = sys.exc_info()
        silent = True
    else:
        silent = False
    if args[0].__name__ != "Notify":
        last_error = args

    if args[0].__name__ == "KeyboardInterrupt":
        shutdown("Keyboard interrupt")
    elif not silent and args[0].__name__ != "Notify":
        logging.exception("Unhandled exception")
        if "greenlet.py" not in args[2].tb_frame.f_code.co_filename:  # Don't display error twice
            sys.__excepthook__(*args, **kwargs)


# Ignore notify errors
def handleErrorNotify(*args, **kwargs):
    err = args[0]
    if err.__name__ == "KeyboardInterrupt":
        shutdown("Keyboard interrupt")
    elif err.__name__ != "Notify":
        logging.error("Unhandled exception: %s" % Debug.formatException(args))
        sys.__excepthook__(*args, **kwargs)


if config.debug:  # Keep last error for /Debug
    sys.excepthook = handleError
else:
    sys.excepthook = handleErrorNotify


# Override default error handler to allow silent killing / custom logging
if "handle_error" in dir(gevent.hub.Hub):
    gevent.hub.Hub._original_handle_error = gevent.hub.Hub.handle_error
else:
    logging.debug("gevent.hub.Hub.handle_error not found using old gevent hooks")
    OriginalGreenlet = gevent.Greenlet
    class ErrorhookedGreenlet(OriginalGreenlet):
        def _report_error(self, exc_info):
            sys.excepthook(exc_info[0], exc_info[1], exc_info[2])

    gevent.Greenlet = gevent.greenlet.Greenlet = ErrorhookedGreenlet
    importlib.reload(gevent)

def _isThreadpoolError(context, tb):
    # Exceptions raised in gevent's thread pool workers are re-raised in the
    # main thread via ThreadResult.get(), so they should not be reported here.
    # The worker class name differs across gevent versions (ThreadPool in older
    # versions, _WorkerGreenlet in newer ones), so also match on the traceback.
    if context is not None and context.__class__ is tuple:
        name = getattr(context[0].__class__, "__name__", "")
        if name in ("ThreadPool", "_WorkerGreenlet", "ThreadPoolWorker"):
            return True
    while tb is not None:
        frame = tb.tb_frame
        code = frame.f_code
        if code.co_filename.endswith("threadpool.py") and code.co_name in ("__run_task", "_run_task"):
            return True
        tb = tb.tb_next
    return False


def handleGreenletError(context, type, value, tb):
    if _isThreadpoolError(context, tb):
        # Exceptions in ThreadPool will be handled in the main Thread
        return None

    if isinstance(value, str):
        # Cython can raise errors where the value is a plain string
        # e.g., AttributeError, "_semaphore.Semaphore has no attr", <traceback>
        value = type(value)

    if not issubclass(type, gevent.get_hub().NOT_ERROR):
        sys.excepthook(type, value, tb)

gevent.get_hub().handle_error = handleGreenletError

try:
    signal.signal(signal.SIGTERM, lambda signum, stack_frame: shutdown("SIGTERM"))
except Exception as err:
    logging.debug("Error setting up SIGTERM watcher: %s" % err)


if __name__ == "__main__":
    import time
    from gevent import monkey
    monkey.patch_all(thread=False, ssl=False)
    from . import Debug

    def sleeper(num):
        print("started", num)
        time.sleep(3)
        raise Exception("Error")
        print("stopped", num)
    thread1 = gevent.spawn(sleeper, 1)
    thread2 = gevent.spawn(sleeper, 2)
    time.sleep(1)
    print("killing...")
    thread1.kill(exception=Debug.Notify("Worker stopped"))
    #thread2.throw(Debug.Notify("Throw"))
    print("killed")
    gevent.joinall([thread1,thread2])
