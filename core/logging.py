from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import get_str


_LOCK = threading.Lock()


def log_dir() -> Path:
    configured = get_str("logs.dir", None)
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[1] / "logs"


def log_text_path() -> Path:
    return log_dir() / "apolo.log"


def log_json_path() -> Path:
    return log_dir() / "apolo.ndjson"


def write_log(source: str, message: str, **fields: Any) -> None:
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")
    clean_source = str(source or "SYSTEM").strip() or "SYSTEM"
    clean_message = str(message or "").replace("\r", "\\r").replace("\n", "\\n")
    entry = {"ts": timestamp, "source": clean_source, "message": clean_message, **fields}
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        with log_text_path().open("a", encoding="utf-8") as log_file:
            log_file.write(f"{timestamp} {clean_source:<12} {clean_message}\n")
        with log_json_path().open("a", encoding="utf-8") as json_file:
            json_file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_recent_lines(limit: int = 200) -> list[str]:
    path = log_text_path()
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max(1, limit) :]
