"""Browser automation actions via Playwright (Chrome/Safari/Firefox).

Provides a persistent browser session shared across all calls so that
successive commands ("navigate", "click", "type", "get text") operate on
the same live page without re-launching.

Direct voice-action functions (used by commands.yaml):
    browser_navigate(url)        – go to a URL
    browser_web_search(query)    – open browser and DuckDuckGo-search
    browser_get_page_text()      – read visible text of the current page
    browser_close()              – close the browser window

The higher-level ``browser_action`` dispatcher (used by the LLM tool in
brain/tools.py) wraps all of the above plus click / type / get_url.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Optional

log = logging.getLogger("jarvis.actions.browser")

# ── Module-level config (injected from core.py or config.yaml) ───────────────

_browser_cfg: dict = {}


def set_browser_config(cfg: dict) -> None:
    """Inject the ``browser`` config block.  Called once at startup."""
    global _browser_cfg
    _browser_cfg = cfg or {}


# ── Singleton Playwright session ─────────────────────────────────────────────

_lock = threading.Lock()
_playwright = None   # playwright handle
_browser = None      # Browser instance
_page = None         # active Page

_MAX_GET_TEXT_CHARS = 4_000


def _ensure_session():
    """Return the current Page, launching the browser if needed."""
    global _playwright, _browser, _page

    # Reuse if still alive
    if _page is not None:
        try:
            if not _page.is_closed():
                return _page
        except Exception:
            pass  # stale reference – fall through to relaunch

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError:
        raise RuntimeError(
            "playwright is not installed. "
            "Run: pip install playwright && python -m playwright install"
        )

    browser_type = _browser_cfg.get("browser", "chromium")   # chromium | webkit | firefox
    headless = _browser_cfg.get("headless", False)            # visible by default

    _playwright = sync_playwright().start()
    factory = getattr(_playwright, browser_type)
    _browser = factory.launch(headless=headless)
    _page = _browser.new_page()
    log.info("Browser session started (%s, headless=%s)", browser_type, headless)
    return _page


def _close_session() -> None:
    """Tear down browser + playwright handles."""
    global _playwright, _browser, _page

    if _browser is not None:
        try:
            _browser.close()
        except Exception:
            pass
        _browser = None

    if _playwright is not None:
        try:
            _playwright.stop()
        except Exception:
            pass
        _playwright = None

    _page = None
    log.info("Browser session closed.")


# ── Public action functions ───────────────────────────────────────────────────

def browser_navigate(url: str, **_) -> str:
    """Navigate to *url* and return the page title."""
    if not url or not url.strip():
        return "Error: no URL provided."

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    with _lock:
        try:
            page = _ensure_session()
            page.goto(url, timeout=30_000, wait_until="domcontentloaded")
            return f"Navigated to: {page.title()} — {page.url}"
        except Exception as exc:
            log.warning("browser_navigate error: %s", exc)
            return f"Error navigating to {url}: {exc}"


def browser_web_search(query: str, **_) -> str:
    """Open DuckDuckGo in the browser and return the top result snippets."""
    if not query or not query.strip():
        return "Error: no search query provided."

    search_url = "https://duckduckgo.com/?q=" + query.strip().replace(" ", "+")

    with _lock:
        try:
            page = _ensure_session()
            page.goto(search_url, timeout=30_000, wait_until="domcontentloaded")

            # Collect result snippets (DuckDuckGo HTML layout)
            snippets: list[str] = []
            for sel in ("[data-result='snippet']", ".result__snippet", ".OgdwYG"):
                els = page.query_selector_all(sel)
                for el in els[:5]:
                    text = el.inner_text().strip()
                    if text:
                        snippets.append(text)
                if snippets:
                    break

            if not snippets:
                # Fallback: grab raw body text
                body = page.inner_text("body")
                return f"Search results for '{query}':\n{body[:_MAX_GET_TEXT_CHARS]}"

            return "Search results for '{}': {}".format(
                query, "\n---\n".join(snippets[:5])
            )
        except Exception as exc:
            log.warning("browser_web_search error: %s", exc)
            return f"Error searching for '{query}': {exc}"


def browser_get_page_text(selector: str = "body", **_) -> str:
    """Return the visible text of the current page (or a CSS selector)."""
    with _lock:
        try:
            page = _ensure_session()
            text = page.inner_text(selector)
            if len(text) > _MAX_GET_TEXT_CHARS:
                text = text[:_MAX_GET_TEXT_CHARS] + "\n…[truncated]"
            return text
        except Exception as exc:
            log.warning("browser_get_page_text error: %s", exc)
            return f"Error reading page text: {exc}"


def browser_close(**_) -> str:
    """Close the browser window."""
    with _lock:
        _close_session()
    return "Browser closed."


def browser_screenshot(path: str = "", **_) -> str:
    """Take a screenshot of the current page and save it."""
    if not path:
        screenshots_dir = os.path.expanduser("~/.jarvis/screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        path = os.path.join(screenshots_dir, f"browser_{int(time.time())}.png")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    with _lock:
        try:
            page = _ensure_session()
            page.screenshot(path=path)
            return f"Screenshot saved: {path}"
        except Exception as exc:
            log.warning("browser_screenshot error: %s", exc)
            return f"Error taking screenshot: {exc}"


# ── High-level dispatcher (used by LLM tool) ─────────────────────────────────

def browser_action(
    action: str,
    url: str = "",
    selector: str = "",
    text: str = "",
    query: str = "",
    **_,
) -> str:
    """Dispatch a single browser automation step.

    action  : navigate | search | click | type | get_text | get_url | screenshot | close
    url     : target URL              (navigate)
    selector: CSS selector            (click / type / get_text)
    text    : text to enter           (type)
    query   : search string           (search)
    """
    action = (action or "").lower().strip()

    if action == "navigate":
        return browser_navigate(url)

    if action == "search":
        return browser_web_search(query or url)

    if action == "click":
        if not selector:
            return "Error: 'click' requires a 'selector'."
        with _lock:
            try:
                page = _ensure_session()
                page.click(selector, timeout=10_000)
                return f"Clicked '{selector}'"
            except Exception as exc:
                return f"Error clicking '{selector}': {exc}"

    if action == "type":
        if not selector or not text:
            return "Error: 'type' requires both 'selector' and 'text'."
        with _lock:
            try:
                page = _ensure_session()
                page.fill(selector, text)
                return f"Typed into '{selector}'"
            except Exception as exc:
                return f"Error typing into '{selector}': {exc}"

    if action == "press_enter":
        target = selector or "body"
        with _lock:
            try:
                page = _ensure_session()
                page.press(target, "Enter")
                page.wait_for_load_state("domcontentloaded", timeout=15_000)
                return "Pressed Enter"
            except Exception as exc:
                return f"Error pressing Enter: {exc}"

    if action == "get_text":
        return browser_get_page_text(selector or "body")

    if action == "get_url":
        with _lock:
            try:
                page = _ensure_session()
                return f"Current URL: {page.url}"
            except Exception as exc:
                return f"Error: {exc}"

    if action == "screenshot":
        return browser_screenshot()

    if action == "close":
        return browser_close()

    return (
        f"Error: unknown browser action '{action}'. "
        "Valid actions: navigate, search, click, type, press_enter, "
        "get_text, get_url, screenshot, close."
    )
