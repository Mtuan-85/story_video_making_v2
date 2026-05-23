"""Renderer: render zone-based animation video (standalone).

Uses PIL for frame composition (M1 render_frame logic) + ffmpeg for encoding.
Supports all 7 animations: fade_in, scale_pop, slide_in_*, drop_in,
pulse, glow, shake.
"""

from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw

from animations import (
    Layer,
    StickerTransform,
    build_animation,
    compose_transforms,
)
from zone_refiner import CHROMA_THRESHOLD as _REFINER_CHROMA_THRESHOLD


PRESETS = {
    "youtube": {"width": 1920, "height": 1080, "fps": 30, "bitrate": "8M"},
    "tiktok": {"width": 1080, "height": 1920, "fps": 30, "bitrate": "6M"},
}

# Map aspect ratio strings to preset names
ASPECT_TO_PRESET = {
    "16:9": "youtube",
    "9:16": "tiktok",
    "youtube": "youtube",
    "tiktok": "tiktok",
}


def _resolve_preset(aspect_ratio: str) -> dict:
    """Resolve aspect ratio string ('16:9', '9:16', 'youtube', 'tiktok') to preset dict."""
    preset_name = ASPECT_TO_PRESET.get(aspect_ratio)
    if preset_name is None:
        raise ValueError(
            f"aspect_ratio không hỗ trợ: {aspect_ratio}. "
            f"Hỗ trợ: {list(ASPECT_TO_PRESET.keys())}"
        )
    return PRESETS[preset_name]


class Sticker:
    """Sticker: RGBA image extracted from a zone polygon, with metadata."""

    def __init__(
        self,
        zone_id: int,
        image: Image.Image,
        position: Tuple[int, int],
        size: Tuple[int, int],
        centroid: Tuple[float, float],
        order: int = 0,
    ):
        self.zone_id = zone_id
        self.image = image
        self.position = position
        self.size = size
        self.centroid = centroid
        self.order = order  # z-order for layering (smaller = bottom)


# ============================================================
# Public API
# ============================================================

def render_slideshow_video(
    image_path: Path,
    output_path: Path,
    zones_with_plans: List[Dict],
    duration_sec: float,
    bg_color: Tuple[int, int, int],
    aspect_ratio: str = "16:9",
    sounds_dir: Optional[Path] = None,
    log_cb: Optional[Callable] = None,
) -> Path:
    """Render zone-based animation video.

    Args:
        image_path: Source image (PNG/JPG)
        output_path: Output MP4 path
        zones_with_plans: List of dicts with 'polygon' and scene plan fields
            (animation, emphasis, sound, appear_at, end_at)
        duration_sec: Total video duration in seconds
        bg_color: (r, g, b) background color
        aspect_ratio: "16:9" or "9:16"
        sounds_dir: Path to sounds directory (assets/sounds/)
        log_cb: Optional progress callback

    Returns:
        Path to rendered video
    """
    if log_cb is None:
        log_cb = print

    preset = _resolve_preset(aspect_ratio)
    canvas_w, canvas_h = preset["width"], preset["height"]
    fps = preset["fps"]
    log_cb(f"  Preset: {canvas_w}x{canvas_h} @ {fps}fps")

    # Load source image (with-context closes file handle immediately)
    log_cb("Loading source image...")
    with Image.open(image_path) as img:
        source_img = img.convert("RGB")
    source_w, source_h = source_img.size
    source_array = np.array(source_img)

    # Build render plan
    log_cb("Building render plan...")
    render_plan = _build_render_plan(
        zones_with_plans, duration_sec, fps, source_w, source_h
    )

    # Build base canvas: source with zones masked
    log_cb("Building base canvas...")
    base_canvas = _make_base_canvas(source_img, zones_with_plans, bg_color)

    # Extract stickers
    log_cb("Extracting zone stickers...")
    stickers = {}
    for idx, zone_dict in enumerate(zones_with_plans):
        zone_id = zone_dict.get("zone_id", zone_dict.get("id", idx + 1))
        polygon = zone_dict.get("polygon", [])
        if len(polygon) < 3:
            log_cb(f"  Skipping zone {zone_id}: invalid polygon")
            continue
        try:
            sticker = _extract_sticker(
                source_array, polygon, zone_id, bg_color, order=idx + 1
            )
            stickers[zone_id] = sticker
        except Exception as e:
            log_cb(f"  WARN: zone {zone_id} extraction failed: {e}")

    if not stickers:
        raise RuntimeError("No stickers extracted. Check zone polygons.")

    # Create frames directory
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = output_path.parent / f".{output_path.stem}_frames"
    frames_dir.mkdir(exist_ok=True)

    try:
        # Render frames using M1 logic
        log_cb("Rendering frames...")
        _render_frames(
            frames_dir=frames_dir,
            canvas_size=(source_w, source_h),
            bg_color=bg_color,
            base_canvas=base_canvas,
            render_plan=render_plan,
            stickers=stickers,
            log_cb=log_cb,
        )

        # Encode video
        log_cb("Encoding video (ffmpeg)...")
        audio_inputs = []
        if sounds_dir:
            audio_inputs = _collect_audio_inputs(render_plan, sounds_dir)

        _encode_video(
            frames_dir=frames_dir,
            audio_inputs=audio_inputs,
            output_path=output_path,
            fps=fps,
            canvas_size=(canvas_w, canvas_h),
            source_size=(source_w, source_h),
            bg_color=bg_color,
        )

        log_cb(f"✓ Slideshow rendered: {output_path}")
        return output_path

    finally:
        import shutil
        if frames_dir.exists():
            shutil.rmtree(frames_dir, ignore_errors=True)


