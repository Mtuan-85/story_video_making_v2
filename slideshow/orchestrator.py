"""Orchestrator: main entry point for slideshow v2 rendering.

Synchronous pipeline: BG detect → Claude auto-pick → refine → render.
No threading, no cancellation. Single function call from main app.

Workflow files:
  - cache_dir (default sources/edit/.cache/{scene_id}/) — ephemeral, deleted on success
  - zones_json_path (default sources/edit/{scene_id}-zones.json) — persistent
  - thumb_path (default sources/edit/{scene_id}-thumb.png) — persistent
  - output_path (mp4) — overwrites existing
"""

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

# Ensure slideshow is in sys.path for imports to work
_slideshow_dir = Path(__file__).resolve().parent
if str(_slideshow_dir) not in sys.path:
    sys.path.insert(0, str(_slideshow_dir))

# Bundled sound effects shipped with the engine. Each zone's `sound` value
# (pop/flip/whoosh/swoosh/ding) resolves to a .wav under this directory.
# Caller may override by passing sounds_dir explicitly.
_DEFAULT_SOUNDS_DIR = _slideshow_dir / "assets" / "sounds"

# Import modules
try:
    from bg_detect import detect_bg_color
    from claude_runner import run_auto_pick
    from zone_refiner import refine_polygon_from_bbox, resolve_overlaps
    from renderer import render_slideshow_video
except ImportError as e:
    raise RuntimeError(f"Failed to import slideshow modules: {e}") from e


