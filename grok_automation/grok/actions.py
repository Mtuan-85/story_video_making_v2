"""Atomic actions on grok.com/imagine page.

Each action takes a Patchright Page and returns a result dict
{"ok": bool, ...} per CLAUDE.md convention. Errors are logged
and returned, never raised — runner decides retry/skip.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger
from patchright.async_api import Page

from grok import selectors as SEL


# ---------- Human-like helpers ----------

async def human_pause(min_ms: int = 800, max_ms: int = 2500) -> None:
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


_TYPING_DELAYS = {
    "fast": (10, 25),
    "human": (40, 110),
    "slow": (80, 200),
}


async def human_type(
    page: Page,
    selector: str,
    text: str,
    speed: str = "human",
) -> None:
    lo, hi = _TYPING_DELAYS.get(speed, _TYPING_DELAYS["human"])
    await page.click(selector)
    await asyncio.sleep(random.uniform(0.3, 0.6))
    await page.type(selector, text, delay=random.randint(lo, hi))
    if random.random() < 0.05:
        await asyncio.sleep(random.uniform(0.2, 0.6))


async def human_click(locator) -> None:
    try:
        await locator.scroll_into_view_if_needed()
    except Exception:
        pass
    await asyncio.sleep(random.uniform(0.2, 0.5))
    try:
        await locator.hover()
        await asyncio.sleep(random.uniform(0.1, 0.3))
    except Exception:
        pass
    await locator.click()


# ---------- Navigation ----------

async def ensure_at(page: Page, url_fragment: str) -> dict[str, Any]:
    """Navigate to url_fragment if not there. Robust recovery from /post/.

    On /post/, try Back button first; if it fails, force `page.goto`.
    Always wait for the Generation mode dropdown after navigation so
    set_mode/set_quality won't time out on a half-rendered page.
    """
    target = url_fragment if url_fragment.startswith("/") else f"/{url_fragment}"
    current = page.url or ""

    if target in current:
        logger.debug(f"Already at {target}")
    else:
        logger.info(f"Navigating from {current} to {target}")
        navigated = False

        if "/post/" in current:
            try:
                back = page.locator(SEL.BACK)
                if await back.count() > 0:
                    await back.first.click(timeout=5000)
                    await page.wait_for_url(
                        re.compile(r".*/imagine(?!/post)"), timeout=10000
                    )
                    navigated = True
                    logger.debug("Navigated via Back button")
            except Exception as e:
                logger.warning(f"Back button click failed: {e}")

        if not navigated:
            logger.warning("Using direct goto as fallback")
            try:
                await page.goto(
                    f"https://grok.com{target}", wait_until="domcontentloaded",
                    timeout=30000,
                )
            except Exception as e:
                return {"ok": False, "reason": f"goto failed: {e}"}

    logger.debug("Waiting for Generation mode dropdown to render...")
    try:
        await page.locator(SEL.MODE_GROUP).wait_for(state="visible", timeout=15000)
        await asyncio.sleep(0.5)
        logger.debug(f"UI ready at {target}")
    except Exception as e:
        logger.error(
            f"Generation mode not visible at {page.url}. Error: {e}"
        )
        return {
            "ok": False,
            "reason": f"page not ready at {target}, url={page.url}",
        }

    return {"ok": True}


async def wait_url_match(page: Page, pattern: str, timeout: int = 30000) -> dict[str, Any]:
    try:
        await page.wait_for_url(re.compile(pattern), timeout=timeout)
        return {"ok": True, "url": page.url}
    except Exception as e:
        return {"ok": False, "reason": f"wait_url_match: {e}"}


# ---------- Input ----------

async def verify_input_empty(page: Page, timeout: int = 5000) -> dict[str, Any]:
    try:
        await page.wait_for_selector(SEL.PROMPT_INPUT_EMPTY, timeout=timeout)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"input not empty: {e}"}


async def fill_prompt(page: Page, text: str, speed: str = "human") -> dict[str, Any]:
    try:
        await human_type(page, SEL.PROMPT_INPUT, text, speed=speed)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"fill_prompt: {e}"}


async def click_submit(page: Page) -> dict[str, Any]:
    try:
        btn = page.locator(SEL.SUBMIT).first
        await human_click(btn)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"click_submit: {e}"}


# ---------- Mode / settings ----------

async def set_mode(page: Page, value: str) -> dict[str, Any]:
    """Click Image or Video radio button.

    Anchors to the Generation mode container — direct aria-label radio
    selectors only work on /imagine/post/{uuid}, not on /imagine main page.
    """
    target_text = value.strip().capitalize()  # "Image" or "Video"
    try:
        group = page.locator(SEL.MODE_GROUP)
        await group.wait_for(state="visible", timeout=10000)

        radios = group.locator('button[role="radio"]')
        n = await radios.count()
        logger.debug(f"set_mode group radios count={n}, target='{target_text}'")

        btn = group.locator(f'button:has-text("{target_text}")').first
        await btn.click()
        await asyncio.sleep(0.5)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"set_mode: {e}"}


async def set_quality(page: Page, value: str) -> dict[str, Any]:
    """Click Speed or Quality preset by text filter on role=radio buttons."""
    target = value.strip().lower()
    try:
        btns = page.locator(SEL.QUALITY_RADIO)
        n = await btns.count()
        labels: list[tuple[int, str, str]] = []
        for i in range(n):
            r = btns.nth(i)
            text = (await r.text_content() or "").strip()
            checked = (await r.get_attribute("aria-checked")) or ""
            labels.append((i, text, checked))
        logger.debug(f"set_quality radios: {labels}")

        for i, text, checked in labels:
            if text.lower() == target:
                if checked == "true":
                    return {"ok": True, "already": True}
                await btns.nth(i).click()
                await asyncio.sleep(0.5)
                return {"ok": True}
        return {"ok": False, "reason": f"quality '{value}' not found in {[l[1] for l in labels]}"}
    except Exception as e:
        return {"ok": False, "reason": f"set_quality: {e}"}


async def set_aspect(page: Page, value: str) -> dict[str, Any]:
    try:
        await page.locator(SEL.ASPECT_TRIGGER).first.click()
        await asyncio.sleep(0.4)
        options = page.locator(SEL.ASPECT_OPTION)
        n = await options.count()
        for i in range(n):
            text = (await options.nth(i).text_content() or "").strip()
            if text.startswith(value):
                await options.nth(i).click()
                await asyncio.sleep(0.3)
                return {"ok": True}
        # Close menu if no match
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return {"ok": False, "reason": f"aspect '{value}' not found in menu"}
    except Exception as e:
        return {"ok": False, "reason": f"set_aspect: {e}"}


# ---------- Image generation polling ----------

async def wait_image_ready(
    page: Page,
    target_count: int = 4,
    timeout_ms: int = 60000,
) -> dict[str, Any]:
    """Wait for `target_count` images ready in the latest masonry section.

    Does NOT require canvases to disappear — Speed mode generates unlimited
    images (more keep arriving as you scroll), so it never reaches "all done".
    We only need the first N ready.

    Returns:
        {"ok": True, "ready_count": N} if reached
        {"ok": False, "reason": "timeout|rate_limit|policy_fail", "ready_count": N}
    """
    start = time.time() * 1000
    last_ready = 0
    while (time.time() * 1000 - start) < timeout_ms:
        try:
            masonry = page.locator(SEL.MASONRY_PREFIX).last
            ready_count = await masonry.locator("img.opacity-1").count()
        except Exception:
            await asyncio.sleep(0.5)
            continue

        if ready_count != last_ready:
            logger.debug(f"wait_image_ready: ready={ready_count}/{target_count}")
            last_ready = ready_count

        if ready_count >= target_count:
            return {"ok": True, "ready_count": ready_count}

        err = await detect_error(page)
        if err:
            return {"ok": False, "ready_count": ready_count, **err}

        await asyncio.sleep(1)
    return {"ok": False, "reason": "timeout", "ready_count": last_ready}


async def submit_and_wait_ready(
    page: Page,
    target_count: int = 4,
    timeout_ms: int = 60000,
) -> dict[str, Any]:
    """Submit prompt and wait for target_count ready listitems in the NEW masonry.

    Ready = listitem has no <canvas> child. Canvas overlay = still generating;
    img.opacity-1 alone is unreliable (appears on low-res placeholder too).

    Tracks masonry by index (initial count) to avoid race conditions with
    .last selector when multiple sections exist.
    """
    try:
        initial_sections = await page.locator(SEL.MASONRY_PREFIX).count()
    except Exception as e:
        return {"ok": False, "reason": f"count masonry sections: {e}"}

    try:
        await page.locator(SEL.SUBMIT).first.click()
    except Exception as e:
        return {"ok": False, "reason": f"submit click: {e}"}

    logger.info(f"Submitted. Waiting for masonry #{initial_sections}...")

    start = time.time() * 1000
    last_ready = 0

    while (time.time() * 1000 - start) < timeout_ms:
        try:
            current = await page.locator(SEL.MASONRY_PREFIX).count()
        except Exception:
            await asyncio.sleep(0.5)
            continue

        if current <= initial_sections:
            err = await detect_error(page)
            if err:
                return {"ok": False, "ready_count": 0, **err}
            await asyncio.sleep(0.5)
            continue

        new_masonry = page.locator(SEL.MASONRY_PREFIX).nth(initial_sections)
        listitems = new_masonry.locator('[role="listitem"]')

        try:
            total = await listitems.count()
        except Exception:
            await asyncio.sleep(0.5)
            continue

        ready = 0
        for i in range(total):
            try:
                has_canvas = await listitems.nth(i).locator("canvas").count()
                if has_canvas == 0:
                    ready += 1
            except Exception:
                pass

        if ready != last_ready:
            logger.debug(
                f"Masonry #{initial_sections}: {ready}/{total} ready (no canvas)"
            )
            last_ready = ready

        if ready >= target_count:
            logger.info(
                f"Masonry #{initial_sections} ready: {ready}/{target_count}"
            )
            return {
                "ok": True,
                "ready_count": ready,
                "masonry_index": initial_sections,
            }

        err = await detect_error(page)
        if err:
            return {"ok": False, "ready_count": ready, **err}

        await asyncio.sleep(1)

    return {"ok": False, "reason": "timeout", "ready_count": last_ready}


async def click_image(
    page: Page,
    idx: int,
    masonry_index: int | None = None,
) -> dict[str, Any]:
    """Click the Nth ready (no-canvas) listitem in the target masonry.

    `idx` indexes into the filtered list of ready listitems, not the raw list.
    Falls back to ready[0] if idx is out of range.
    """
    try:
        if masonry_index is not None:
            masonry = page.locator(SEL.MASONRY_PREFIX).nth(masonry_index)
        else:
            masonry = page.locator(SEL.MASONRY_PREFIX).last

        listitems = masonry.locator('[role="listitem"]')
        total = await listitems.count()

        ready_indices: list[int] = []
        for i in range(total):
            has_canvas = await listitems.nth(i).locator("canvas").count()
            if has_canvas == 0:
                ready_indices.append(i)

        if not ready_indices:
            return {
                "ok": False,
                "reason": "no ready listitem (all still have canvas overlay)",
            }

        if idx < 0 or idx >= len(ready_indices):
            logger.warning(
                f"click_image: idx {idx} out of range ({len(ready_indices)} ready), fallback to 0"
            )
            idx = 0

        real_idx = ready_indices[idx]
        target_img = listitems.nth(real_idx).locator("img.opacity-1").first
        await target_img.click()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"click_image: {e}"}


async def click_back(page: Page) -> dict[str, Any]:
    try:
        await page.locator(SEL.BACK).first.click()
        await page.wait_for_url(re.compile(r".*/imagine(?!/post)"), timeout=10000)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "reason": f"click_back: {e}"}


# ---------- Download ----------

async def download(
    page: Page,
    output_dir: Path,
    project: str,
    prefix: str,
    counter: int,
) -> dict[str, Any]:
    logger.info(f">>> Download start for prompt #{counter}")
    try:
        btn = page.locator(SEL.DOWNLOAD)
        btn_count = await btn.count()
        logger.debug(f"Found {btn_count} Download button(s) at {page.url}")

        if btn_count == 0:
            return {
                "ok": False,
                "reason": (
                    f"download button not found at {page.url}; "
                    "media may not have rendered yet"
                ),
            }

        async with page.expect_download(timeout=60000) as dl_info:
            await btn.first.click()
            logger.debug("Download button clicked")
        dl = await dl_info.value
        suggested = dl.suggested_filename or "out.bin"
        logger.info(f"Download triggered: {suggested}")

        ext = suggested.split(".")[-1] if "." in suggested else "bin"
        target_dir = output_dir / project
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{project}_{prefix}{counter}.{ext}"
        await dl.save_as(str(target))

        if target.exists():
            size_kb = target.stat().st_size / 1024
            logger.info(f"<<< Saved: {target} ({size_kb:.1f} KB)")
            return {"ok": True, "path": str(target)}
        logger.error(f"File not found after save: {target}")
        return {"ok": False, "reason": "file_not_saved"}
    except Exception as e:
        return {"ok": False, "reason": f"download: {e}"}


# ---------- Candidates debug log ----------

def _candidates_dir(output_dir: Path, project: str, counter: int) -> Path:
    d = Path(output_dir) / project / "candidates" / f"{counter:04d}"
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_candidates_log(
    page: Page,
    output_dir: Path,
    project: str,
    counter: int,
    prompt_text: str,
    masonry_index: int,
    target_count: int,
    pick_mode: str,
) -> dict[str, Any]:
    """Save debug log for current prompt's candidates.

    Output: output/{project}/candidates/{counter:04d}/
        strip.png        viewport screenshot
        0.png .. N.png   per-listitem element screenshots (only ready ones)
        prompt.txt       original prompt
        meta.json        counter/target_count/masonry_index/timestamp/pick_mode
    """
    cdir = _candidates_dir(output_dir, project, counter)

    strip_path = cdir / "strip.png"
    try:
        await page.screenshot(path=str(strip_path))
    except Exception as e:
        logger.warning(f"strip screenshot failed: {e}")

    masonry = page.locator(SEL.MASONRY_PREFIX).nth(masonry_index)
    listitems = masonry.locator('[role="listitem"]')

    try:
        total = await listitems.count()
    except Exception:
        total = 0

    saved = 0
    for i in range(min(total, target_count)):
        try:
            has_canvas = await listitems.nth(i).locator("canvas").count()
            if has_canvas:
                continue
            img = listitems.nth(i).locator("img.opacity-1").first
            img_bytes = await img.screenshot()
            (cdir / f"{i}.png").write_bytes(img_bytes)
            saved += 1
        except Exception as e:
            logger.warning(f"candidate {i} screenshot failed: {e}")

    try:
        (cdir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    except Exception as e:
        logger.warning(f"prompt.txt write failed: {e}")

    meta = {
        "counter": counter,
        "prompt": prompt_text,
        "target_count": target_count,
        "masonry_index": masonry_index,
        "saved_candidates": saved,
        "pick_mode": pick_mode,
        "timestamp": datetime.now().isoformat(),
    }
    (cdir / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info(f"Saved {saved} candidates to {cdir}")
    return {"ok": True, "saved": saved, "dir": str(cdir)}


# ---------- Pick ----------

async def pick_image_auto() -> int:
    return 0


async def pick_image(
    config: dict[str, Any],
    output_dir: Path | None = None,
    project: str | None = None,
    counter: int | None = None,
) -> int:
    """Dispatch by pick_mode and ALWAYS write pick.json next to candidates log.

    auto   → 0 (first image)
    claude → TODO: Implement claude_picker.py in separate batch — not Phase 2 scope.
             Falls back to 0 with warning.
    """
    mode = (config.get("pick_mode") or "auto").lower()

    if mode == "auto":
        choice = 0
        pick_data = {
            "choice": 0,
            "mode": "auto",
            "reason": "First image (auto mode)",
        }
    elif mode == "claude":
        logger.warning(
            "pick_mode='claude' not implemented yet — falling back to index 0"
        )
        choice = 0
        pick_data = {
            "choice": 0,
            "mode": "claude_fallback",
            "reason": "Claude picker not implemented (TODO)",
        }
    else:
        choice = 0
        pick_data = {
            "choice": 0,
            "mode": "unknown",
            "reason": f"Unknown pick_mode: {mode}",
        }

    pick_data["timestamp"] = datetime.now().isoformat()

    if output_dir and project and counter is not None:
        try:
            cdir = _candidates_dir(output_dir, project, counter)
            (cdir / "pick.json").write_text(
                json.dumps(pick_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                f"Pick #{counter}: choice={choice} ({pick_data['mode']})"
            )
        except Exception as e:
            logger.warning(f"pick.json write failed: {e}")

    return choice


# ---------- Upload (image-to-image / image-to-video) ----------

async def _wait_upload_preview_ready(page: Page, timeout_ms: int = 60000) -> bool:
    """Wait for upload preview thumbnail to render in prompt bar.

    Strategy:
    1. Wait for popup ("Upload or drop images" button) to close — means file
       was accepted by the dialog.
    2. Poll for a preview <img> element appearing in query-bar area.
    """
    start = time.time()

    while (time.time() - start) * 1000 < 5000:
        try:
            popup_visible = await page.locator(
                'button:has-text("Upload or drop images")'
            ).count()
        except Exception:
            popup_visible = 0
        if popup_visible == 0:
            logger.debug("Upload popup closed")
            break
        await asyncio.sleep(0.5)

    selectors = [
        '.query-bar img',
        '[class*="query-bar"] img',
        'form img:not([alt="Generated image"])',
        '.query-bar [class*="preview"]',
    ]
    while (time.time() - start) * 1000 < timeout_ms:
        for sel in selectors:
            try:
                count = await page.locator(sel).count()
            except Exception:
                count = 0
            if count > 0:
                logger.info(f"Upload preview detected via selector: {sel}")
                await asyncio.sleep(1.0)
                return True
        await asyncio.sleep(1)

    return False


async def upload_ref_if_present(
    page: Page,
    value: str | None,
    ref_cache: dict[str, Path] | None = None,
) -> dict[str, Any]:
    """Upload ref image if `value` is set. Skip silently if None/empty.

    Grok's upload flow:
    1. Click button[aria-label="Upload"] → opens HTML popup dialog.
    2. Set file directly on hidden <input type="file"> in popup
       (bypasses 2nd button + OS file picker).
    3. Wait for upload preview to render (can take 5-30s in video mode).
    """
    if not value:
        return {"ok": True, "skipped": True}

    cache = ref_cache or {}
    full_path = cache.get(value)
    if not full_path:
        return {"ok": False, "reason": f"ref '{value}' not in cache"}

    try:
        logger.info(f"Uploading ref: {full_path}")

        upload_btn = page.locator(SEL.UPLOAD).first
        await upload_btn.wait_for(state="visible", timeout=10000)
        await upload_btn.click()

        await asyncio.sleep(0.5)

        input_count = await page.locator('input[type="file"]').count()
        if input_count == 0:
            return {
                "ok": False,
                "reason": "no <input type='file'> found after Upload click",
            }

        logger.debug(f"Found {input_count} file input(s), using first")

        file_input = page.locator('input[type="file"]').first
        await file_input.set_input_files(str(full_path))

        logger.info("Waiting for upload preview to render...")
        preview_ok = await _wait_upload_preview_ready(page, timeout_ms=60000)
        if not preview_ok:
            logger.warning("Preview detection failed, using fixed 15s sleep")
            await asyncio.sleep(15.0)

        logger.info(f"Ref uploaded: {value}")
        return {"ok": True, "path": str(full_path)}
    except Exception as e:
        return {"ok": False, "reason": f"upload_ref: {e}"}


# ---------- Video settings ----------

async def _click_radio_in_group(page: Page, group_selector: str, label: str) -> dict[str, Any]:
    try:
        group = page.locator(group_selector)
        await group.wait_for(state="visible", timeout=10000)
        radios = group.locator('button[role="radio"]')
        n = await radios.count()
        for i in range(n):
            r = radios.nth(i)
            text = (await r.text_content() or "").strip().lower()
            if text == label.lower():
                checked = (await r.get_attribute("aria-checked")) or ""
                if checked == "true":
                    return {"ok": True, "already": True}
                await r.click()
                await asyncio.sleep(0.3)
                return {"ok": True}
        return {"ok": False, "reason": f"'{label}' not found in {group_selector}"}
    except Exception as e:
        return {"ok": False, "reason": f"radio click: {e}"}


async def set_video_resolution(page: Page, value: str) -> dict[str, Any]:
    return await _click_radio_in_group(page, SEL.VIDEO_RES_GROUP, value)


async def set_video_duration(page: Page, value: str) -> dict[str, Any]:
    return await _click_radio_in_group(page, SEL.VIDEO_DUR_GROUP, value)


# ---------- Video generation polling ----------

async def wait_video_ready(
    page: Page,
    initial_wait_s: int = 20,
    timeout_ms: int = 300000,
) -> dict[str, Any]:
    """Wait for video: fixed initial sleep + poll until done.

    Sleeps `initial_wait_s` first (Grok needs ~10-15s after submit before
    overlay renders). Then polls for "Generating X%" overlay disappearance
    AND positive ready signal `<video id="sd-video">`.
    """
    pattern = re.compile(r"Generating\s+\d+%")
    pct_pattern = re.compile(r"(\d+)%")

    logger.info(f"Waiting fixed {initial_wait_s}s for overlay to appear...")
    await asyncio.sleep(initial_wait_s)

    logger.info("Polling for video completion...")
    start = time.time()
    last_pct = -1

    while (time.time() - start) * 1000 < timeout_ms:
        try:
            overlays = page.locator("div").filter(has_text=pattern)
            count = await overlays.count()
        except Exception:
            count = -1

        if count == 0:
            try:
                video_count = await page.locator("#sd-video").count()
            except Exception:
                video_count = 0
            if video_count > 0:
                logger.info("Video ready (sd-video element present)")
                await asyncio.sleep(1.0)
                return {"ok": True}
            else:
                logger.debug("Overlay gone but no <video> yet, keep polling")

        if count > 0:
            try:
                text = await overlays.first.text_content()
                m = pct_pattern.search(text or "")
                if m:
                    pct = int(m.group(1))
                    if pct != last_pct:
                        logger.info(f"Video progress: {pct}%")
                        last_pct = pct
            except Exception:
                pass

        err = await detect_error(page)
        if err:
            return {"ok": False, "last_progress": last_pct, **err}

        await asyncio.sleep(2)

    return {"ok": False, "reason": "gen_timeout", "last_progress": last_pct}


# ---------- Error detection ----------

async def detect_error(page: Page) -> dict[str, Any] | None:
    try:
        toasts = page.locator(SEL.TOAST)
        n = await toasts.count()
        for i in range(n):
            text = (await toasts.nth(i).text_content() or "").lower()
            if any(k in text for k in ("rate limit", "too many", "quota", "slow down")):
                return {"type": "rate_limit", "msg": text, "reason": "rate_limit"}
            if any(k in text for k in ("violat", "policy", "inappropriate", "not allowed", "blocked")):
                return {"type": "policy_fail", "msg": text, "reason": "policy_fail"}
    except Exception:
        pass
    return None