# ============================================================
# Plan + canvas construction
# ============================================================

def _build_render_plan(
    zones_with_plans: List[Dict],
    duration_sec: float,
    fps: int,
    canvas_w: int,
    canvas_h: int,
) -> Dict:
    """Convert zone+plan data to M1 render plan format."""
    scenes = []

    for idx, zone_dict in enumerate(zones_with_plans, start=1):
        zone_id = zone_dict.get("zone_id") or zone_dict.get("id") or idx
        animation = zone_dict.get("animation", "fade_in")
        emphasis = zone_dict.get("emphasis", "none")
        sound = zone_dict.get("sound", "ding")
        appear_at = float(zone_dict.get("appear_at", 0.0))
        end_at = float(zone_dict.get("end_at", appear_at + 0.5))

        # Entry duration: from appear_at to end_at OR default
        # If end_at given, entry = min of (end_at - appear_at, default duration)
        from animations import DEFAULTS
        default_entry_dur = DEFAULTS.get(animation, {}).get("duration", 0.5)

        # If emphasis present, split window: entry first, then emphasis
        if emphasis and emphasis != "none":
            default_emp_dur = DEFAULTS.get(emphasis, {}).get("duration", 0.4)
            emp_delay = 0.2
            # Try to fit both in end_at-appear_at window
            total_window = max(0.5, end_at - appear_at)
            if total_window >= default_entry_dur + emp_delay + default_emp_dur:
                entry_duration = default_entry_dur
                emp_duration = default_emp_dur
            else:
                # Scale down both proportionally
                entry_duration = total_window * 0.5
                emp_duration = total_window * 0.3
        else:
            entry_duration = min(default_entry_dur, max(0.1, end_at - appear_at))
            emp_duration = 0.0

        scene = {
            "zone_id": zone_id,
            "appear_at": appear_at,
            "entry": {
                "type": animation,
                "duration": entry_duration,
                "params": {},
            },
        }
        # Pre-build animation instance once per scene; reused every frame.
        scene["_entry_anim"] = build_animation(animation, {})

        if emphasis and emphasis != "none":
            scene["emphasis"] = {
                "type": emphasis,
                "duration": emp_duration,
                "delay": 0.2,
                "params": {},
            }
            scene["_emphasis_anim"] = build_animation(emphasis, {})

        scene["sound"] = sound
        scenes.append(scene)

    return {
        "duration": duration_sec,
        "fps": fps,
        "canvas": (canvas_w, canvas_h),
        "scenes": scenes,
    }


def _make_base_canvas(
    source_img: Image.Image,
    zones_with_plans: List[Dict],
    bg_color: Tuple[int, int, int],
) -> Image.Image:
    """Create base canvas: source with zone regions painted bg_color."""
    frame = source_img.copy()
    if frame.mode != "RGB":
        frame = frame.convert("RGB")

    draw = ImageDraw.Draw(frame)
    fill_color = tuple(int(v) for v in bg_color)

    for zone_dict in zones_with_plans:
        polygon = zone_dict.get("polygon", [])
        if len(polygon) >= 3:
            draw.polygon(polygon, fill=fill_color)

    return frame


