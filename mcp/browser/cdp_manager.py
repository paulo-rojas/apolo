import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import urlopen

from core.config import get_bool, get_int, get_str
from core.process import hidden_subprocess_kwargs
from .executable_resolver import resolve_browser_executable


DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9222"


class BrowserCdpEnsureError(RuntimeError):
    pass


def is_cdp_available(endpoint: str = DEFAULT_CDP_ENDPOINT, timeout: float = 2.0) -> bool:
    try:
        with urlopen(f"{endpoint.rstrip('/')}/json/version", timeout=timeout) as response:
            return response.status == 200
    except (OSError, URLError, ValueError):
        return False


def ensure_cdp(
    endpoint: Optional[str] = None,
    executable: Optional[str] = None,
    profile_directory: Optional[str] = None,
    selected_browser: Optional[str] = None,
    timeout_seconds: Optional[int] = None,
    restore_last_session: Optional[bool] = None,
    close_existing: bool = True,
    runner: Callable[..., Any] = subprocess.run,
    popen: Callable[..., Any] = subprocess.Popen,
) -> Dict[str, Any]:
    endpoint = endpoint or get_str("browser.cdp_endpoint") or DEFAULT_CDP_ENDPOINT
    timeout_seconds = timeout_seconds or get_int("browser.cdp_start_timeout_seconds", 12, minimum=1)
    restore_last_session = (
        get_bool("browser.restore_last_session", True)
        if restore_last_session is None
        else restore_last_session
    )
    selected_browser = selected_browser or get_str("browser.selected", "brave")
    profile_directory = profile_directory or get_str("browser.profile_directory")

    if is_cdp_available(endpoint):
        return {"ok": True, "status": "already_available", "endpoint": endpoint}

    executable = executable or resolve_browser_executable()
    if not executable:
        raise BrowserCdpEnsureError("no browser executable configured")

    if close_existing:
        close_browser_processes(selected_browser, runner=runner)

    start_browser_with_cdp(
        executable=executable,
        endpoint=endpoint,
        profile_directory=profile_directory,
        restore_last_session=restore_last_session,
        popen=popen,
    )

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if is_cdp_available(endpoint, timeout=1.0):
            return {"ok": True, "status": "started", "endpoint": endpoint}
        time.sleep(0.4)

    raise BrowserCdpEnsureError(f"CDP did not become available at {endpoint}")


def close_browser_processes(
    selected_browser: Optional[str],
    grace_seconds: int = 4,
    runner: Callable[..., Any] = subprocess.run,
) -> None:
    process_name = browser_process_name(selected_browser)
    close_script = (
        f"Get-Process {process_name} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.MainWindowHandle -ne 0 } | "
        "ForEach-Object { $_.CloseMainWindow() | Out-Null }"
    )
    _run_hidden(
        runner,
        ["powershell", "-NoProfile", "-Command", close_script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    time.sleep(grace_seconds)
    _run_hidden(
        runner,
        ["taskkill", "/IM", f"{process_name}.exe", "/T", "/F"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def start_browser_with_cdp(
    executable: str,
    endpoint: str,
    profile_directory: Optional[str],
    restore_last_session: bool,
    popen: Callable[..., Any] = subprocess.Popen,
) -> None:
    port = cdp_port(endpoint)
    args = [executable, f"--remote-debugging-port={port}"]
    if profile_directory:
        args.append(f"--profile-directory={profile_directory}")
    if restore_last_session:
        args.append("--restore-last-session")
    _popen_hidden(popen, args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _run_hidden(runner: Callable[..., Any], args: list[str], **kwargs) -> Any:
    if runner is subprocess.run:
        kwargs.update(hidden_subprocess_kwargs())
    return runner(args, **kwargs)


def _popen_hidden(popen: Callable[..., Any], args: list[str], **kwargs) -> Any:
    if popen is subprocess.Popen:
        kwargs.update(hidden_subprocess_kwargs())
    return popen(args, **kwargs)


def cdp_port(endpoint: str) -> int:
    parsed = urlparse(endpoint)
    if not parsed.port:
        raise BrowserCdpEnsureError(f"CDP endpoint needs an explicit port: {endpoint}")
    return parsed.port


def browser_process_name(selected_browser: Optional[str]) -> str:
    name = (selected_browser or "brave").strip().lower()
    if name in {"edge", "msedge"}:
        return "msedge"
    if name in {"chrome", "google-chrome"}:
        return "chrome"
    if name in {"brave", "brave-browser"}:
        return "brave"
    return Path(name).stem


def main() -> None:
    parser = argparse.ArgumentParser(description="Ensure a browser CDP endpoint is available.")
    parser.add_argument("--endpoint", default=get_str("browser.cdp_endpoint") or DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--no-close", action="store_true")
    args = parser.parse_args()
    result = ensure_cdp(endpoint=args.endpoint, close_existing=not args.no_close)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
