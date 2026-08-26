import asyncio
from contextlib import contextmanager
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.config import get_bool, get_int, get_str
from core.logging import write_log
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

    def __init__(
        self,
        user_data_dir: Optional[str] = None,
        headless: Optional[bool] = None,
        force_launch: bool = False,
    ):
        self.user_data_dir = (
            user_data_dir
            or get_str("browser.profile", env="APOLO_BROWSER_PROFILE")
            or str(Path.home() / ".apolo-profile")
        )
        self.user_data_dir = os.path.expandvars(self.user_data_dir)
        self.profile_directory = get_str(
            "browser.profile_directory", env="APOLO_BROWSER_PROFILE_DIRECTORY"
        )
        self.cdp_endpoint = None if force_launch else get_str(
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
        self._suspend_focus_sync = 0
        self._controlled_pages: Dict[str, Any] = {}
        self.state: Dict[str, Any] = {
            "url": None,
            "title": None,
            "tab": 0,
            "visibleElements": [],
            "recentActions": [],
            "lastSelectedElement": None,
            "controlledTabs": {},
        }

    def _ensure_started(self):
        if self._started:
            self._sync_to_focused_page()
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

    def _sync_to_focused_page(self):
        if self._suspend_focus_sync or not self._context:
            return
        focused = self._focused_page()
        if focused is not None:
            self._page = focused

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

    def dom_snapshot(self, max_elements: int = 40) -> Dict[str, Any]:
        self._ensure_started()
        elements = self._page.evaluate(
            """
            (maxElements) => {
                const selectorFor = (el) => {
                    if (el.id) return `#${CSS.escape(el.id)}`;
                    const data = ['data-testid', 'data-test', 'name', 'aria-label']
                        .map((attr) => [attr, el.getAttribute(attr)])
                        .find(([, value]) => value);
                    if (data) return `${el.tagName.toLowerCase()}[${data[0]}="${CSS.escape(data[1])}"]`;
                    const parent = el.parentElement;
                    if (!parent) return el.tagName.toLowerCase();
                    const index = Array.from(parent.children).indexOf(el) + 1;
                    return `${el.tagName.toLowerCase()}:nth-child(${index})`;
                };
                const visible = (el) => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 2 && rect.height > 2 &&
                        style.visibility !== 'hidden' && style.display !== 'none';
                };
                const nodes = Array.from(document.querySelectorAll(
                    'a, button, input, textarea, select, [role="button"], [contenteditable="true"]'
                )).filter(visible).slice(0, maxElements);
                return nodes.map((el, index) => ({
                    index,
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || '',
                    text: (el.innerText || el.value || el.textContent || '').trim().slice(0, 160),
                    aria: el.getAttribute('aria-label') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    href: el.href || '',
                    selector: selectorFor(el)
                }));
            }
            """,
            max_elements,
        )
        self.state["visibleElements"] = elements
        self._update_state("dom_snapshot")
        return {"url": self._page.url, "title": self._page.title(), "elements": elements}

    def dom_click(self, target: str = "", index: Optional[int] = None, selector: str = "") -> Dict[str, Any]:
        self._ensure_started()
        if selector:
            self._page.locator(selector).first.click()
            self._update_state("dom_click")
            return {"ok": True, "selector": selector}
        if index is not None:
            snapshot = self.dom_snapshot(max_elements=max(index + 1, 40))
            elements = snapshot.get("elements", [])
            if index < 0 or index >= len(elements):
                raise IndexError("element index out of range")
            selector = elements[index]["selector"]
            self._page.locator(selector).first.click()
            self._update_state("dom_click")
            return {"ok": True, "index": index, "selector": selector}
        if not target:
            raise ValueError("target, index, or selector is required")
        clicked = self._page.evaluate(
            """
            (target) => {
                const needle = target.toLowerCase();
                const nodes = Array.from(document.querySelectorAll(
                    'a, button, [role="button"], input[type="button"], input[type="submit"]'
                ));
                const node = nodes.find((el) => {
                    const value = [
                        el.innerText,
                        el.textContent,
                        el.value,
                        el.getAttribute('aria-label'),
                        el.getAttribute('title')
                    ].filter(Boolean).join(' ').toLowerCase();
                    return value.includes(needle);
                });
                if (!node) return false;
                node.click();
                return true;
            }
            """,
            target,
        )
        if not clicked:
            raise ValueError(f"DOM target not found: {target}")
        self._update_state("dom_click")
        return {"ok": True, "target": target}

    def smart_click(self, target: str = "", max_elements: int = 80, min_score: float = 0.45) -> Dict[str, Any]:
        self._ensure_started()
        target = " ".join(str(target or "").split())
        if not target:
            raise ValueError("target is required")
        snapshot = self.dom_snapshot(max_elements=max_elements)
        ranked = sorted(
            (
                (_element_match_score(target, element), index, element)
                for index, element in enumerate(snapshot.get("elements", []))
                if _element_is_clickable(element)
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        if not ranked or ranked[0][0] < min_score:
            raise ValueError(f"DOM target not found: {target}")
        score, index, element = ranked[0]
        selector = element.get("selector")
        if not selector:
            raise ValueError(f"DOM target has no selector: {target}")
        self._page.locator(selector).first.click()
        self.state["lastSelectedElement"] = {
            "target": target,
            "index": index,
            "score": score,
            "text": element.get("text", ""),
            "aria": element.get("aria", ""),
            "selector": selector,
        }
        self._update_state("smart_click")
        return {
            "ok": True,
            "target": target,
            "index": index,
            "score": round(score, 3),
            "selector": selector,
            "element": {
                "tag": element.get("tag", ""),
                "role": element.get("role", ""),
                "text": element.get("text", ""),
                "aria": element.get("aria", ""),
            },
        }

    def dom_type(self, text: str, target: str = "", selector: str = "", submit: bool = False) -> Dict[str, Any]:
        self._ensure_started()
        locator = None
        if selector:
            locator = self._page.locator(selector).first
        elif target:
            try:
                candidate = self._page.get_by_placeholder(target)
                locator = candidate.first if candidate.count() else None
            except Exception:
                locator = None
        if locator is None:
            locator = self._page.locator('input:not([type="hidden"]), textarea, [contenteditable="true"]').first
        locator.fill(text)
        if submit:
            locator.press("Enter")
        self._update_state("dom_type")
        return {"ok": True, "text": text, "submitted": submit}

    def dom_press(self, key: str) -> Dict[str, Any]:
        self._ensure_started()
        self._page.keyboard.press(key)
        self._update_state("dom_press")
        return {"ok": True, "key": key}

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

    def find_tab(self, url_contains: str = "", title_contains: str = "") -> Optional[int]:
        self._ensure_started()
        url_query = (url_contains or "").lower()
        title_query = (title_contains or "").lower()
        for index, page in enumerate(self._context.pages):
            try:
                url = (page.url or "").lower()
                title = (page.title() or "").lower()
            except Exception:
                continue
            if url_query and url_query not in url:
                continue
            if title_query and title_query not in title:
                continue
            return index
        return None

    def _focused_page(self):
        for page in self._context.pages:
            try:
                if page.evaluate("document.hasFocus()"):
                    return page
            except Exception:
                continue
        return None

    def _remember_controlled_page(self, key: str, page) -> None:
        if not key or page is None:
            return
        self._controlled_pages[key] = page
        self.state["controlledTabs"][key] = self._page_snapshot(page)

    def _controlled_page(self, key: str):
        page = self._controlled_pages.get(key)
        if page is None:
            return None
        try:
            if page.is_closed():
                self._controlled_pages.pop(key, None)
                self.state["controlledTabs"].pop(key, None)
                return None
        except Exception:
            return None
        return page

    def _page_snapshot(self, page=None) -> Dict[str, Any]:
        page = page or self._page
        if page is None:
            return {"index": None, "url": None, "title": None}
        try:
            index = self._context.pages.index(page) if self._context else None
        except Exception:
            index = None
        try:
            url = page.url
        except Exception:
            url = None
        try:
            title = page.title()
        except Exception:
            title = None
        return {"index": index, "url": url, "title": title}

    @contextmanager
    def using_tab(
        self,
        url_contains: str = "",
        title_contains: str = "",
        create_url: Optional[str] = None,
        restore: bool = True,
        remember_key: str = "",
    ):
        self._ensure_started()
        previous = self._focused_page() or self._page
        before = self._page_snapshot(previous)
        self._suspend_focus_sync += 1
        try:
            page = self._controlled_page(remember_key)
            if page is None:
                index = self.find_tab(url_contains=url_contains, title_contains=title_contains)
                page = None if index is None else self._context.pages[index]
            if page is None:
                if not create_url:
                    yield None
                    return
                page = self._context.new_page()
                page.goto(create_url, timeout=self.navigation_timeout_ms, wait_until="domcontentloaded")
            self._remember_controlled_page(remember_key, page)
            self._page = page
            target = self._page_snapshot(page)
            write_log(
                "BROWSER",
                "tab_context_enter",
                before=before,
                target=target,
                remember_key=remember_key,
                url_contains=url_contains,
                title_contains=title_contains,
            )
            yield page
        finally:
            if "page" in locals():
                target = self._page_snapshot(page)
                self._remember_controlled_page(remember_key, page)
            self._suspend_focus_sync = max(0, self._suspend_focus_sync - 1)
            if restore and previous is not None:
                try:
                    if not previous.is_closed():
                        self._page = previous
                        previous.bring_to_front()
                        write_log(
                            "BROWSER",
                            "tab_context_restore",
                            restored=self._page_snapshot(previous),
                            target=target if "target" in locals() else None,
                        )
                except Exception:
                    pass

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
            self.state["tab"] = self._context.pages.index(self._page) if self._context else 0
        except Exception:
            pass
        current = self._page_snapshot()
        self.state["recentActions"].append({"action": action, "ts": time.time(), "page": current})
        write_log("BROWSER", "action", action=action, page=current)


def _element_is_clickable(element: Dict[str, Any]) -> bool:
    tag = str(element.get("tag") or "").lower()
    role = str(element.get("role") or "").lower()
    return tag in {"a", "button", "input"} or role == "button" or bool(element.get("href"))


def _element_match_score(target: str, element: Dict[str, Any]) -> float:
    target_norm = _norm_match_text(target)
    labels = [
        element.get("text", ""),
        element.get("aria", ""),
        element.get("placeholder", ""),
        element.get("href", ""),
    ]
    return max((_text_match_score(target_norm, _norm_match_text(str(label or ""))) for label in labels), default=0.0)


def _text_match_score(target: str, label: str) -> float:
    if not target or not label:
        return 0.0
    if target == label:
        return 1.0
    if target in label:
        return min(0.95, len(target) / max(len(label), 1) + 0.35)
    target_tokens = set(target.split())
    label_tokens = set(label.split())
    if not target_tokens or not label_tokens:
        return 0.0
    overlap = len(target_tokens & label_tokens) / len(target_tokens | label_tokens)
    return max(0.55, overlap) if overlap else 0.0


def _norm_match_text(text: str) -> str:
    cleaned = str(text or "").lower()
    cleaned = re.sub(r"[_\-]+", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9áéíóúüñ\s]", " ", cleaned)
    return " ".join(cleaned.split())
