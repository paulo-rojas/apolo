from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable

from core.memory_files import memory_dir
from core.process import hidden_subprocess_kwargs
from voice.normalize import normalize_text


Launcher = Callable[[Dict[str, Any]], None]


class SystemAppNotFound(RuntimeError):
    pass


def known_app_alias(name: str) -> bool:
    aliases = _registry().get("aliases", {})
    return normalize_text(name) in aliases


def open_system_app(name: str, launcher: Launcher | None = None) -> Dict[str, Any]:
    query = _clean_app_name(name)
    if not query:
        raise SystemAppNotFound("app name is empty")
    normalized = normalize_text(query)
    registry = _registry()
    aliases = registry.setdefault("aliases", {})

    entry = aliases.get(normalized)
    source = "memory"
    if not entry:
        match = best_app_match(query, discover_system_apps())
        if not match:
            raise SystemAppNotFound(f"No encontré una aplicación llamada {query}")
        entry = {
            "label": match["label"],
            "launch": match["launch"],
            "source": match["source"],
            "aliases": sorted({normalized, normalize_text(match["label"])}),
            "timesOpened": 0,
            "createdAt": _now(),
        }
        source = match["source"]

    _launch(entry["launch"], launcher=launcher)
    entry["timesOpened"] = int(entry.get("timesOpened", 0)) + 1
    entry["updatedAt"] = _now()
    for alias in set(entry.get("aliases", [])) | {normalized, normalize_text(entry.get("label", query))}:
        aliases[alias] = entry
    _write_registry(registry)
    return {"ok": True, "app": entry["label"], "alias": normalized, "source": source}


def close_system_app(name: str, runner: Callable[..., Any] = subprocess.run) -> Dict[str, Any]:
    query = _clean_app_name(name)
    if not query:
        raise SystemAppNotFound("app name is empty")
    normalized = normalize_text(query)
    registry = _registry()
    entry = registry.setdefault("aliases", {}).get(normalized)
    needles = _close_needles(query, entry)
    result = _close_processes(needles, runner=runner)
    if result["closed"] <= 0:
        raise SystemAppNotFound(f"No encontré una aplicación abierta llamada {query}")
    if entry:
        entry["timesClosed"] = int(entry.get("timesClosed", 0)) + result["closed"]
        entry["updatedAt"] = _now()
        for alias in set(entry.get("aliases", [])) | {normalized, normalize_text(entry.get("label", query))}:
            registry.setdefault("aliases", {})[alias] = entry
        _write_registry(registry)
    return {"ok": True, "app": entry.get("label", query) if entry else query, **result}


def remember_system_app(alias: str, launch: Dict[str, Any], label: str | None = None) -> Dict[str, Any]:
    normalized = normalize_text(alias)
    if not normalized:
        raise ValueError("alias is required")
    if not isinstance(launch, dict) or not launch.get("type") or not launch.get("value"):
        raise ValueError("launch must include type and value")
    registry = _registry()
    entry = {
        "label": label or alias,
        "launch": {"type": str(launch["type"]), "value": str(launch["value"])},
        "source": "manual",
        "aliases": sorted({normalized, normalize_text(label or alias)}),
        "timesOpened": 0,
        "createdAt": _now(),
        "updatedAt": _now(),
        "timesClosed": 0,
    }
    for item in entry["aliases"]:
        registry.setdefault("aliases", {})[item] = entry
    _write_registry(registry)
    return {"ok": True, "alias": normalized, "app": entry["label"]}


def discover_system_apps() -> list[Dict[str, Any]]:
    apps: list[Dict[str, Any]] = []
    for directory in _start_menu_dirs():
        if not directory.exists():
            continue
        for shortcut in directory.rglob("*"):
            if shortcut.suffix.lower() not in {".lnk", ".url", ".appref-ms"}:
                continue
            apps.append(
                {
                    "label": shortcut.stem,
                    "normalized": normalize_text(shortcut.stem),
                    "source": "start_menu",
                    "launch": {"type": "path", "value": str(shortcut)},
                }
            )
    seen = {item["normalized"] for item in apps}
    for path_dir in _path_dirs():
        if not path_dir.exists():
            continue
        for executable in path_dir.glob("*.exe"):
            normalized = normalize_text(executable.stem)
            if normalized in seen:
                continue
            seen.add(normalized)
            apps.append(
                {
                    "label": executable.stem,
                    "normalized": normalized,
                    "source": "path",
                    "launch": {"type": "path", "value": str(executable)},
                }
            )
    return apps


