from mcp.browser.playwright_driver import PlaywrightBrowser


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
