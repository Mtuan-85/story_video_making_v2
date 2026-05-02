"""Assemble scene clips: concat (stream-copy) + burn ASS subtitle."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from loguru import logger as log


def assemble_concat(scene_paths: list[Path], output_path: Path) -> Path:
    """Concat scene videos via concat demuxer with stream copy (fast, lossless).

    Requires all clips share codec/timebase/resolution — composite enforces
    h264 + yuv420p + 30fps + same canvas, so this is safe.
    """
    if not scene_paths:
        raise ValueError("No scenes to assemble")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="assemble_"))
    list_file = tmp_dir / "concat_list.txt"
    list_file.write_text(
        "\n".join(f"file '{Path(p).resolve().as_posix()}'" for p in scene_paths) + "\n",
        encoding="utf-8",
    )

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat",
        "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600,
        )
    finally:
        try:
            list_file.unlink()
            tmp_dir.rmdir()
        except OSError:
            pass

    if result.returncode != 0:
        log.error(f"assemble failed: {(result.stderr or '')[-1500:]}")
        raise RuntimeError("FFmpeg assemble failed")

    log.info(f"assembled -> {output_path.name}")
    return output_path


def apply_ass_subtitle(
    input_video: Path,
    ass_path: Path,
    output_video: Path,
) -> Path:
    """Burn an ASS file into the video (libass via subtitles filter).

    Re-encodes video, copies audio. If the ASS file is missing, the input is
    copied verbatim to output (no-op for projects without subtitles).
    """
    input_video = Path(input_video)
    ass_path = Path(ass_path)
    output_video = Path(output_video)

    if not ass_path.exists():
        log.warning(f"ASS file not found: {ass_path}, skipping subtitle burn")
        shutil.copy(input_video, output_video)
        return output_video

    # libass on Windows: forward slashes, escape colon (for drive letter)
    ass_safe = str(ass_path.resolve()).replace("\\", "/").replace(":", "\\:")

    output_video.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(input_video),
        "-vf", f"subtitles='{ass_safe}'",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        str(output_video),
    ]

    log.info("apply_ass_subtitle: burning ASS via libass...")
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=900,
    )

    if result.returncode != 0:
        log.error(f"apply_ass_subtitle failed: {(result.stderr or '')[-1500:]}")
        raise RuntimeError("FFmpeg apply_ass_subtitle failed")

    log.info(f"  -> {output_video.name}")
    return output_video