def _extract_sticker(
    source_array: np.ndarray,
    polygon: List[Tuple[int, int]],
    zone_id: int,
    bg_color: Tuple[int, int, int],
    order: int = 0,
) -> Sticker:
    """Extract RGBA sticker from source image using polygon mask + chroma."""
    import cv2

    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    x1, x2 = min(xs), max(xs)
    y1, y2 = min(ys), max(ys)
    w, h = x2 - x1, y2 - y1

    if w < 5 or h < 5:
        raise ValueError(f"Bounding box too small: {w}x{h}")

    # Contiguous copy to prevent heap corruption (0xc0000374) from non-contig slices
    crop = np.ascontiguousarray(source_array[y1 : y1 + h, x1 : x1 + w])

    # Polygon mask (local coords)
    mask_img = Image.new("L", (w, h), 0)
    local_polygon = [(x - x1, y - y1) for x, y in polygon]
    ImageDraw.Draw(mask_img).polygon(local_polygon, fill=255)
    poly_mask = np.ascontiguousarray(np.array(mask_img), dtype=np.uint8)

    # Chroma mask via int32 squared-distance (no BLAS — safer in threaded context).
    # CRITICAL: use SAME threshold as zone_refiner so polygon area matches
    # sticker alpha exactly. Different thresholds → halo of bg_color around
    # faint content (chroma 15-25) that never animates.
    bg = np.array(bg_color, dtype=np.int32)
    diff = crop.astype(np.int32) - bg
    chroma_dist_sq = (diff * diff).sum(axis=2)
    chroma_threshold_sq = _REFINER_CHROMA_THRESHOLD * _REFINER_CHROMA_THRESHOLD
    chroma_mask = (chroma_dist_sq > chroma_threshold_sq).astype(np.uint8) * 255

    alpha = np.ascontiguousarray((poly_mask & chroma_mask), dtype=np.uint8)

    # Morph open + blur (each step ensures contiguous uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, kernel)
    alpha = np.ascontiguousarray(alpha, dtype=np.uint8)
    alpha = cv2.GaussianBlur(alpha, (5, 5), 1.5)

    rgba = np.dstack([crop, alpha])
    sticker_img = Image.fromarray(rgba, "RGBA")

    # Centroid (center of mass)
    mask_nonzero = alpha > 128
    if mask_nonzero.any():
        ys_arr, xs_arr = np.where(mask_nonzero)
        cy = float(np.mean(ys_arr))
        cx = float(np.mean(xs_arr))
    else:
        cx, cy = w / 2, h / 2

    return Sticker(
        zone_id=zone_id,
        image=sticker_img,
        position=(x1, y1),
        size=(w, h),
        centroid=(cx, cy),
        order=order,
    )


# ============================================================
# M1 Render logic (ported standalone)
# ============================================================

def _compute_transform_at_t(
    scene: dict, sticker: Sticker, t: float
) -> Optional[StickerTransform]:
    """Return transform for this scene at time t, or None if not visible.

    Uses cached animation instances from scene["_entry_anim"] / "_emphasis_anim"
    to avoid rebuilding every frame.
    """
    appear_at = scene["appear_at"]
    if t < appear_at:
        return None

    entry = scene["entry"]
    emphasis = scene.get("emphasis")
    t_after_appear = t - appear_at

    # Phase 1: entry
    if t_after_appear < entry["duration"]:
        anim = scene.get("_entry_anim") or build_animation(entry["type"], entry.get("params", {}))
        return anim.transform(sticker, t_after_appear, entry["duration"])

    # Phase 2+: idle (entry done)
    base = StickerTransform()

    if not emphasis:
        return base

    emphasis_start_local = entry["duration"] + emphasis.get("delay", 0.0)
    if t_after_appear < emphasis_start_local:
        return base

    t_in_emphasis = t_after_appear - emphasis_start_local
    if t_in_emphasis < emphasis["duration"]:
        anim = scene.get("_emphasis_anim") or build_animation(emphasis["type"], emphasis.get("params", {}))
        emp_transform = anim.transform(sticker, t_in_emphasis, emphasis["duration"])
        return compose_transforms(base, emp_transform)

    # Phase 4: post-emphasis idle
    return base


