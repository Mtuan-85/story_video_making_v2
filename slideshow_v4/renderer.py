"""
Renderer v3 - support group (multi-object per scene).

Key change: mỗi scene trong plan có array 'objects[]'.
Tất cả objects cùng scene → cùng appear_at + cùng animation.
"""

import shutil
import subprocess
from pathlib import Path

from animations import (
    ANIMATION_DURATION,
    build_animation_exprs,
    build_scale_animation_filter,
    needs_scale_animation,
)


PRESETS = {
    "youtube": {"width": 1920, "height": 1080, "fps": 30, "bitrate": "8M"},
    "tiktok":  {"width": 1080, "height": 1920, "fps": 30, "bitrate": "6M"},
}


def find_ffmpeg() -> str:
    for name in ("ffmpeg", "ffmpeg.exe"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("Không tìm thấy ffmpeg. Cài từ https://ffmpeg.org/download.html")


def compute_source_to_canvas_transform(source_w, source_h, canvas_w, canvas_h):
    """Strategy (c): scale fit, center, bg solid fill còn lại."""
    scale = min(canvas_w / source_w, canvas_h / source_h)
    scaled_w = source_w * scale
    scaled_h = source_h * scale
    offset_x = (canvas_w - scaled_w) / 2
    offset_y = (canvas_h - scaled_h) / 2
    return scale, offset_x, offset_y


def build_filter_complex(metadata: dict, plan: dict, canvas_w: int, canvas_h: int) -> tuple:
    """
    Build ffmpeg filter_complex.
    Trả về (filter_string, ordered_object_filenames).
    ordered_object_filenames: list filename theo thứ tự input (để build ffmpeg -i).
    """
    source_w, source_h = metadata["source_size"]
    scale, offset_x, offset_y = compute_source_to_canvas_transform(
        source_w, source_h, canvas_w, canvas_h
    )

    meta_by_name = {obj["filename"]: obj for obj in metadata["objects"]}

    # Flatten: list (obj_filename, appear_at, animation) theo thứ tự overlay
    flat_overlays = []
    for scene in plan["scenes"]:
        appear_at = float(scene["appear_at"])
        animation = scene["animation"]
        for obj_fn in scene["objects"]:
            flat_overlays.append({
                "filename": obj_fn,
                "appear_at": appear_at,
                "animation": animation,
            })

    # Sort by appear_at để overlay theo thứ tự thời gian (earlier first)
    # Nếu cùng appear_at, giữ nguyên thứ tự metadata
    flat_overlays.sort(key=lambda o: (o["appear_at"], o["filename"]))

    # Thứ tự input files cho ffmpeg = thứ tự overlay
    ordered_filenames = [o["filename"] for o in flat_overlays]

    parts = []
    parts.append(f"[0:v]format=yuv420p,setsar=1[bg]")
    last_layer = "bg"

    for i, overlay in enumerate(flat_overlays, start=1):
        obj_fn = overlay["filename"]
        appear_at = overlay["appear_at"]
        animation = overlay["animation"]

        obj_meta = meta_by_name[obj_fn]
        pos_src_x, pos_src_y = obj_meta["position_in_source"]
        size_src_w, size_src_h = obj_meta["size"]

        target_x = int(offset_x + pos_src_x * scale)
        target_y = int(offset_y + pos_src_y * scale)
        target_w = max(1, int(size_src_w * scale))
        target_h = max(1, int(size_src_h * scale))

        scaled_label = f"obj{i}_s"
        anim_label = f"obj{i}"

        parts.append(f"[{i}:v]scale={target_w}:{target_h}[{scaled_label}]")

        chain = [f"[{scaled_label}]format=rgba"]
        if needs_scale_animation(animation):
            sf = build_scale_animation_filter(animation, appear_at, target_w, target_h)
            chain.append(sf)
        chain.append(f"fade=in:st={appear_at}:d={ANIMATION_DURATION}:alpha=1")
        parts.append(",".join(chain) + f"[{anim_label}]")

        x_expr, y_expr = build_animation_exprs(
            animation, appear_at, target_x, target_y, canvas_w, canvas_h
        )

        next_layer = f"v{i}"
        parts.append(
            f"[{last_layer}][{anim_label}]overlay="
            f"x='{x_expr}':y='{y_expr}':"
            f"enable='gte(t,{appear_at})':"
            f"format=auto[{next_layer}]"
        )
        last_layer = next_layer

    parts.append(f"[{last_layer}]format=yuv420p[out]")
    return ";".join(parts), ordered_filenames


def render_video(metadata: dict, plan: dict, processed_dir: Path,
                 output_path: Path, preset_name: str = "youtube",
                 progress_callback=None) -> Path:
    if preset_name not in PRESETS:
        raise ValueError(f"Preset không hợp lệ: {preset_name}")

    preset = PRESETS[preset_name]
    canvas_w = preset["width"]
    canvas_h = preset["height"]
    fps = preset["fps"]
    bitrate = preset["bitrate"]
    duration = plan.get("duration", 5)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = find_ffmpeg()

    r, g, b = metadata["bg_color_rgb"]
    bg_hex = f"0x{r:02X}{g:02X}{b:02X}"

    fc, ordered_filenames = build_filter_complex(metadata, plan, canvas_w, canvas_h)

    cmd = [ffmpeg, "-y"]
    cmd.extend([
        "-f", "lavfi",
        "-t", str(duration),
        "-i", f"color=c={bg_hex}:s={canvas_w}x{canvas_h}:r={fps}",
    ])
    for fn in ordered_filenames:
        obj_path = processed_dir / fn
        if not obj_path.exists():
            raise FileNotFoundError(f"Object file missing: {obj_path}")
        cmd.extend(["-loop", "1", "-t", str(duration), "-i", str(obj_path)])

    cmd.extend(["-filter_complex", fc])
    cmd.extend(["-map", "[out]"])
    cmd.extend([
        "-r", str(fps),
        "-c:v", "libx264",
        "-preset", "medium",
        "-b:v", bitrate,
        "-pix_fmt", "yuv420p",
        "-t", str(duration),
        "-movflags", "+faststart",
        str(output_path),
    ])

    total_objects = len(ordered_filenames)
    total_scenes = len(plan["scenes"])
    if progress_callback:
        progress_callback(
            f"ffmpeg: {canvas_w}x{canvas_h}, bg {bg_hex}, "
            f"{total_scenes} scenes / {total_objects} objects, {duration}s"
        )

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding='utf-8', errors='replace'
    )

    if result.returncode != 0:
        err = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr
        raise RuntimeError(f"ffmpeg lỗi:\n{err}\n\nFilter (first 500):\n{fc[:500]}...")

    if not output_path.exists():
        raise RuntimeError("ffmpeg chạy xong nhưng không có output")

    return output_path
