from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Dict

from core.process import hidden_subprocess_kwargs


class SystemVolumeUnavailable(RuntimeError):
    pass


def set_system_volume(level: int | None = None, direction: str | None = None, step: int = 2) -> Dict[str, Any]:
    if level is not None:
        return _set_exact_volume(level)
    if direction in {"up", "down"}:
        return _nudge_volume(direction, step=step)
    raise SystemVolumeUnavailable("volume command requires level or direction")


def _set_exact_volume(level: int) -> Dict[str, Any]:
    value = min(100, max(0, int(level)))
    nircmd = shutil.which("nircmd.exe") or shutil.which("nircmd")
    if nircmd:
        subprocess.run(
            [nircmd, "setsysvolume", str(round(value * 655.35))],
            check=True,
            **hidden_subprocess_kwargs(),
        )
        return {"ok": True, "level": value, "method": "nircmd"}
    raise SystemVolumeUnavailable("exact volume requires nircmd.exe or a future Windows audio backend")


def _nudge_volume(direction: str, step: int = 2) -> Dict[str, Any]:
    if os.name != "nt":
        raise SystemVolumeUnavailable("volume hotkeys are only implemented on Windows")
    virtual_key = "0xAF" if direction == "up" else "0xAE"
    count = max(1, int(step))
    script = (
        "Add-Type -Namespace Native -Name Keyboard -MemberDefinition "
        "'[DllImport(\"user32.dll\")] public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);'; "
        + " ".join(
            f"[Native.Keyboard]::keybd_event({virtual_key},0,0,[UIntPtr]::Zero); "
            f"[Native.Keyboard]::keybd_event({virtual_key},0,2,[UIntPtr]::Zero); "
            "Start-Sleep -Milliseconds 40;"
            for _ in range(count)
        )
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        **hidden_subprocess_kwargs(),
    )
    return {"ok": True, "direction": direction, "step": count, "method": "media_keys"}
