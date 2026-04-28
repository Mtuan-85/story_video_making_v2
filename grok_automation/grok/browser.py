from __future__ import annotations

from typing import Any

from loguru import logger
from patchright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

GROK_HOST = "grok.com"


class BrowserManager:
    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page | None:
        return self._page

    @property
    def is_connected(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def connect(self, cdp_url: str) -> dict[str, Any]:
        if self.is_connected:
            return {"ok": True, "reason": "already_connected"}

        try:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.connect_over_cdp(cdp_url)
            contexts = self._browser.contexts
            if not contexts:
                await self.disconnect()
                return {"ok": False, "reason": "no_contexts"}
            self._context = contexts[0]
            logger.info(f"Connected to CDP at {cdp_url}")
            return {"ok": True}
        except Exception as e:
            logger.error(f"CDP connect failed: {e}")
            await self.disconnect()
            return {"ok": False, "reason": str(e)}

    async def list_tabs(self, grok_only: bool = True) -> list[dict[str, str]]:
        if not self._context:
            return []

        tabs: list[dict[str, str]] = []
        for idx, page in enumerate(self._context.pages):
            url = page.url or ""
            if grok_only and GROK_HOST not in url:
                continue
            try:
                title = await page.title()
            except Exception:
                title = "(untitled)"
            tabs.append({"index": str(idx), "title": title, "url": url})
        return tabs

    async def select_tab(self, index: int) -> dict[str, Any]:
        if not self._context:
            return {"ok": False, "reason": "not_connected"}

        pages = self._context.pages
        if index < 0 or index >= len(pages):
            return {"ok": False, "reason": "index_out_of_range"}

        self._page = pages[index]
        try:
            await self._page.bring_to_front()
            title = await self._page.title()
        except Exception:
            title = "(untitled)"
        url = self._page.url
        logger.info(f"Selected tab #{index}: {title}")
        return {"ok": True, "title": title, "url": url}

    async def disconnect(self) -> dict[str, Any]:
        try:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.debug(f"Browser close ignored: {e}")
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None
        logger.info("Disconnected")
        return {"ok": True}
