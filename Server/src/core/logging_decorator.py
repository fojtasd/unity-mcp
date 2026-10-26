import functools
import inspect
import logging
from typing import Callable, Any

logger = logging.getLogger("mcp-for-unity-server")

# A call's arguments and result are cut to this many characters in the log: a whole script or
# test report on every call filled the rotated log within a few hours.
_MAX_LOGGED_CHARS = 300


# A failed result is kept longer: its error (a reload, a timeout, a ping not answered) is what the
# log is read for.
_MAX_LOGGED_FAILURE_CHARS = 2000


def _short(value: Any) -> str:
    text = str(value)
    failed = "success=False" in text or "'success': False" in text
    limit = _MAX_LOGGED_FAILURE_CHARS if failed else _MAX_LOGGED_CHARS
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… ({len(text)} chars)"


def log_execution(name: str, type_label: str):
    """Decorator to log input arguments and return value of a function."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def _sync_wrapper(*args, **kwargs) -> Any:
            logger.info(
                f"{type_label} '{name}' called with args={_short(args)} kwargs={_short(kwargs)}")
            try:
                result = func(*args, **kwargs)
                logger.info(f"{type_label} '{name}' returned: {_short(result)}")
                return result
            except Exception as e:
                logger.info(f"{type_label} '{name}' failed: {e}")
                raise

        @functools.wraps(func)
        async def _async_wrapper(*args, **kwargs) -> Any:
            logger.info(
                f"{type_label} '{name}' called with args={_short(args)} kwargs={_short(kwargs)}")
            try:
                result = await func(*args, **kwargs)
                logger.info(f"{type_label} '{name}' returned: {_short(result)}")
                return result
            except Exception as e:
                logger.info(f"{type_label} '{name}' failed: {e}")
                raise

        return _async_wrapper if inspect.iscoroutinefunction(func) else _sync_wrapper
    return decorator