def _transform_around_centroid(
    rgba: Image.Image,
    centroid: Tuple[float, float],
    scale: float,
    rotation_deg: float,
) -> Tuple[Image.Image, Tuple[float, float]]:
    """Apply scale/rotate around centroid. Returns (new_img, paste_offset_correction)."""
    if scale == 1.0 and rotation_deg == 0.0:
        return rgba, (0.0, 0.0)

    w, h = rgba.size
    cx, cy = centroid
    img = rgba

    if scale != 1.0:
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = img.resize((new_w, new_h), Image.LANCZOS)

    if rotation_deg != 0.0:
        img = img.rotate(rotation_deg, resample=Image.BICUBIC, expand=True)

    new_w_after, new_h_after = img.size
    new_cx = cx * scale
    new_cy = cy * scale

    if rotation_deg != 0.0:
        new_cx = new_w_after / 2
        new_cy = new_h_after / 2

    correction = (cx - new_cx, cy - new_cy)
    return img, correction


def _apply_opacity(rgba: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 1.0:
        return rgba
    if opacity <= 0.0:
        return Image.new("RGBA", rgba.size, (0, 0, 0, 0))

    r, g, b, a = rgba.split()
    # LUT (256 entries) — PIL applies vectorized in C. Lambda would call
    # Python per pixel (slow on 1920x1080).
    lut = [int(v * opacity) for v in range(256)]
    a_arr = a.point(lut)
    return Image.merge("RGBA", (r, g, b, a_arr))


def _paste_layer(
    canvas: Image.Image,
    layer_img: Image.Image,
    paste_pos: Tuple[int, int],
    opacity: float,
    blend_mode: str,
):
    """Paste a layer onto canvas (RGB). Supports 'normal' and 'screen' blend."""
    if opacity < 1.0:
        layer_img = _apply_opacity(layer_img, opacity)

    if blend_mode == "screen":
        x, y = paste_pos
        lw, lh = layer_img.size
        cw, ch = canvas.size

        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(cw, x + lw)
        y1 = min(ch, y + lh)
        if x0 >= x1 or y0 >= y1:
            return

        layer_crop = layer_img.crop((x0 - x, y0 - y, x1 - x, y1 - y))
        canvas_region = canvas.crop((x0, y0, x1, y1)).convert("RGB")

        layer_np = np.array(layer_crop.convert("RGBA"), dtype=np.float32)
        canvas_np = np.array(canvas_region, dtype=np.float32)

        layer_rgb = layer_np[:, :, :3] / 255.0
        layer_alpha = layer_np[:, :, 3:4] / 255.0
        canvas_rgb = canvas_np[:, :, :3] / 255.0

        screened = 1.0 - (1.0 - canvas_rgb) * (1.0 - layer_rgb)
        result = canvas_rgb * (1 - layer_alpha) + screened * layer_alpha
        result_np = (result * 255.0).clip(0, 255).astype(np.uint8)

        result_img = Image.fromarray(result_np, mode="RGB")
        canvas.paste(result_img, (x0, y0))
    else:
        canvas.paste(layer_img, paste_pos, layer_img)


def _render_frame(
    canvas_size: Tuple[int, int],
    bg_color: Tuple[int, int, int],
    scenes_with_stickers: List[Tuple[dict, Sticker]],
    t: float,
    base_canvas: Optional[Image.Image] = None,
) -> Image.Image:
    """Render single frame at time t. Expects scenes_with_stickers ALREADY sorted by z-order."""
    if base_canvas is not None:
        canvas = base_canvas.copy()
    else:
        canvas = Image.new("RGB", canvas_size, tuple(bg_color))

    for scene, sticker in scenes_with_stickers:
        transform = _compute_transform_at_t(scene, sticker, t)
        if transform is None:
            continue

        # 1. Render glow / extra layers UNDER sticker
        for layer in transform.extra_layers:
            paste_x = int(round(sticker.position[0] + transform.offset[0] + layer.offset[0]))
            paste_y = int(round(sticker.position[1] + transform.offset[1] + layer.offset[1]))
            _paste_layer(
                canvas, layer.image, (paste_x, paste_y), layer.opacity, layer.blend_mode
            )

        # 2. Transform sticker (scale/rotate around centroid)
        sticker_img = sticker.image
        sticker_img, correction = _transform_around_centroid(
            sticker_img, sticker.centroid, transform.scale, transform.rotation_deg
        )

        # 3. Apply opacity
        if transform.opacity < 1.0:
            sticker_img = _apply_opacity(sticker_img, transform.opacity)

        # 4. Paste at position + offset + correction
        paste_x = int(round(sticker.position[0] + transform.offset[0] + correction[0]))
        paste_y = int(round(sticker.position[1] + transform.offset[1] + correction[1]))
        canvas.paste(sticker_img, (paste_x, paste_y), sticker_img)

    return canvas


def _render_frames(
    frames_dir: Path,
    canvas_size: Tuple[int, int],
    bg_color: Tuple[int, int, int],
    base_canvas: Image.Image,
    render_plan: Dict,
    stickers: Dict,
    log_cb: Callable,
) -> int:
    """Render all frames to PNG sequence using M1 render_frame logic."""
    frames_dir.mkdir(parents=True, exist_ok=True)

    fps = render_plan["fps"]
    duration = render_plan["duration"]
    total_frames = int(round(duration * fps))

    # Pre-pair scenes with stickers (M1 pattern)
    scenes_with_stickers = []
    for scene in render_plan["scenes"]:
        sticker = stickers.get(scene["zone_id"])
        if sticker is None:
            log_cb(f"  WARN: No sticker for zone_id {scene['zone_id']}, skipping")
            continue
        scenes_with_stickers.append((scene, sticker))

    if not scenes_with_stickers:
        raise RuntimeError("No scenes can be rendered (all stickers missing)")

    # Z-order: sort once before loop (smaller order = bottom layer)
    scenes_with_stickers = sorted(scenes_with_stickers, key=lambda ps: ps[1].order)

    progress_step = max(1, total_frames // 10)
    for frame_idx in range(total_frames):
        t = frame_idx / fps
        frame = _render_frame(
            canvas_size=canvas_size,
            bg_color=bg_color,
            scenes_with_stickers=scenes_with_stickers,
            t=t,
            base_canvas=base_canvas,
        )
        frame.save(frames_dir / f"frame_{frame_idx:04d}.png", optimize=False)

        if frame_idx % progress_step == 0:
            pct = int(100 * frame_idx / max(total_frames, 1))
            log_cb(f"  Frame {frame_idx}/{total_frames} ({pct}%)")

    return total_frames


# ============================================================
# Encoding
# ============================================================

def _collect_audio_inputs(
    render_plan: Dict, sounds_dir: Path
) -> List[Tuple[float, Path]]:
    """Build list of (offset, sound_file) for ffmpeg."""
    inputs = []
    for scene in render_plan["scenes"]:
        sound = scene.get("sound")
        if not sound:
            continue
        sound_path = sounds_dir / f"{sound}.wav"
        if not sound_path.exists():
            continue
        inputs.append((scene["appear_at"], sound_path))
    return inputs


def _encode_video(
    frames_dir: Path,
    audio_inputs: List[Tuple[float, Path]],
    output_path: Path,
    fps: int,
    canvas_size: Tuple[int, int],
    source_size: Tuple[int, int],
    codec: str = "libx264",
    crf: int = 18,
    bg_color: Tuple[int, int, int] = (255, 255, 255),
) -> None:
    """Encode PNG frames + audio into MP4.

    Frames are rendered at source_size, then scaled+padded to canvas_size
    (16:9 or 9:16) by ffmpeg. Pad color matches detected bg so pillarbox
    bars blend with the source image.
    """
    import subprocess

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas_w, canvas_h = canvas_size
    source_w, source_h = source_size
    pad_color = f"0x{bg_color[0]:02x}{bg_color[1]:02x}{bg_color[2]:02x}"

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%04d.png"),
    ]

    # Audio inputs
    for offset, sound_path in audio_inputs:
        cmd.extend(["-itsoffset", f"{offset}", "-i", str(sound_path)])

    # Video filter: scale-fit + pad to canvas aspect
    vf = (
        f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
        f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color={pad_color},"
        f"setsar=1,format=yuv420p"
    )

    if audio_inputs:
        n = len(audio_inputs)
        prep = ";".join(f"[{i+1}:a]volume=0.7[a{i}]" for i in range(n))
        amix_inputs = "".join(f"[a{i}]" for i in range(n))
        filter_complex = (
            f"[0:v]{vf}[vout];"
            f"{prep};"
            f"{amix_inputs}amix=inputs={n}:duration=longest:dropout_transition=0[amix];"
            f"[amix]apad[aout]"
        )
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[vout]",
            "-map", "[aout]",
            "-shortest",
        ])
    else:
        cmd.extend(["-vf", vf, "-map", "0:v"])

    cmd.extend(["-c:v", codec, "-crf", str(crf)])

    if audio_inputs:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])

    cmd.append(str(output_path))

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr_msg = result.stderr[-2000:] if result.stderr else ""
        raise RuntimeError(
            f"ffmpeg failed (code {result.returncode}).\n{stderr_msg}"
        )
