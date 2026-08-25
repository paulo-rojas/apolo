import asyncio
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import get_bool, get_int, get_str
from .executable_resolver import resolve_browser_executable
from .selector_utils import find_by_accessibility, simple_text_locator_candidates
from core.recovery import retry_action, classify_exception, ErrorCategory

try:
    import pytesseract
    from PIL import Image
    _HAS_OCR = True
except Exception:
    _HAS_OCR = False


class PlaywrightNotInstalled(RuntimeError):
    pass


class BrowserProfileInUse(RuntimeError):
    pass


class BrowserCdpUnavailable(RuntimeError):
    pass


class PlaywrightBrowser:
    """Playwright-based browser wrapper with accessibility-first search and retries.

    Provides recovery strategies for clicks: scroll into view, retry with text locators,
    and screenshot+OCR fallback when available.
    """

    def __init__(self, user_data_dir: Optional[str] = None, headless: Optional[bool] = None):
        self.user_data_dir = (
            user_data_dir
            or get_str("browser.profile", env="APOLO_BROWSER_PROFILE")
            or str(Path.home() / ".apolo-profile")
        )
        self.user_data_dir = os.path.expandvars(self.user_data_dir)
        self.profile_directory = get_str(
            "browser.profile_directory", env="APOLO_BROWSER_PROFILE_DIRECTORY"
        )
        self.cdp_endpoint = get_str(
            "browser.cdp_endpoint", env="APOLO_BROWSER_CDP_ENDPOINT"
        )
        self.headless = get_bool("browser.headless", True, env="APOLO_BROWSER_HEADLESS") if headless is None else headless
        self.executable_path = resolve_browser_executable()
        self.default_timeout_ms = get_int(
            "browser.timeout_ms", 15000, env="APOLO_BROWSER_TIMEOUT_MS", minimum=1000
        )
        self.navigation_timeout_ms = get_int(
            "browser.navigation_timeout_ms",
            self.default_timeout_ms,
            env="APOLO_BROWSER_NAVIGATION_TIMEOUT_MS",
            minimum=1000,
        )
        self._started = False
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self.state: Dict[str, Any] = {
            "url": None,
            "title": None,
            "tab": 0,
            "visibleElements": [],
            "recentActions": [],
            "lastSelectedElement": None,
        }

    def _ensure_started(self):
        if self._started:
            return
        try:
            from playwright.sync_api import sync_playwright

        except Exception as e:
            raise PlaywrightNotInstalled(
                "playwright is not installed or browsers not available"
            ) from e

        self._clear_running_loop_for_sync_playwright()
        self._playwright = sync_playwright().start()
        if self.cdp_endpoint:
            self._connect_over_cdp()
            return

        self._launch_persistent_context()

    def _connect_over_cdp(self):
        try:
            self._browser = self._playwright.chromium.connect_over_cdp(
                self.cdp_endpoint,
                timeout=self.default_timeout_ms,
            )
        except Exception as e:
            raise BrowserCdpUnavailable(
                "Brave no esta exponiendo CDP en "
                f"{self.cdp_endpoint}. Cierra Brave completo y abrelo con "
                "--remote-debugging-port=9222."
            ) from e
        contexts = self._browser.contexts
        self._context = contexts[0] if contexts else self._browser.new_context()
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._context.set_default_timeout(self.default_timeout_ms)
        self._context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._started = True

    def _launch_persistent_context(self):
        launch_options = {
            "user_data_dir": self.user_data_dir,
            "headless": self.headless,
            "timeout": self.default_timeout_ms,
        }
        if self.profile_directory:
            launch_options["args"] = [f"--profile-directory={self.profile_directory}"]
        if self.executable_path:
            launch_options["executable_path"] = self.executable_path
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                **launch_options
            )
        except Exception as e:
            if "Opening in existing browser session" in str(e):
                raise BrowserProfileInUse(
                    "El perfil del navegador ya esta en uso. Cierra ese navegador "
                    "antes de usar este perfil con Apolo, o inicia Brave con "
                    "--remote-debugging-port y configura browser.cdp_endpoint."
                ) from e
            raise
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        self._context.set_default_timeout(self.default_timeout_ms)
        self._context.set_default_navigation_timeout(self.navigation_timeout_ms)
        self._started = True

    @staticmethod
    def _clear_running_loop_for_sync_playwright():
        # Uvicorn/Python 3.14 can leave a running loop marker on this sync worker.
        # Playwright's sync API is safe here because browser calls run off the app loop.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if loop.is_running():
            asyncio.events._set_running_loop(None)

    @retry_action(max_retries=None, backoff=0.4)
    def open(self, url: str, timeout: Optional[int] = None, wait_until: str = "domcontentloaded"):
        self._ensure_started()
        try:
            timeout_ms = int(timeout * 1000) if timeout is not None else self.navigation_timeout_ms
            self._page.goto(url, timeout=timeout_ms, wait_until=wait_until)
            # brief stabilization
            time.sleep(0.15)
            self._update_state("open")
            return {"url": self._page.url, "title": self._page.title()}
        except Exception as e:
            raise

    def get_state(self) -> Dict[str, Any]:
        self._ensure_started()
        self._update_state("get_state")
        return dict(self.state)

    def snapshot_state(self) -> Dict[str, Any]:
        return dict(self.state)

    def find(self, text: str, max_results: int = 5) -> Dict[str, Any]:
        self._ensure_started()
        # 1) accessibility tree
        acc = find_by_accessibility(self._page, text, max_results)
        if acc:
            results = [{"type": "accessibility", **a} for a in acc]
            return {"count": len(results), "results": results}

        # 2) text locator
        txt = simple_text_locator_candidates(self._page, text, max_results)
        if txt:
            results = [{"type": "text", **t} for t in txt]
            return {"count": len(results), "results": results}

        return {"count": 0, "results": []}

    @retry_action(max_retries=None, backoff=0.5)
    def click(self, selector: Dict[str, Any] = None, timeout: int = 15):
        self._ensure_started()
        if selector is None:
            raise ValueError("selector is required")

        before_url = self._page.url
        try:
            # Primary attempt: semantic or CSS selector with scroll into view
            if "selector" in selector:
                locator = self._page.locator(selector["selector"])
                try:
                    locator.scroll_into_view_if_needed()
                except Exception:
                    pass
                locator.click(timeout=timeout * 1000)

            elif selector.get("type") == "accessibility":
                name = selector.get("name")
                if name:
                    loc = self._page.locator(f'text="{name}"')
                    try:
                        loc.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    loc.click()
                else:
                    raise ValueError("accessibility selector missing name")

            elif "role" in selector:
                role = selector.get("role")
                name = selector.get("name")
                el = self._page.get_by_role(role, name=name)
                try:
                    el.scroll_into_view_if_needed()
                except Exception:
                    pass
                el.click()

            else:
                text = selector.get("text")
                if text:
                    loc = self._page.locator(f'text="{text}"')
                    try:
                        loc.scroll_into_view_if_needed()
                    except Exception:
                        pass
                    loc.click()
                else:
                    raise ValueError("Unsupported selector descriptor")

            # verification: if URL changed assume navigation; else return success
            time.sleep(0.15)
            after_url = self._page.url
            if after_url != before_url:
                self._update_state("click")
                return {"ok": True, "navigated": True, "url": after_url}

            self._update_state("click")
            return {"ok": True, "navigated": False}

        except Exception as e:
            cat = classify_exception(e)
            # recovery attempts: scroll+retry, text fallback, screenshot+OCR
            try:
                # scroll a bit and retry once
                self._page.evaluate("window.scrollBy(0, 250)")
                time.sleep(0.2)
                name = selector.get("name") or selector.get("text")
                if name:
                    try:
                        self._page.click(f'text="{name}"', timeout=5000)
                        self._update_state("click_retry")
                        return {"ok": True, "recovered": True}
                    except Exception:
                        pass

                # screenshot fallback
                path = str(Path.cwd() / "apolo_click_error.png")
                self._page.screenshot(path=path, full_page=True)
                ocr_text = ""
                if _HAS_OCR:
                    try:
                        ocr_text = pytesseract.image_to_string(Image.open(path))
                    except Exception:
                        ocr_text = ""

                return {"ok": False, "error": str(e), "category": cat, "screenshot": path, "ocr": ocr_text}
            except Exception:
                return {"ok": False, "error": str(e), "category": cat}

    def type(self, selector: Dict[str, Any], text: str, timeout: int = 15):
        self._ensure_started()
        if "selector" in selector:
            self._page.fill(selector["selector"], text, timeout=timeout * 1000)
        elif "placeholder" in selector:
            el = self._page.get_by_placeholder(selector.get("placeholder"))
            el.fill(text)
        else:
            raise ValueError("Unsupported selector for type")
        self._update_state("type")
        return {"ok": True}

    def scroll(self, direction: str = "down", amount: int = 400):
        self._ensure_started()
        if direction == "down":
            self._page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            self._page.evaluate(f"window.scrollBy(0, -{amount})")
        else:
            raise ValueError("direction must be 'down' or 'up'")
        self._update_state("scroll")
        return {"ok": True}

    def screenshot(self, path: Optional[str] = None) -> Dict[str, Any]:
        self._ensure_started()
        path = path or str(Path.cwd() / "apolo_screenshot.png")
        self._page.screenshot(path=path, full_page=True)
        return {"path": path}

    def list_tabs(self) -> List[Dict[str, Any]]:
        self._ensure_started()
        tabs = []
        for i, p in enumerate(self._context.pages):
            tabs.append({"index": i, "url": p.url, "title": p.title()})
        return tabs

    def switch_tab(self, index: int = 0):
        self._ensure_started()
        pages = self._context.pages
        if index < 0 or index >= len(pages):
            raise IndexError("tab index out of range")
        self._page = pages[index]
        self._update_state("switch_tab")
        return {"ok": True, "tab": index, "url": self._page.url}

    def back(self):
        self._ensure_started()
        try:
            self._page.go_back()
            self._update_state("back")
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def close(self):
        if self._context and not self._browser:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._started = False
        self._context = None
        self._page = None
        self._browser = None
        self._playwright = None
        return {"ok": True}

    def _update_state(self, action: str):
        try:
            self.state["url"] = self._page.url
            self.state["title"] = self._page.title()
        except Exception:
            pass
        self.state["recentActions"].append({"action": action, "ts": time.time()})
