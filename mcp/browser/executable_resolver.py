import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import DEFAULT_CONFIG_PATH, get_bool, get_config, get_str


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EXECUTABLE_CONFIG_PATH = PROJECT_ROOT / "config" / "browser_executables.json"


class BrowserExecutableError(RuntimeError):
    pass


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_config(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise BrowserExecutableError("browser executable config must be a JSON object")
    return data


def _normalize_mapping(config: Dict[str, Any]) -> Dict[str, str]:
    browsers = config.get("browsers", config)
    if not isinstance(browsers, dict):
        raise BrowserExecutableError("browser executable config 'browsers' must be an object")
    return {str(name): str(path) for name, path in browsers.items() if isinstance(path, str)}


def resolve_browser_executable() -> Optional[str]:
    """Resolve a user-approved browser executable.

    Priority:
    1. APOLO_BROWSER_EXECUTABLE: explicit executable path.
    2. config/browser_executables.json selected by APOLO_BROWSER_NAME or "default".
    3. None, allowing Playwright's bundled browser, unless strict mode is enabled.
    """
    explicit_path = get_str("browser.executable", env="APOLO_BROWSER_EXECUTABLE")
    if explicit_path:
        return _validate_executable(explicit_path)

    legacy_config_override = os.getenv("APOLO_BROWSER_EXECUTABLES_FILE")
    configured_mapping = get_config("browser.executables", {})
    if configured_mapping and not legacy_config_override:
        config = {
            "default": get_str("browser.selected", env="APOLO_BROWSER_NAME"),
            "browsers": configured_mapping,
        }
    else:
        config_path = Path(
            legacy_config_override or str(DEFAULT_EXECUTABLE_CONFIG_PATH)
        )
        config = _load_config(config_path)

    if config:
        mapping = _normalize_mapping(config)
        if legacy_config_override:
            selected = os.getenv("APOLO_BROWSER_NAME") or str(config.get("default", ""))
        else:
            selected = get_str("browser.selected", env="APOLO_BROWSER_NAME") or str(
                config.get("default", "")
            )
        if not selected and len(mapping) == 1:
            selected = next(iter(mapping))
        if not selected:
            raise BrowserExecutableError("APOLO_BROWSER_NAME or config 'default' is required")
        if selected not in mapping:
            raise BrowserExecutableError(f"browser '{selected}' is not configured")
        return _validate_executable(mapping[selected])

    if get_bool("browser.require_configured", False, env="APOLO_BROWSER_REQUIRE_CONFIGURED"):
        raise BrowserExecutableError("no configured browser executable found")
    return None


def _validate_executable(path: str) -> str:
    resolved = Path(os.path.expandvars(path)).expanduser()
    if not resolved.is_file():
        raise BrowserExecutableError(f"browser executable not found: {resolved}")
    return str(resolved)
