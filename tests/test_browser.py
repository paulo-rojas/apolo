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


def test_dom_layer_can_inspect_type_and_click(monkeypatch, tmp_path):
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
        % str(tmp_path / "profile-dom").replace("\\", "\\\\"),
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    def run_browser_check():
        b = PlaywrightBrowser(headless=True)
        try:
            b.open("data:text/html,<input placeholder='Buscar'><button onclick=\"document.body.dataset.clicked='yes'\">Enviar</button>")
            snapshot = b.dom_snapshot()
            typed = b.dom_type("hola", target="Buscar")
            clicked = b.dom_click(target="Enviar")
            smart = b.smart_click(target="Enviar")
            clicked_value = b._page.evaluate("document.body.dataset.clicked")
            return snapshot, typed, clicked, smart, clicked_value
        finally:
            b.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        snapshot, typed, clicked, smart, clicked_value = executor.submit(run_browser_check).result()

    assert any(item["placeholder"] == "Buscar" for item in snapshot["elements"])
    assert typed["ok"] is True
    assert clicked["ok"] is True
    assert smart["ok"] is True
    assert smart["element"]["text"] == "Enviar"
    assert clicked_value == "yes"


def test_smart_click_uses_accessible_button_name(monkeypatch, tmp_path):
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
        % str(tmp_path / "profile-smart").replace("\\", "\\\\"),
        encoding="utf-8",
    )
    monkeypatch.setenv("APOLO_CONFIG_FILE", str(config))

    def run_browser_check():
        b = PlaywrightBrowser(headless=True)
        try:
            b.open("data:text/html,<button aria-label='Reproducir canci&oacute;n' onclick=\"document.body.dataset.play='yes'\"></button>")
            clicked = b.smart_click(target="reproducir")
            clicked_value = b._page.evaluate("document.body.dataset.play")
            return clicked, clicked_value
        finally:
            b.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        clicked, clicked_value = executor.submit(run_browser_check).result()

    assert clicked["ok"] is True
    assert clicked["element"]["aria"] == "Reproducir canción"
    assert clicked_value == "yes"