def render_slideshow_v2(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str = "16:9",
    hint: str = "",
    bg_method: str = "auto",
    sounds_dir: Optional[Path] = None,
    log_cb: Optional[Callable] = None,
    zones_json_path: Optional[Path] = None,
    thumb_path: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    keep_cache: bool = False,
) -> Path:
    """Render slideshow from scratch (full pipeline with Claude).

    Args:
        image_path: Source image (PNG/JPG)
        output_path: Output MP4 path (overwrite OK)
        duration_sec: Total video duration in seconds
        aspect_ratio: "16:9" (youtube) or "9:16" (tiktok)
        hint: User guidance string
        bg_method: ignored, kept for API compat
        sounds_dir: Path to sounds folder
        log_cb: Progress callback
        zones_json_path: Where to save zones JSON (default: next to output)
        thumb_path: Where to save thumbnail with polygon overlay (default: next to output)
        cache_dir: Working dir for Claude logs + frames (default: next to output)
        keep_cache: If True, keep cache_dir even on success (debug)

    Returns:
        Path to rendered MP4 file
    """
    if log_cb is None:
        log_cb = print

    image_path = Path(image_path)
    output_path = Path(output_path)

    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Resolve default paths if not provided (fall back to next to output_path)
    if zones_json_path is None:
        zones_json_path = output_path.parent / f"{output_path.stem}-zones.json"
    if thumb_path is None:
        thumb_path = output_path.parent / f"{output_path.stem}-thumb.png"
    if cache_dir is None:
        cache_dir = output_path.parent / f".{output_path.stem}-cache"
    if sounds_dir is None and _DEFAULT_SOUNDS_DIR.exists():
        sounds_dir = _DEFAULT_SOUNDS_DIR

    zones_json_path = Path(zones_json_path)
    thumb_path = Path(thumb_path)
    cache_dir = Path(cache_dir)

    zones_json_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    log_cb(f"🎬 Slideshow v2 — {image_path.name} → {output_path.name}")
    log_cb(f"   Duration: {duration_sec}s, Aspect: {aspect_ratio}")
    log_cb(f"   Cache: {cache_dir}")
    log_cb(f"   Zones JSON: {zones_json_path}")
    t_pipeline = time.monotonic()

    success = False
    try:
        # Step 1: Detect background color
        log_cb("\n📍 Step 1: Detect background color...")
        t_step1 = time.monotonic()
        bg_color = detect_bg_color(image_path)
        log_cb(f"   BG: RGB{bg_color} ({time.monotonic()-t_step1:.2f}s)")

        # Load image
        log_cb("   Loading source image into memory...")
        t_load = time.monotonic()
        with Image.open(image_path) as img:
            source_img = img.convert("RGB")
            image_size = source_img.size
            source_array = np.array(source_img)
        log_cb(f"   Image loaded: {image_size[0]}x{image_size[1]} ({time.monotonic()-t_load:.2f}s)")

        # Step 2: Call Claude to pick zones
        log_cb("\n🤖 Step 2: Claude auto-pick zones (vision)...")
        t_step2 = time.monotonic()

        try:
            plan = run_auto_pick(
                image_path=image_path,
                image_size=image_size,
                bg_color=bg_color,
                duration=duration_sec,
                free_hint=hint,
                work_dir=cache_dir,
                log_cb=log_cb,
            )
        except Exception as e:
            raise RuntimeError(f"Claude auto-pick failed: {e}") from e
        log_cb(f"   Step 2 done in {time.monotonic()-t_step2:.2f}s")

        zones = plan.get("zones", [])
        log_cb(f"   → {len(zones)} zones picked")

        # Step 3: Refine bboxes to tight polygons
        log_cb("\n✏️  Step 3: Refine polygons (chroma-key + CV)...")
        zones_refined = []
        failed_zones = []

        t_step3 = time.monotonic()
        for idx, zone_dict in enumerate(zones, start=1):
            zone_dict["zone_id"] = idx
            zone_label = zone_dict.get("label", f"zone_{idx}")
            bbox = zone_dict.get("bbox", [])

            log_cb(f"   → [{idx}/{len(zones)}] zone #{idx} ({zone_label}) starting...")
            t_zone = time.monotonic()

            if not bbox or len(bbox) != 4:
                log_cb(f"   SKIP zone #{idx} ({zone_label}): invalid bbox")
                failed_zones.append(idx)
                continue

            try:
                polygon = refine_polygon_from_bbox(
                    source_array=source_array,
                    bbox=bbox,
                    bg_color=bg_color,
                    log_cb=log_cb,
                    zone_label=zone_label,
                )
                zone_dict["polygon"] = polygon
                zones_refined.append(zone_dict)
                elapsed = time.monotonic() - t_zone
                log_cb(f"   ✓ zone #{idx} ({zone_label}): {len(polygon)} vertices ({elapsed:.2f}s)")
            except Exception as e:
                elapsed = time.monotonic() - t_zone
                log_cb(f"   SKIP zone #{idx} ({zone_label}) ({elapsed:.2f}s): {e}")
                failed_zones.append(idx)

        log_cb(f"   Step 3 done in {time.monotonic()-t_step3:.2f}s")

        if not zones_refined:
            raise RuntimeError(
                "All zones failed refinement. Check image contrast/colors."
            )

        if failed_zones:
            log_cb(f"   ⚠️  {len(failed_zones)} zone(s) failed, continuing with {len(zones_refined)}")

        # Step 4: Resolve overlaps
        log_cb("\n🔄 Step 4: Resolve overlaps...")
        t_step4 = time.monotonic()
        try:
            polygons = [z.get("polygon", []) for z in zones_refined]
            refined_polygons = resolve_overlaps(polygons, image_size, log_cb=log_cb)
            for z, poly in zip(zones_refined, refined_polygons):
                z["polygon"] = poly
            log_cb(f"   ✓ {len(zones_refined)} zones finalized ({time.monotonic()-t_step4:.2f}s)")
        except Exception as e:
            log_cb(f"   WARN: overlap resolution failed ({time.monotonic()-t_step4:.2f}s), continuing: {e}")

        # Step 5: Render video
        log_cb("\n🎥 Step 5: Render video (M1 pipeline)...")
        t_step5 = time.monotonic()
        try:
            result = render_slideshow_video(
                image_path=image_path,
                output_path=output_path,
                zones_with_plans=zones_refined,
                duration_sec=duration_sec,
                bg_color=bg_color,
                aspect_ratio=aspect_ratio,
                sounds_dir=sounds_dir,
                log_cb=log_cb,
            )
        except Exception as e:
            raise RuntimeError(f"Render failed: {e}") from e
        log_cb(f"   Step 5 done in {time.monotonic()-t_step5:.2f}s")

        # Step 6: Save persistent artefacts (zones JSON + thumbnail)
        log_cb("\n💾 Step 6: Save zones JSON + thumbnail...")
        t_step6 = time.monotonic()
        _save_zones_json(
            zones_refined,
            image_path,
            image_size,
            bg_color,
            duration_sec,
            aspect_ratio,
            hint,
            zones_json_path,
        )
        log_cb(f"   ✓ Zones saved: {zones_json_path.name}")
        try:
            _render_thumbnail(source_img, zones_refined, thumb_path)
            log_cb(f"   ✓ Thumb saved: {thumb_path.name}")
        except Exception as e:
            log_cb(f"   WARN: thumbnail render failed: {e}")
        log_cb(f"   Step 6 done in {time.monotonic()-t_step6:.2f}s")

        success = True
        log_cb(f"\n✅ DONE: {result} (total pipeline: {time.monotonic()-t_pipeline:.2f}s)")
        return result

    finally:
        # Cleanup cache_dir on success (unless keep_cache=True)
        if success and not keep_cache:
            try:
                if cache_dir.exists():
                    shutil.rmtree(cache_dir, ignore_errors=True)
                    log_cb(f"   Cache cleaned: {cache_dir.name}")
            except Exception as e:
                log_cb(f"   WARN: cache cleanup failed: {e}")
        elif not success:
            log_cb(f"   Cache preserved for debug: {cache_dir}")


