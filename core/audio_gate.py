from __future__ import annotations

import time
from pathlib import Path
from tempfile import gettempdir


_GATE_PATH = Path(gettempdir()) / "apolo_listener_mute_until.txt"
_COMPUTER_AUDIO_PATH = Path(gettempdir()) / "apolo_computer_audio_until.txt"


def mute_listener_for(seconds: float) -> None:
    until = time.time() + max(0.0, float(seconds))
    _GATE_PATH.write_text(str(until), encoding="utf-8")


def clear_listener_mute() -> None:
    _GATE_PATH.unlink(missing_ok=True)


def listener_is_muted() -> bool:
    try:
        until = float(_GATE_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if time.time() < until:
        return True
    clear_listener_mute()
    return False


def mark_computer_audio_for(seconds: float) -> None:
    until = time.time() + max(0.0, float(seconds))
    _COMPUTER_AUDIO_PATH.write_text(str(until), encoding="utf-8")


def clear_computer_audio() -> None:
    _COMPUTER_AUDIO_PATH.unlink(missing_ok=True)


def computer_audio_guard_active() -> bool:
    try:
        until = float(_COMPUTER_AUDIO_PATH.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    if time.time() < until:
        return True
    clear_computer_audio()
    return False
