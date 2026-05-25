"""Generate freeze-frame JPGs from video sources for beat-pause clips.

Per Sprint 2 §9.2: beat_pause after a video/slideshow scene reuses the
last visible frame of that source. We extract it once via ffmpeg's
`-sseof -0.1` (seek 100ms from end, grab one frame).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger as log


def extract_last_frame(
    video_path: Path,
    output_jpg: Path,
    timeout_sec: int = 30,
) -> bool:
    """Extract the last frame of `video_path` to `output_jpg`. Idempotent.

    Returns True on success, False on failure (caller falls back to
    placeholder per spec §9.3).
    """
    video_path = Path(video_path)
    output_jpg = Path(output_jpg)

    if not video_path.exists():
        log.warning(f"extract_last_frame: source missing: {video_path}")
        return False

    if output_jpg.exists():
        # Cache hit — don't regenerate
        return True

    output_jpg.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-sseof", "-0.1",                  # 100ms before EOF
        "-i", str(video_path),
        "-frames:v", "1",
        "-q:v", "2",                       # high-quality JPEG (1-31, lower=better)
        str(output_jpg),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=timeout_sec,
        )
    except subprocess.TimeoutExpired:
        log.error(f"freeze_frame: ffmpeg timeout on {video_path.name}")
        return False

    if result.returncode != 0 or not output_jpg.exists():
        log.error(
            f"freeze_frame: ffmpeg failed for {video_path.name} "
            f"(rc={result.returncode}): {(result.stderr or '')[-500:]}"
        )
        return False

    log.debug(f"freeze_frame: {video_path.name} → {output_jpg.name}")
    return True
