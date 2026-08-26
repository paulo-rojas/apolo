from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict
from urllib.parse import quote_plus

from core.memory_files import memory_dir
from voice.normalize import normalize_text


UrlLauncher = Callable[[str], None]


COMMON_TLDS = (".com", ".org", ".net", ".io", ".dev", ".ai", ".app", ".edu", ".gov")


def open_web_target(target: str, launcher: UrlLauncher | None = None) -> Dict[str, Any]:
    normalized = normalize_text(target)
    if not normalized:
        raise ValueError("web target is empty")
    registry = _registry()
    entry = registry.setdefault("aliases", {}).get(normalized)
    source = "memory"
    if not entry:
        url = infer_url(target)
        entry = {
            "label": target.strip(),
            "url": url,
            "source": "inferred",
            "aliases": sorted({normalized}),
            "timesOpened": 0,
            "createdAt": _now(),
        }
        source = "inferred"
    _open_url(entry["url"], launcher=launcher)
    entry["timesOpened"] = int(entry.get("timesOpened", 0)) + 1
    entry["updatedAt"] = _now()
    for alias in set(entry.get("aliases", [])) | {normalized, normalize_text(entry.get("label", target))}:
        registry.setdefault("aliases", {})[alias] = entry
    _write_registry(registry)
    return {"ok": True, "url": entry["url"], "alias": normalized, "source": source}


def search_google(query: str, launcher: UrlLauncher | None = None) -> Dict[str, Any]:
    query = " ".join(str(query or "").split())
    if not query:
        raise ValueError("search query is empty")
    url = f"https://www.google.com/search?q={quote_plus(query)}"
    _open_url(url, launcher=launcher)
    return {"ok": True, "url": url, "query": query}


def remember_web_shortcut(alias: str, url: str, label: str | None = None) -> Dict[str, Any]:
    normalized = normalize_text(alias)
    if not normalized:
        raise ValueError("alias is required")
    final_url = normalize_url(url)
    registry = _registry()
    entry = {
        "label": label or alias,
        "url": final_url,
        "source": "manual",
        "aliases": sorted({normalized, normalize_text(label or alias)}),
        "timesOpened": 0,
        "createdAt": _now(),
        "updatedAt": _now(),
    }
    for item in entry["aliases"]:
        registry.setdefault("aliases", {})[item] = entry
    _write_registry(registry)
    return {"ok": True, "alias": normalized, "url": final_url}


def infer_url(target: str) -> str:
    cleaned = str(target or "").strip()
    lowered = cleaned.lower()
    if lowered.startswith(("http://", "https://")):
        return cleaned
    compact = normalize_text(cleaned).replace(" ", "")
    if "." in compact:
        return normalize_url(compact)
    return f"https://{compact}.com"


def normalize_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        raise ValueError("url is empty")
    if value.lower().startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def known_web_alias(name: str) -> bool:
    return normalize_text(name) in _registry().get("aliases", {})


def _open_url(url: str, launcher: UrlLauncher | None = None) -> None:
    if launcher:
        launcher(url)
        return
    os.startfile(url)  # type: ignore[attr-defined]


def _registry_path() -> Path:
    return memory_dir() / "web_shortcuts.json"


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


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
