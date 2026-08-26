from __future__ import annotations

import os
import subprocess
import sys

from core.process import hidden_subprocess_kwargs


_PROCESS_PATTERN = r"(?i)C:\\apolo\\\.venv\\Scripts\\pythonw?\.exe.*(?:-m\s+(?:ui\.app|voice\.local_listener)|uvicorn\s+mcp\.server:app)"
_PYTHON_GLOB = r"*C:\apolo\.venv\Scripts\python*.exe*"
_SERVICE_GLOBS = (
    "*-m ui.app*",
    "*-m voice.local_listener*",
    "*uvicorn mcp.server:app*",
)


def cleanup_apolo_processes() -> None:
    """Stop stale Apolo UI, listener, and backend processes on Windows."""
    if sys.platform != "win32":
        return
    command = _cleanup_command(os.getpid(), os.getppid())
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **hidden_subprocess_kwargs(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    for line in result.stdout.splitlines():
        if line.strip().isdigit():
            subprocess.run(
                ["taskkill", "/PID", line.strip(), "/T", "/F"],
                capture_output=True,
                timeout=5,
                check=False,
                **hidden_subprocess_kwargs(),
            )


def _cleanup_command(pid: int, ppid: int) -> str:
    protected = f"@({pid},{ppid})"
    service_filter = " -or ".join(f"$_.CommandLine -like '{item}'" for item in _SERVICE_GLOBS)
    return (
        "$protected = " + protected + "; "
        "$ids = Get-CimInstance Win32_Process | "
        "Where-Object { $protected -notcontains $_.ProcessId -and "
        "$null -ne $_.CommandLine -and "
        f"$_.CommandLine -like '{_PYTHON_GLOB}' -and "
        f"({service_filter}) }} | "
        "Select-Object -ExpandProperty ProcessId; "
        "$ids"
    )
