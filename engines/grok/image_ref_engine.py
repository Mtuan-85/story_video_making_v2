"""GrokImageRefEngine — linear image-gen flow when reference images are used.

Differs from the masonry-based ``GrokImageEngine``:
- Multi-file ref upload (1-5) BEFORE prompt entry.
- Grok resets aspect to "Original" on upload — we re-apply project aspect.
- Single result lands on /imagine/post/{uuid}; download directly (no
  candidate masonry, no Claude pick step).

Stops on the worker's asyncio.Event between every step.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any

from loguru import logger as log
from patchright.async_api import Page

from engines.grok import actions as A
from engines.grok import selectors as SEL


class GrokImageRefEngine:
    """Engine for image generation WITH 1-5 reference images."""

    def __init__(self, page: Page) -> None:
        self.page = page
        self._stop_event: asyncio.Event | None = None

    def set_stop_event(self, event: asyncio.Event | None) -> None:
        self._stop_event = event

    def _check_stop(self) -> None:
        if self._stop_event is not None and self._stop_event.is_set():
            raise asyncio.CancelledError("Stopped by user")

    async def gen_image_with_refs(
        self,
        scene_id: str,
        prompt: str,
        ref_paths: list[Path],
        output_path: Path,
        aspect: str,
        wait_timeout_s: int = 60,
    ) -> dict[str, Any]:
        """Run flow: upload refs → set_aspect → fill_prompt → submit → download.

        Returns ``{"ok": bool, "path": str | None, "reason": str (on fail)}``.
        Caller (worker) is responsible for state.json updates.
        """
        log.info(
            f"[{scene_id}] Image-with-refs flow: {len(ref_paths)} ref(s), aspect={aspect}"
        )

        try:
            self._check_stop()
            r = await A.ensure_at(self.page, "/imagine")
            if not r.get("ok"):
                return {"ok": False, "reason": f"ensure_at: {r.get('reason')}"}

            self._check_stop()
            r = await A.set_mode(self.page, "image")
            if not r.get("ok"):
                return {"ok": False, "reason": f"set_mode: {r.get('reason')}"}

            # Upload refs — Grok will silently reset aspect to "Original" after this.
            self._check_stop()
            r = await A.upload_ref_if_present(self.page, ref_paths=ref_paths)
            if not r.get("ok"):
                return {"ok": False, "reason": f"upload_refs: {r.get('reason')}"}

            self._check_stop()
            await asyncio.sleep(0.5)
            r = await A.set_aspect(self.page, aspect)
            if not r.get("ok"):
                log.warning(
                    f"[{scene_id}] set_aspect '{aspect}' failed (continuing): "
                    f"{r.get('reason')}"
                )

            self._check_stop()
            r = await A.fill_prompt(self.page, prompt)
            if not r.get("ok"):
                return {"ok": False, "reason": f"fill_prompt: {r.get('reason')}"}

            self._check_stop()
            r = await A.click_submit(self.page)
            if not r.get("ok"):
                return {"ok": False, "reason": f"click_submit: {r.get('reason')}"}

            self._check_stop()
            ready = await self._wait_image_ready(initial_wait_s=30, timeout_s=120)
            if not ready:
                return {"ok": False, "reason": "timeout waiting image ready"}

            self._check_stop()
            r = await self._download_to(output_path)
            if not r.get("ok"):
                return {"ok": False, "reason": f"download: {r.get('reason')}"}

            self._check_stop()
            try:
                back = self.page.locator(SEL.BACK).first
                if await back.count() > 0:
                    await back.click()
                    await self.page.wait_for_url("**/imagine", timeout=10000)
            except Exception as e:
                log.warning(f"[{scene_id}] Back navigation failed (continuing): {e}")
                try:
                    await self.page.goto("https://grok.com/imagine", timeout=15000)
                except Exception as e2:
                    log.warning(f"[{scene_id}] goto /imagine also failed: {e2}")

            log.info(f"[{scene_id}] Image-with-refs DONE → {output_path.name}")
            return {"ok": True, "path": str(output_path)}

        except asyncio.CancelledError:
            log.warning(f"[{scene_id}] Cancelled by user")
            return {"ok": False, "reason": "cancelled"}
        except Exception as e:
            log.error(f"[{scene_id}] Image-with-refs failed: {e}")
            return {"ok": False, "reason": str(e)}

    async def _wait_image_ready(
        self, initial_wait_s: int = 30, timeout_s: int = 120
    ) -> bool:
        """Image-with-refs wait — same shape as ``actions.wait_video_ready``.

        Inlined (instead of calling the action) so we can interleave
        ``_check_stop()`` between every sleep tick — Stop All stays responsive
        even during the 30s initial wait. The ref-upload preview makes the
        Download button visible from T=0, so the overlay-gone + download-visible
        double-check is the only reliable "image truly ready" signal.
        """
        try:
            await self.page.wait_for_url("**/imagine/post/**", timeout=20000)
        except Exception as e:
            log.warning(f"URL didn't navigate to /post/: {e}")

        log.info(
            f"_wait_image_ready: initial sleep {initial_wait_s}s with stop checks..."
        )
        for _ in range(initial_wait_s):
            self._check_stop()
            await asyncio.sleep(1)

        overlay_pattern = re.compile(r"Generating\s+\d+%")
        poll_budget_s = max(0, timeout_s - initial_wait_s)
        log.info(f"Polling for image ready (max {poll_budget_s}s)...")
        start = time.time()

        while (time.time() - start) < poll_budget_s:
            self._check_stop()
            try:
                overlays = self.page.locator("div").filter(has_text=overlay_pattern)
                overlay_count = await overlays.count()
            except Exception:
                overlay_count = -1

            if overlay_count == 0:
                try:
                    btn = self.page.locator(SEL.DOWNLOAD).first
                    if await btn.count() > 0 and await btn.is_visible():
                        log.info("Image ready (overlay gone, download visible)")
                        await asyncio.sleep(1.0)
                        return True
                except Exception:
                    pass

            err = await A.detect_error(self.page)
            if err:
                log.error(f"Error toast: {err}")
                return False

            await asyncio.sleep(2)

        log.error(f"Timeout waiting image ready after {timeout_s}s")
        return False

    async def _download_to(self, output_path: Path) -> dict[str, Any]:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            btn = self.page.locator(SEL.DOWNLOAD).first

            async with self.page.expect_download(timeout=60000) as dl_info:
                await btn.click()
            download = await dl_info.value

            await download.save_as(str(output_path))
            if not output_path.exists():
                return {"ok": False, "reason": "file not saved"}
            log.info(f"Downloaded: {output_path}")
            return {"ok": True, "path": str(output_path)}
        except Exception as e:
            return {"ok": False, "reason": f"download: {e}"}
