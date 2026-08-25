import json

import pytest

from mcp.browser.executable_resolver import BrowserExecutableError, resolve_browser_executable


def test_resolves_explicit_browser_executable(monkeypatch, tmp_path):
    executable = tmp_path / "browser.exe"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("APOLO_BROWSER_EXECUTABLE", str(executable))

    assert resolve_browser_executable() == str(executable)


def test_resolves_configured_browser_by_name(monkeypatch, tmp_path):
    executable = tmp_path / "chrome.exe"
    executable.write_text("", encoding="utf-8")
    config = tmp_path / "browsers.json"
    config.write_text(
        json.dumps({"default": "chrome", "browsers": {"chrome": str(executable)}}),
        encoding="utf-8",
    )
    monkeypatch.delenv("APOLO_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setenv("APOLO_BROWSER_EXECUTABLES_FILE", str(config))

    assert resolve_browser_executable() == str(executable)


def test_resolves_browser_from_apolo_config(monkeypatch, tmp_path):
    executable = tmp_path / "edge.exe"
    executable.write_text("", encoding="utf-8")
    config = tmp_path / "apolo.json"
    config.write_text(
        json.dumps(
            {
                "browser": {
                    "selected": "edge",
                    "executables": {"edge": str(executable)},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("APOLO_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.delenv("APOLO_BROWSER_EXECUTABLES_FILE", raising=False)
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    assert resolve_browser_executable() == str(executable)


def test_strict_mode_requires_configured_browser(monkeypatch, tmp_path):
    missing_config = tmp_path / "missing.json"
    monkeypatch.delenv("APOLO_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setenv("APOLO_BROWSER_EXECUTABLES_FILE", str(missing_config))
    monkeypatch.setenv("APOLO_BROWSER_REQUIRE_CONFIGURED", "true")

    with pytest.raises(BrowserExecutableError):
        resolve_browser_executable()
