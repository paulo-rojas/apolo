from mcp.browser.playwright_driver import PlaywrightBrowser
from mcp.browser.cdp_manager import ensure_cdp


def test_browser_profile_directory_from_config(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text(
        """
        {
          "browser": {
            "profile": "C:\\\\Users\\\\paulo\\\\BraveUserData",
            "profile_directory": "Default",
            "cdp_endpoint": "http://127.0.0.1:9222",
            "headless": false
          }
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    browser = PlaywrightBrowser()

    assert browser.user_data_dir == "C:\\Users\\paulo\\BraveUserData"
    assert browser.profile_directory == "Default"
    assert browser.cdp_endpoint == "http://127.0.0.1:9222"
    assert browser.headless is False


def test_ensure_cdp_uses_profile_directory_without_user_data_dir(monkeypatch):
    launched = []

    class FakeProcess:
        pid = 1234

    def fake_popen(args, **kwargs):
        launched.append(args)
        return FakeProcess()

    checks = iter([False, True])
    monkeypatch.setattr("mcp.browser.cdp_manager.is_cdp_available", lambda *args, **kwargs: next(checks))
    monkeypatch.setattr("mcp.browser.cdp_manager.resolve_browser_executable", lambda: "brave.exe")

    result = ensure_cdp(
        endpoint="http://127.0.0.1:9222",
        profile_directory="Default",
        restore_last_session=False,
        close_existing=False,
        timeout_seconds=1,
        popen=fake_popen,
    )

    assert result == {
        "ok": True,
        "status": "started",
        "endpoint": "http://127.0.0.1:9222",
        "pid": 1234,
    }
    assert "--profile-directory=Default" in launched[0]
    assert all(not arg.startswith("--user-data-dir=") for arg in launched[0])
