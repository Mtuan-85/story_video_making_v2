"""Adapter layer: legacy async wrappers around slideshow v2.

⚠️ DEPRECATED for new code.

  - `SlideshowWorker` (workers/slideshow_worker.py) now calls
    `slideshow.render_slideshow_v2` / `rerender_slideshow_v2` DIRECTLY
    inside a fresh QThread, bypassing this async wrapper.
  - These async functions are kept ONLY for legacy callers
    (workers/batch_video.py still imports `render_slideshow`).
  - Do NOT use `asyncio.to_thread` for new slideshow calls: the shared
    qasync thread pool accumulates BLAS / cv2 state across many renders
    and triggered heap corruption (Windows 0xc0000374). Use a fresh
    QThread per call instead (see workers/slideshow_worker.SlideshowWorker).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, Optional

from loguru import logger as log


def _import_slideshow_v2():
    """Import slideshow v2 package (standalone, no zone_animate dependency)."""
    slideshow_dir = Path(__file__).resolve().parent.parent / "slideshow"
    if not slideshow_dir.exists():
        raise RuntimeError(f"slideshow không tồn tại: {slideshow_dir}")

    s = str(slideshow_dir)
    if s not in sys.path:
        sys.path.insert(0, s)

    try:
        from orchestrator import render_slideshow_v2, rerender_slideshow_v2
        return render_slideshow_v2, rerender_slideshow_v2
    except ImportError as e:
        log.error(f"Failed to import slideshow v2: {e}", exc_info=True)
        raise RuntimeError(
            f"Không import được slideshow v2: {e}. "
            f"Kiểm tra slideshow package."
        ) from e


async def render_slideshow(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,
    hint: str = "",
    bg_method: str = "auto",
    log_cb: Callable[[str], None] | None = None,
    zones_json_path: Optional[Path] = None,
    thumb_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
) -> Path:
    """Async wrapper around slideshow v2 full pipeline.

    Saves zones JSON + thumbnail next to output for re-edit.
    Cache dir is cleaned on success unless keep_cache=True.
    """
    import asyncio

    render_slideshow_v2, _ = _import_slideshow_v2()

    cb = log_cb or (lambda m: log.info(m))
    try:
        result = await asyncio.to_thread(
            render_slideshow_v2,
            Path(image_path),
            Path(output_path),
            duration_sec,
            aspect_ratio,
            hint,
            bg_method,
            None,  # sounds_dir
            cb,
            zones_json_path,
            thumb_path,
            cache_dir,
            False,  # keep_cache
        )
        return result
    except Exception as e:
        log.exception("slideshow render failed")
        raise RuntimeError(f"Slideshow render failed: {e}") from e


async def rerender_slideshow(
    zones_json_path: Path,
    output_path: Path,
    log_cb: Callable[[str], None] | None = None,
    thumb_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
) -> Path:
    """Async wrapper for re-render (skip Claude).

    Uses saved zones JSON from a previous render.
    """
    import asyncio

    _, rerender_slideshow_v2 = _import_slideshow_v2()

    cb = log_cb or (lambda m: log.info(m))
    try:
        result = await asyncio.to_thread(
            rerender_slideshow_v2,
            Path(zones_json_path),
            Path(output_path),
            None,                # sounds_dir
            cb,                  # log_cb
            thumb_path,
            None,                # image_path_override
            None,                # duration_override
            None,                # aspect_ratio_override
            cache_dir,
            False,               # keep_cache
        )
        return result
    except Exception as e:
        log.exception("slideshow rerender failed")
        raise RuntimeError(f"Slideshow rerender failed: {e}") from e
