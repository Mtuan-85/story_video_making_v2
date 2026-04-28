"""CDP browser connection — implements EngineConnection Protocol.

Wraps Patchright's connect_over_cdp. Lists/selects existing tabs (the user
keeps the browser open and logged in — we never spawn).
"""

from __future__ import annotations

from typing import Any

from loguru import logger as log
from patchright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)

GROK_HOST = "grok.com"


class GrokConnection:
    """Persistent CDP attach to an already-running Brave/Chrome instance.

    Lifecycle:
        conn = GrokConnection()
        await conn.connect("http://localhost:9222")
        tabs = await conn.list_tabs()
        await conn.select_tab(tabs[0]["index"])
        page = conn.page  # use this with the engines
        ...
        await conn.disconnect()
    """

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page | None:
        return self._page

    # EngineConnection Protocol --------------------------------------------------

    async def connect(self, cdp_url: str) -> None:
        if await self.is_connected():
            return
        self._pw = await async_playwright().start()
        try:
            self._browser = await self._pw.chromium.connect_over_cdp(cdp_url)
        except Exception as e:
            await self._cleanup()
            raise RuntimeError(f"Không thể kết nối CDP {cdp_url}: {e}") from e

        contexts = self._browser.contexts
        if not contexts:
            await self._cleanup()
            raise RuntimeError("Browser không có context nào")
        self._context = contexts[0]
        log.info(f"Đã kết nối CDP: {cdp_url}")

    async def disconnect(self) -> None:
        await self._cleanup()
        log.info("Đã ngắt kết nối CDP")

    async def is_connected(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    # Tab management (UI-driven) -------------------------------------------------

    async def list_tabs(self, grok_only: bool = True) -> list[dict[str, Any]]:
        if not self._context:
            return []
        tabs: list[dict[str, Any]] = []
        for idx, page in enumerate(self._context.pages):
            url = page.url or ""
            if grok_only and GROK_HOST not in url:
                continue
            try:
                title = await page.title()
            except Exception:
                title = "(untitled)"
            tabs.append({"index": idx, "title": title, "url": url})
        return tabs

    async def select_tab(self, index: int) -> dict[str, Any]:
        if not self._context:
            raise RuntimeError("Chưa kết nối")
        pages = self._context.pages
        if index < 0 or index >= len(pages):
            raise IndexError(f"Tab index {index} không hợp lệ (có {len(pages)} tab)")
        self._page = pages[index]
        try:
            await self._page.bring_to_front()
            title = await self._page.title()
        except Exception:
            title = "(untitled)"
        log.info(f"Đã chọn tab #{index}: {title}")
        return {"index": index, "title": title, "url": self._page.url}

    # ---------------------------------------------------------------------------

    async def _cleanup(self) -> None:
        try:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception as e:
                    log.debug(f"Browser close ignored: {e}")
            if self._pw is not None:
                await self._pw.stop()
        finally:
            self._page = None
            self._context = None
            self._browser = None
            self._pw = None
