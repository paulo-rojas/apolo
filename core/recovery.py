import time
from enum import Enum
from typing import Callable, Any, Optional

from core.config import get_int


class ErrorCategory(str, Enum):
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"
    MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
    PAGE_CHANGED = "PAGE_CHANGED"
    NAVIGATION_TIMEOUT = "NAVIGATION_TIMEOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    ACTION_NO_EFFECT = "ACTION_NO_EFFECT"
    POPUP_BLOCKING = "POPUP_BLOCKING"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    UNKNOWN = "UNKNOWN"


def classify_exception(exc: Exception) -> ErrorCategory:
    msg = str(exc).lower()
    if "timeout" in msg:
        return ErrorCategory.NAVIGATION_TIMEOUT
    if "not found" in msg or "no node found" in msg or "node is detached" in msg:
        return ErrorCategory.ELEMENT_NOT_FOUND
    if "multiple" in msg or "ambiguous" in msg:
        return ErrorCategory.MULTIPLE_MATCHES
    if "popup" in msg or "dialog" in msg:
        return ErrorCategory.POPUP_BLOCKING
    return ErrorCategory.UNKNOWN


def _env_int(name: str, default: int) -> int:
    return get_int("browser.retries", default, env=name, minimum=1)


def retry_action(max_retries: Optional[int] = 3, backoff: float = 0.5):
    def decorator(fn: Callable[..., Any]):
        def wrapper(*args, **kwargs):
            last_exc = None
            retries = max_retries or _env_int("APOLO_BROWSER_RETRIES", 3)
            for attempt in range(1, retries + 1):
                try:
                    return fn(*args, **kwargs)
                except Exception as e:
                    last_exc = e
                    time.sleep(backoff * attempt)
            raise last_exc

        return wrapper

    return decorator
