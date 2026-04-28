"""Ken Burns effect (slow zoom-pan) via ffmpeg zoompan filter.

Two modes:
    self          — zoom-pan applied to the scene's own image
    continuation  — extract last frame of the previous video, then zoom-pan

zoompan quirk: the filter outputs ONE frame per d= (duration in frames). To
emit a stream, we feed the still through `loop` first, then zoompan. The
output canvas is fixed (1920x1080 or 1080x1920); the source image is rescaled
to ~2x canvas before zooming so the zoom doesn't expose pixel boundaries.
"""

from __future__ import annotations

import asyncio
import shlex
import subprocess
from pathlib import Path
from typing import Literal

from loguru import logger as log

CANVAS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
}
FPS = 30
ZOOM_RATE_DEFAULT = 0.04  # 4% per second
ZOOM_MAX = 1.5
ZOOM_MIN_BOUND = 1.0001  # zoompan needs >1 to avoid div-by-zero pan math

Direction = Literal["in", "out", "pan_left", "pan_right"]


def _resolve_canvas(aspect_ratio: str) -> tuple[int, int]:
    if aspect_ratio not in CANVAS:
        raise ValueError(f"aspect_ratio không hỗ trợ: {aspect_ratio}")
    return CANVAS[aspect_ratio]


def _zoompan_expression(
    direction: Direction,
    duration_sec: float,
    zoom_rate: float,
    width: int,
    height: int,
) -> tuple[str, str, str]:
    """Build (z, x, y) expressions for zoompan.

    `on` is current output frame index (0-based). Total frames = duration*FPS.
    Per-frame zoom delta = zoom_rate / FPS.
    """
    frames = max(1, int(round(duration_sec * FPS)))
    per_frame = zoom_rate / FPS

    if direction == "in":
        # Zoom from 1.0 to 1 + zoom_rate*duration, capped at ZOOM_MAX.
        z = f"min(zoom+{per_frame:.6f},{ZOOM_MAX})"
        x = f"iw/2-(iw/zoom/2)"
        y = f"ih/2-(ih/zoom/2)"
    elif direction == "out":
        zoom_start = min(1 + zoom_rate * duration_sec, ZOOM_MAX)
        # Decrease but never below 1.0001 (else pan math diverges).
        z = f"if(eq(on,0),{zoom_start:.4f},max(zoom-{per_frame:.6f},{ZOOM_MIN_BOUND}))"
        x = f"iw/2-(iw/zoom/2)"
        y = f"ih/2-(ih/zoom/2)"
    elif direction == "pan_left":
        # Hold a slight zoom and pan from right edge → left edge.
        z = f"{1.15}"
        x = f"(iw-iw/zoom)*(1-on/{frames})"
        y = f"ih/2-(ih/zoom/2)"
    elif direction == "pan_right":
        z = f"{1.15}"
        x = f"(iw-iw/zoom)*(on/{frames})"
        y = f"ih/2-(ih/zoom/2)"
    else:
        raise ValueError(f"direction không hỗ trợ: {direction}")

    return z, x, y


def build_zoompan_filter(
    duration_sec: float,
    aspect_ratio: str,
    direction: Direction = "in",
    zoom_rate: float = ZOOM_RATE_DEFAULT,
) -> str:
    """Return the `-vf` filtergraph string for one ken-burns clip.

    Pipeline:
        scale to 2x canvas (oversample so zoom doesn't blur)
        → zoompan (one frame per duration unit)
        → format yuv420p (h264-friendly)
    """
    w, h = _resolve_canvas(aspect_ratio)
    frames = max(1, int(round(duration_sec * FPS)))
    z_expr, x_expr, y_expr = _zoompan_expression(
        direction, duration_sec, zoom_rate, w, h
    )

    # Oversample to ~2x for headroom.
    over_w, over_h = w * 2, h * 2
    return (
        f"scale={over_w}:{over_h}:force_original_aspect_ratio=increase,"
        f"crop={over_w}:{over_h},"
        f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
        f"d={frames}:s={w}x{h}:fps={FPS},"
        f"format=yuv420p"
    )


async def _run_ffmpeg(cmd: list[str]) -> None:
    log.debug("ffmpeg: " + " ".join(shlex.quote(c) for c in cmd))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        tail = (stderr or b"").decode("utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"ffmpeg fail (rc={proc.returncode}):\n{tail}")


async def ken_burns_self(
    image_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,
    direction: Direction = "in",
    zoom_rate: float = ZOOM_RATE_DEFAULT,
) -> Path:
    """Render Ken Burns on a still image."""
    image_path = Path(image_path)
    output_path = Path(output_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Ảnh không tồn tại: {image_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    vf = build_zoompan_filter(duration_sec, aspect_ratio, direction, zoom_rate)
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-framerate", str(FPS),
        "-i", str(image_path),
        "-t", f"{duration_sec:.3f}",
        "-vf", vf,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-r", str(FPS),
        "-an",
        str(output_path),
    ]
    log.info(f"Ken Burns self: {image_path.name} → {output_path.name} ({duration_sec:.1f}s, {direction})")
    await _run_ffmpeg(cmd)
    return output_path


async def extract_last_frame(video_path: Path, frame_path: Path) -> Path:
    """Extract last frame of a video as PNG. Uses -sseof to seek from the end."""
    video_path = Path(video_path)
    frame_path = Path(frame_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Video không tồn tại: {video_path}")
    frame_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-sseof", "-0.5",
        "-i", str(video_path),
        "-vsync", "0",
        "-update", "1",
        "-frames:v", "1",
        str(frame_path),
    ]
    log.info(f"Extract last frame: {video_path.name} → {frame_path.name}")
    await _run_ffmpeg(cmd)
    if not frame_path.exists():
        raise RuntimeError(f"Last-frame extract không tạo file: {frame_path}")
    return frame_path


async def ken_burns_continuation(
    prev_video_path: Path,
    output_path: Path,
    duration_sec: float,
    aspect_ratio: str,
    work_dir: Path | None = None,
    direction: Direction = "in",
    zoom_rate: float = ZOOM_RATE_DEFAULT,
) -> Path:
    """Extract last frame of prev video, then apply ken_burns_self on it."""
    prev_video_path = Path(prev_video_path)
    output_path = Path(output_path)
    work_dir = Path(work_dir) if work_dir else output_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    frame = work_dir / f"{output_path.stem}_lastframe.png"
    await extract_last_frame(prev_video_path, frame)
    return await ken_burns_self(
        frame, output_path, duration_sec, aspect_ratio, direction, zoom_rate
    )