def best_app_match(query: str, apps: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    normalized = normalize_text(query)
    if not normalized:
        return None
    best: tuple[float, Dict[str, Any]] | None = None
    for app in apps:
        candidate = app.get("normalized") or normalize_text(app.get("label", ""))
        score = _match_score(normalized, candidate)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, app)
    return best[1] if best and best[0] >= 0.55 else None


def _match_score(query: str, candidate: str) -> float:
    if query == candidate:
        return 1.0
    if query in candidate or candidate in query:
        return min(len(query), len(candidate)) / max(len(query), len(candidate))
    query_tokens = set(query.split())
    candidate_tokens = set(candidate.split())
    if not query_tokens or not candidate_tokens:
        return 0.0
    return len(query_tokens & candidate_tokens) / len(query_tokens | candidate_tokens)


def _clean_app_name(name: str) -> str:
    cleaned = normalize_text(name)
    cleaned = " ".join(
        token for token in cleaned.split() if token not in {"aplicacion", "app", "programa"}
    )
    return cleaned.strip()


def _launch(launch: Dict[str, Any], launcher: Launcher | None = None) -> None:
    if launcher:
        launcher(launch)
        return
    kind = str(launch.get("type", "path"))
    value = str(launch.get("value", ""))
    if not value:
        raise ValueError("launch value is empty")
    if kind == "path":
        os.startfile(value)  # type: ignore[attr-defined]
        return
    if kind == "command":
        subprocess.Popen([value], **hidden_subprocess_kwargs())
        return
    raise ValueError(f"unsupported launch type: {kind}")


def _close_needles(query: str, entry: Dict[str, Any] | None) -> list[str]:
    values = {normalize_text(query)}
    if entry:
        values.add(normalize_text(entry.get("label", "")))
        values.update(normalize_text(alias) for alias in entry.get("aliases", []))
        launch_value = str(entry.get("launch", {}).get("value", ""))
        if launch_value:
            values.add(normalize_text(Path(launch_value).stem))
    return sorted(value for value in values if value)


def _close_processes(needles: list[str], runner: Callable[..., Any] = subprocess.run) -> Dict[str, Any]:
    if os.name != "nt":
        raise RuntimeError("closing system apps is only implemented on Windows")
    payload = json.dumps(needles)
    browser_names = json.dumps(["brave", "chrome", "msedge", "firefox", "opera", "vivaldi"])
    script = (
        "$needles = ConvertFrom-Json @'\n"
        + payload
        + "\n'@; "
        "$browserNames = ConvertFrom-Json @'\n"
        + browser_names
        + "\n'@; "
        "function Norm($value) { "
        "  if ($null -eq $value) { return '' }; "
        "  return (($value.ToString()).ToLowerInvariant() -replace '[^a-z0-9]+',' ').Trim() "
        "}; "
        "$closed = @(); "
        "Get-Process | Where-Object { $_.MainWindowHandle -ne 0 } | ForEach-Object { "
        "  $p = $_; $name = Norm $p.ProcessName; $title = Norm $p.MainWindowTitle; "
        "  foreach ($needle in $needles) { "
        "    $n = Norm $needle; "
        "    $nameMatch = $n -and ($name -eq $n -or $name.Contains($n) -or ($name.Length -ge 4 -and $n.Contains($name))); "
        "    $titleMatch = $n -and -not ($browserNames -contains $name) -and $title -and ($title -eq $n -or $title.Contains($n)); "
        "    if ($nameMatch -or $titleMatch) { "
        "      if ($p.CloseMainWindow()) { $closed += [pscustomobject]@{ id=$p.Id; name=$p.ProcessName; title=$p.MainWindowTitle } }; "
        "      break "
        "    } "
        "  } "
        "}; "
        "$closed | ConvertTo-Json -Compress"
    )
    completed = runner(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=8,
        check=False,
        **hidden_subprocess_kwargs(),
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    stdout = completed.stdout.strip()
    if not stdout:
        return {"closed": 0, "processes": []}
    data = json.loads(stdout)
    processes = data if isinstance(data, list) else [data]
    return {"closed": len(processes), "processes": processes}


def _registry_path() -> Path:
    return memory_dir() / "system_apps.json"


def _registry() -> Dict[str, Any]:
    path = _registry_path()
    if not path.exists():
        _write_registry({"aliases": {}})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"aliases": {}}
    return data if isinstance(data, dict) else {"aliases": {}}


def _write_registry(data: Dict[str, Any]) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _start_menu_dirs() -> list[Path]:
    return [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]


def _path_dirs() -> list[Path]:
    return [Path(item) for item in os.environ.get("PATH", "").split(os.pathsep) if item]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
