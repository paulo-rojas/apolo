from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir


_REST_PATH = Path(gettempdir()) / "apolo_listener_resting.flag"
_SHUTDOWN_PATH = Path(gettempdir()) / "apolo_listener_shutdown.flag"


def rest_listener() -> None:
    _REST_PATH.write_text("resting", encoding="utf-8")


def resume_listener() -> None:
    _REST_PATH.unlink(missing_ok=True)
    _SHUTDOWN_PATH.unlink(missing_ok=True)


def listener_is_resting() -> bool:
    return _REST_PATH.exists()


def request_shutdown() -> None:
    _SHUTDOWN_PATH.write_text("shutdown", encoding="utf-8")


def clear_shutdown() -> None:
    _SHUTDOWN_PATH.unlink(missing_ok=True)


def shutdown_requested() -> bool:
    return _SHUTDOWN_PATH.exists()
