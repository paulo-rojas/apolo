import pytest


playwright = pytest.importorskip("playwright", reason="playwright not installed; skipping browser tests")


from mcp.browser.playwright_driver import PlaywrightBrowser


def test_open_and_get_state():
    b = PlaywrightBrowser(headless=True)
    # Try to open a simple site
    res = b.open("https://example.com")
    state = b.get_state()
    assert "example" in res["url"]
    assert state["url"].startswith("http")
