"""Async wrapper around the existing slideshow pipeline.

slideshow is the proven prototype (chroma key + rembg + horizontal dilate +
Claude Code animation director + ffmpeg filter_complex). This wrapper:

  1. Copies the input image into a temp work folder (slideshow expects a
     folder layout — scene.png + .cache/ + movie/).
  2. Calls the sync pipeline (preprocess → claude → render) in a thread.
  3. Moves the resulting movie/final.mp4 to the caller-specified output_path.

Per SPEC §3, slideshow lives at the project root (already in place) and
must NOT be modified — we adapt around it via sys.path injection.
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Callable

from loguru import logger as log

SLIDESHOW_DIR = Path(__file__).resolve().parent.parent / "slideshow"

# Aspect → slideshow preset name (PRESETS in slideshow/renderer.py).
PRESET_BY_ASPECT = {
    "16:9": "youtube",
    "9:16": "tiktok",
}


def _import_slideshow_modules():
    """Lazy-import slideshow with its directory on sys.path.

    slideshow uses bare imports (`from preprocess import ...`); we patch
    sys.path inside this function so the rest of the app keeps a clean
    namespace.
    """
    if not SLIDESHOW_DIR.exists():
        raise RuntimeError(f"slideshow không tồn tại: {SLIDESHOW_DIR}")
    s = str(SLIDESHOW_DIR)
    if s not in sys.path:
        sys.path.insert(0, s)
    import preprocess  # noqa: E402
    import claude_runner  # noqa: E402
    import renderer  # noqa: E402
    return preprocess, claude_runner, renderer


def _run_pipeline_sync(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,
    hint: str,
    bg_method: str,
    log_fn: Callable[[str], None],
) -> Path:
    """Sync core — runs in a worker thread.

    Each step is wrapped with ENTER/EXIT logs so the file sink in `main.py`
    pinpoints exactly where the process dies if a native lib (cv2 / rembg /
    ffmpeg) segfaults — at that point Python can't raise, but the last
    "ENTER <step>" line in app.log tells you which call took the process down.
    """
    log.info(
        f"slideshow ENTER pipeline | image={image_path} duration={duration_sec}s "
        f"aspect={aspect_ratio} bg_method={bg_method}"
    )
    preprocess, claude_runner, renderer = _import_slideshow_modules()
    log.debug("slideshow modules imported")

    if aspect_ratio not in PRESET_BY_ASPECT:
        raise ValueError(f"aspect_ratio không hỗ trợ: {aspect_ratio}")
    preset_name = PRESET_BY_ASPECT[aspect_ratio]
    preset = renderer.PRESETS[preset_name]

    image_path = Path(image_path)
    output_path = Path(output_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Ảnh scene không tồn tại: {image_path}")
    try:
        size_mb = image_path.stat().st_size / 1_048_576
        log.info(f"slideshow source image: {image_path} ({size_mb:.2f} MB)")
    except OSError:
        pass
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a private workspace per call: slideshow expects folder layout.
    # Use a named temp dir so the .cache survives if the caller wants to inspect.
    work_dir = Path(tempfile.mkdtemp(prefix="slideshow_"))
    log_fn(f"workspace: {work_dir}")
    log.debug(f"slideshow workspace: {work_dir}")

    # Copy the source image into work_dir so slideshow.find_scene_image picks it up.
    scene_path = work_dir / image_path.name
    shutil.copy2(image_path, scene_path)

    cache_dir = work_dir / ".cache"
    processed_dir = cache_dir / "processed"

    try:
        log_fn("🎨 Preprocess (bg removal + tách objects)...")
        log.info("slideshow ENTER preprocess.preprocess_scene")
        try:
            metadata = preprocess.preprocess_scene(
                scene_path=scene_path,
                cache_dir=cache_dir,
                bg_method=bg_method,
                log_fn=lambda m: (log.debug(f"preprocess: {m}"), log_fn(f"   {m}"))[-1],
            )
        except BaseException:
            log.exception("slideshow FAILED in preprocess.preprocess_scene")
            raise
        log.info(f"slideshow EXIT preprocess — {len(metadata['objects'])} objects")
        log_fn(f"   → {len(metadata['objects'])} objects")

        log_fn("🎬 Claude design animation...")
        log.info("slideshow ENTER claude_runner.run_claude_analyze")
        try:
            plan = claude_runner.run_claude_analyze(
                folder=work_dir,
                scene_path=scene_path,
                processed_dir=processed_dir,
                duration=int(round(duration_sec)),
                canvas_w=preset["width"],
                canvas_h=preset["height"],
                hint=hint or "",
            )
        except BaseException:
            log.exception("slideshow FAILED in claude_runner.run_claude_analyze")
            raise
        log.info(f"slideshow EXIT claude — {len(plan.get('scenes', []))} scenes")

        available = [obj["filename"] for obj in metadata["objects"]]
        try:
            claude_runner.validate_plan(plan, available, int(round(duration_sec)), min_scenes=3)
        except BaseException:
            log.exception(f"slideshow FAILED validate_plan | plan={plan!r}")
            raise
        if "duration" not in plan:
            plan["duration"] = duration_sec
        log_fn(f"   → plan có {len(plan['scenes'])} scenes")

        log_fn("🎥 Render ffmpeg filter_complex...")
        log.info("slideshow ENTER renderer.render_video")
        movie_dir = work_dir / "movie"
        intermediate = movie_dir / "final.mp4"
        try:
            renderer.render_video(
                metadata=metadata,
                plan=plan,
                processed_dir=processed_dir,
                output_path=intermediate,
                preset_name=preset_name,
                progress_callback=lambda m: (log.debug(f"ffmpeg: {m}"), log_fn(f"   → {m}"))[-1],
            )
        except BaseException:
            log.exception("slideshow FAILED in renderer.render_video")
            raise
        log.info("slideshow EXIT renderer.render_video")

        if not intermediate.exists():
            raise RuntimeError("Slideshow render không tạo file output")

        # Move into the caller-specified location.
        shutil.move(str(intermediate), str(output_path))
        log_fn(f"✓ Slideshow → {output_path}")
        log.info(f"slideshow DONE → {output_path}")
        return output_path
    finally:
        # Best-effort cleanup; keep cache only on explicit debug.
        try:
            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            log.warning(f"slideshow workspace cleanup failed for {work_dir}", exc_info=True)


async def render_slideshow(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,
    hint: str = "",
    bg_method: str = "auto",
    log_cb: Callable[[str], None] | None = None,
) -> Path:
    """Async wrapper: run slideshow in a worker thread, return output Path.

    Args:
        image_path: scene image (e.g. projects/{name}/sources/picN.jpg).
        output_path: where to write the .mp4 (e.g. sources/vidN.mp4).
        duration_sec: total clip length.
        aspect_ratio: "16:9" → youtube preset, "9:16" → tiktok preset.
        hint: optional natural-language nudge passed to Claude.
        bg_method: "auto" | "chroma" | "rembg" (per slideshow docs).
        log_cb: per-step status callback. Default routes through loguru.
    """
    cb = log_cb or (lambda m: log.info(m))
    return await asyncio.to_thread(
        _run_pipeline_sync,
        Path(image_path),
        Path(output_path),
        duration_sec,
        aspect_ratio,
        hint,
        bg_method,
        cb,
    )