# ============================================================
# Re-render (skip Claude — uses saved zones JSON)
# ============================================================

def rerender_slideshow_v2(
    zones_json_path: Path,
    output_path: Path,
    sounds_dir: Optional[Path] = None,
    log_cb: Optional[Callable] = None,
    thumb_path: Optional[Path] = None,
    image_path_override: Optional[Path] = None,
    duration_override: Optional[float] = None,
    aspect_ratio_override: Optional[str] = None,
    cache_dir: Optional[Path] = None,
    keep_cache: bool = False,
) -> Path:
    """Re-render slideshow from saved zones JSON (NO Claude call).

    Use this when user has edited polygons / animation / timing and wants
    to render again. The full pipeline is skipped — only Step 5 (render)
    runs, using the polygons + plans from zones_json_path.

    Args:
        zones_json_path: Path to saved zones JSON (from prev render_slideshow_v2 run)
        output_path: Output MP4 path (overwrite OK)
        sounds_dir: Sounds folder
        log_cb: Progress callback
        thumb_path: Where to refresh thumbnail (default: next to zones_json)
        image_path_override: Override source image path (else use saved in JSON)
        duration_override: Override duration (else use saved in JSON)
        aspect_ratio_override: Override aspect ratio (else use saved in JSON)
        cache_dir: Working dir for frames (default: next to output)
        keep_cache: Keep frames after render (debug)

    Returns:
        Path to rendered MP4
    """
    if log_cb is None:
        log_cb = print

    zones_json_path = Path(zones_json_path)
    output_path = Path(output_path)

    if not zones_json_path.exists():
        raise FileNotFoundError(f"Zones JSON not found: {zones_json_path}")

    log_cb(f"🔄 Slideshow v2 — Re-render (skip Claude)")
    log_cb(f"   Zones JSON: {zones_json_path.name}")
    log_cb(f"   Output: {output_path}")
    t_pipeline = time.monotonic()

    # Load zones JSON
    with zones_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    image_path = Path(image_path_override or data["image_path"])
    duration_sec = float(duration_override if duration_override is not None else data.get("duration", 8.0))
    aspect_ratio = aspect_ratio_override or data.get("aspect_ratio", "16:9")
    bg_color = tuple(data.get("bg_color", (255, 255, 255)))
    hint = data.get("hint", "")
    zones = data.get("zones", [])

    if not image_path.exists():
        raise FileNotFoundError(f"Source image not found: {image_path}")
    if not zones:
        raise RuntimeError("No zones in saved JSON")

    log_cb(f"   Image: {image_path.name}")
    log_cb(f"   Duration: {duration_sec}s, Aspect: {aspect_ratio}")
    log_cb(f"   BG: RGB{bg_color}")
    log_cb(f"   Zones: {len(zones)} (skip Claude + refine + overlap)")

    if cache_dir is None:
        cache_dir = output_path.parent / f".{output_path.stem}-cache"
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    if thumb_path is None:
        thumb_path = zones_json_path.parent / zones_json_path.name.replace("-zones.json", "-thumb.png")
    thumb_path = Path(thumb_path)

    if sounds_dir is None and _DEFAULT_SOUNDS_DIR.exists():
        sounds_dir = _DEFAULT_SOUNDS_DIR

    success = False
    try:
        # Render only
        log_cb("\n🎥 Render video...")
        t_render = time.monotonic()
        result = render_slideshow_video(
            image_path=image_path,
            output_path=output_path,
            zones_with_plans=zones,
            duration_sec=duration_sec,
            bg_color=bg_color,
            aspect_ratio=aspect_ratio,
            sounds_dir=sounds_dir,
            log_cb=log_cb,
        )
        log_cb(f"   Render done in {time.monotonic()-t_render:.2f}s")

        # Update saved data (duration / aspect_ratio may have changed)
        data["duration"] = duration_sec
        data["aspect_ratio"] = aspect_ratio
        with zones_json_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # Refresh thumbnail
        try:
            with Image.open(image_path) as img:
                source_img = img.convert("RGB")
            _render_thumbnail(source_img, zones, thumb_path)
            log_cb(f"   ✓ Thumb refreshed: {thumb_path.name}")
        except Exception as e:
            log_cb(f"   WARN: thumbnail render failed: {e}")

        success = True
        log_cb(f"\n✅ Re-render DONE: {result} ({time.monotonic()-t_pipeline:.2f}s)")
        return result

    finally:
        if success and not keep_cache:
            try:
                if cache_dir.exists():
                    shutil.rmtree(cache_dir, ignore_errors=True)
            except Exception:
                pass


