import pytest
from concurrent.futures import ThreadPoolExecutor


playwright = pytest.importorskip("playwright", reason="playwright not installed; skipping browser tests")


from mcp.browser.playwright_driver import PlaywrightBrowser


def test_open_and_get_state(monkeypatch, tmp_path):
    config = tmp_path / "apolo.json"
    config.write_text(
        """
        {
          "browser": {
            "profile": "%s",
            "profile_directory": null,
            "headless": true
          }
        }
        """
        % str(tmp_path / "profile").replace("\\", "\\\\"),
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    def run_browser_check():
        b = PlaywrightBrowser(headless=True)
        try:
            res = b.open("https://example.com")
            state = b.get_state()
            return res, state
        finally:
            b.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_browser_check)
        try:
            res, state = future.result()
        except Exception as e:
            if "Playwright Sync API inside the asyncio loop" in str(e):
                pytest.skip("Playwright sync API cannot run inside this pytest loop context")
            raise

    assert "example" in res["url"]
    assert state["url"].startswith("http")
