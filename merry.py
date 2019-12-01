import inspect
import logging
from functools import wraps

getargspec = None
if getattr(inspect, 'getfullargspec', None):
    getargspec = inspect.getfullargspec
else:
    # this one is deprecated in Python 3, but available in Python 2
    getargspec = inspect.getargspec


class _Namespace:
    pass


def _wrap_async(fn):
    async def _inner(*args, **kwargs):
        if inspect.iscoroutinefunction(fn):
            return await fn(*args, **kwargs)
        else:
            return fn(*args, **kwargs)
    return _inner


class Merry(object):

    __slots__ = (
        "__logger",
        "__g",
        "__debug",
        "__except",
        "__except_debug",
        "__else",
        "__finally",
        "__as",
    )

    def __init__(self, logger_name='merry', debug=False):
        self.__logger = logging.getLogger(logger_name)
        self.__g = None
        self.__debug = debug
        self.__except = {}
        self.__except_debug = {}
        self.__else = None
        self.__finally = None
        self.__as = {}

    def _try(self, f):
        def except_start(handler, e):
            alias = self.__as[handler]
            if alias is not None:
                setattr(self.__g, alias, e)

        def except_end(handler, e):
            alias = self.__as[handler]
            if alias is not None and hasattr(self.__g, alias):
                delattr(self.__g, alias)

        def get_handler_for(e):
            # find the best handler for this exception
            handler = None
            for c in self.__except.keys():
                if isinstance(e, c):
                    if handler is None or issubclass(c, handler):
                        handler = c
            return handler

        def debug_enabled(handler):
            return self.__debug if self.__except_debug[handler] is None \
                else self.__except_debug[handler]
        
        def assert_error_handling():
            if self.__else is not None and len(self.__except) == 0:
                raise RuntimeError("else clause should come with except clause(s)")

        if inspect.iscoroutinefunction(f):
            @wraps(f)
            async def async_wrapper(*args, **kwargs):
                assert_error_handling()

                self.__g = _Namespace()
                ret = None
                try:
                    ret = await f(*args, **kwargs)

                    # note that if the function returned something, the else clause
                    # will be skipped. This is a similar behavior to a normal
                    # try/except/else block.
                    if ret is not None:
                        return ret
                except Exception as e:
                    handler = get_handler_for(e)
                    # if we don't have any handler, we let the exception bubble up
                    if handler is None:
                        raise e

                    # log exception
                    self.__logger.exception('[merry] Exception caught')

                    # if in debug mode, then bubble up to let a debugger handle
                    if debug_enabled(handler):
                        raise e

                    except_start(handler, e)
                    # invoke handler
                    ret = await _wrap_async(self.__except[handler])(*args, **kwargs)
                    except_end(handler, e)

                    return ret
                else:
                    # if we have an else handler, call it now
                    if self.__else is not None:
                        return await _wrap_async(self.__else)(*args, **kwargs)
                finally:
                    alt_ret = None
                    # if we have a finally handler, call it now
                    if self.__finally is not None:
                        alt_ret = await _wrap_async(self.__finally)(*args, **kwargs)

                    self.__g = None

                    if alt_ret is not None:
                        ret = alt_ret
                        return ret

            return async_wrapper
        else:
            @wraps(f)
            def wrapper(*args, **kwargs):
                assert_error_handling()

                self.__g = _Namespace()
                ret = None
                try:
                    ret = f(*args, **kwargs)

                    # note that if the function returned something, the else clause
                    # will be skipped. This is a similar behavior to a normal
                    # try/except/else block.
                    if ret is not None:
                        return ret
                except Exception as e:
                    handler = get_handler_for(e)
                    # if we don't have any handler, we let the exception bubble up
                    if handler is None:
                        raise e

                    # log exception
                    self.__logger.exception('[merry] Exception caught')

                    # if in debug mode, then bubble up to let a debugger handle
                    if debug_enabled(handler):
                        raise e

                    except_start(handler, e)
                    # invoke handler
                    ret = self.__except[handler](*args, **kwargs)
                    except_end(handler, e)

                    return ret
                else:
                    # if we have an else handler, call it now
                    if self.__else is not None:
                        return self.__else(*args, **kwargs)
                finally:
                    alt_ret = None
                    # if we have a finally handler, call it now
                    if self.__finally is not None:
                        alt_ret = self.__finally(*args, **kwargs)

                    self.__g = None

                    if alt_ret is not None:
                        ret = alt_ret
                        return ret
            return wrapper

    def _except(self, *args, debug=None, _as=None):
        if len(args) == 1 and not inspect.isclass(args[0]):  # @m._except as deco
            self.__except[BaseException] = args[0]
            self.__except_debug[BaseException] = None
            self.__as[BaseException] = None
            return args[0]

        def decorator(f):
            for e in args:
                self.__except[e] = f
                self.__except_debug[e] = debug
                self.__as[e] = _as
            return f
        return decorator

    def _else(self, f):
        self.__else = f
        return f

    def _finally(self, f):
        self.__finally = f
        return f

    # namespace accessors

    def __getattr__(self, key):
        if self.__g is not None:
            return getattr(self.__g, key)
        raise RuntimeError(
            "context is only accessible within error handling clauses")

    def __setattr__(self, key, value):
        if key[:6] == "_Merry" and key[6:] in self.__slots__:
            return super().__setattr__(key, value)
        elif self.__g is not None:
            return setattr(self.__g, key, value)
        else:
            raise RuntimeError(
                "context is only accessible within error handling clauses")

    def __delattr__(self, key):
        if key[:6] != "_Merry" or key[6:] not in self.__slots__:
            if self.__g is not None:
                delattr(self.__g, key)
            else:
                raise RuntimeError(
                    "context is only accessible within error handling clauses")