# ============================================================
# Helpers
# ============================================================

def _save_zones_json(
    zones: List[dict],
    image_path: Path,
    image_size: Tuple[int, int],
    bg_color: Tuple[int, int, int],
    duration_sec: float,
    aspect_ratio: str,
    hint: str,
    target: Path,
) -> None:
    """Save zones state to JSON for later re-edit / re-render.

    Includes everything needed to re-render without Claude:
      - image_path (absolute, for portability use str)
      - image_size
      - bg_color
      - duration + aspect_ratio + hint
      - zones[] with polygon + animation + emphasis + sound + timing + label
    """
    # Sanitize zones — only keep fields needed for re-render
    clean_zones = []
    for z in zones:
        clean_zones.append({
            "zone_id": int(z.get("zone_id", 0)),
            "label": str(z.get("label", "")),
            "polygon": [[int(p[0]), int(p[1])] for p in z.get("polygon", [])],
            "animation": str(z.get("animation", "fade_in")),
            "emphasis": str(z.get("emphasis", "none")),
            "sound": str(z.get("sound", "ding")),
            "appear_at": float(z.get("appear_at", 0.0)),
            "end_at": float(z.get("end_at", 0.5)),
            "rationale": str(z.get("rationale", "")),
        })

    data = {
        "version": 1,
        "image_path": str(image_path).replace("\\", "/"),
        "image_size": list(image_size),
        "bg_color": list(bg_color),
        "duration": duration_sec,
        "aspect_ratio": aspect_ratio,
        "hint": hint,
        "zones": clean_zones,
    }

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)


def _render_thumbnail(
    source_img: Image.Image,
    zones: List[dict],
    target: Path,
    max_dim: int = 480,
) -> None:
    """Render preview thumbnail with semi-transparent polygon overlay.

    Each zone gets a distinct color (golden-angle HSV cycle).
    Output is a downscaled PNG saved to target.
    """
    import colorsys

    # Downscale source
    w, h = source_img.size
    scale = min(1.0, max_dim / max(w, h))
    if scale < 1.0:
        new_size = (int(w * scale), int(h * scale))
        thumb = source_img.resize(new_size, Image.LANCZOS).convert("RGBA")
    else:
        thumb = source_img.copy().convert("RGBA")
        scale = 1.0

    # Overlay polygons with semi-transparent fill
    overlay = Image.new("RGBA", thumb.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for idx, zone_dict in enumerate(zones):
        polygon = zone_dict.get("polygon", [])
        if len(polygon) < 3:
            continue
        scaled_poly = [(int(p[0] * scale), int(p[1] * scale)) for p in polygon]

        # Golden-angle hue
        hue = ((idx * 137.5) % 360) / 360.0
        r, g, b = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
        color = (int(r * 255), int(g * 255), int(b * 255), 100)  # semi-transparent

        draw.polygon(scaled_poly, fill=color, outline=color[:3] + (200,))

    result = Image.alpha_composite(thumb, overlay).convert("RGB")
    target.parent.mkdir(parents=True, exist_ok=True)
    result.save(target, "PNG")
