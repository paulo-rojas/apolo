import json
import os
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "apolo.json"
DEFAULT_CORE_HOST = "127.0.0.1"
DEFAULT_CORE_PORT = 8000


def load_config() -> Dict[str, Any]:
    path = Path(os.getenv("APOLO_CONFIG_FILE", str(DEFAULT_CONFIG_PATH)))
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Apolo config must be a JSON object")
    return data


def get_config(path: str, default: Any = None) -> Any:
    current: Any = load_config()
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def save_config(data: Dict[str, Any]) -> None:
    path = Path(os.getenv("APOLO_CONFIG_FILE", str(DEFAULT_CONFIG_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def set_config(path: str, value: Any) -> None:
    data = load_config()
    current = data
    parts = path.split(".")
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value
    save_config(data)


def get_str(path: str, default: Optional[str] = None, env: Optional[str] = None) -> Optional[str]:
    if env and os.getenv(env) is not None:
        return os.getenv(env)
    value = get_config(path, default)
    return str(value) if value is not None else None


def get_int(path: str, default: int, env: Optional[str] = None, minimum: Optional[int] = None) -> int:
    raw = os.getenv(env) if env and os.getenv(env) is not None else get_config(path, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value) if minimum is not None else value


def get_float(path: str, default: float, env: Optional[str] = None, minimum: Optional[float] = None) -> float:
    raw = os.getenv(env) if env and os.getenv(env) is not None else get_config(path, default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, value) if minimum is not None else value


def get_bool(path: str, default: bool, env: Optional[str] = None) -> bool:
    raw = os.getenv(env) if env and os.getenv(env) is not None else get_config(path, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def core_host() -> str:
    return get_str("core.host", DEFAULT_CORE_HOST, env="APOLO_CORE_HOST") or DEFAULT_CORE_HOST


def core_port() -> int:
    return get_int("core.port", DEFAULT_CORE_PORT, env="APOLO_CORE_PORT", minimum=1)


def core_url() -> str:
    configured = get_str("core.url", None, env="APOLO_CORE_URL")
    if configured:
        return configured.rstrip("/")
    return f"http://{core_host()}:{core_port()}"


def core_ws_url(path: str = "/ws/runtime") -> str:
    parsed = urlparse(core_url())
    scheme = "wss" if parsed.scheme == "https" else "ws"
    base_path = parsed.path.rstrip("/")
    endpoint = "/" + path.lstrip("/")
    return parsed._replace(scheme=scheme, path=f"{base_path}{endpoint}", params="", query="", fragment="").geturl()
