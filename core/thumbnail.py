"""Thumbnail generation — 60px previews for scene rows.

Cache at `<project>/thumbnails/<scene_id>.jpg`. Auto-generated after
gen image / video success. Click on row's thumbnail opens preview dialog.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger as log

THUMBNAIL_MAX_SIDE = 60  # px on the longer side
THUMBNAIL_QUALITY = 70


def _resize_with_pil(src: Path, dst: Path) -> bool:
    try:
        from PIL import Image  # noqa: WPS433 — lazy import (Pillow optional at runtime)
    except ImportError:
        log.warning("Pillow not installed — skip thumbnail")
        return False
    try:
        with Image.open(src) as im:
            w, h = im.size
            if w >= h:
                new_w = THUMBNAIL_MAX_SIDE
                new_h = max(1, int(h * THUMBNAIL_MAX_SIDE / w))
            else:
                new_h = THUMBNAIL_MAX_SIDE
                new_w = max(1, int(w * THUMBNAIL_MAX_SIDE / h))
            im = im.resize((new_w, new_h), Image.LANCZOS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            im.convert("RGB").save(dst, "JPEG", quality=THUMBNAIL_QUALITY)
        return True
    except Exception as e:
        log.warning(f"PIL resize fail ({src.name}): {e}")
        return False


def generate_image_thumbnail(source_path: Path, output_path: Path) -> bool:
    """Resize an image down to <=60px on longest side."""
    return _resize_with_pil(Path(source_path), Path(output_path))


def generate_video_thumbnail(
    source_path: Path,
    output_path: Path,
    timestamp_sec: float = 1.0,
) -> bool:
    """Extract a frame at `timestamp_sec` then resize."""
    src = Path(source_path)
    dst = Path(output_path)
    tmp_frame = dst.with_suffix(".tmp.jpg")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{timestamp_sec:.3f}",
            "-i", str(src),
            "-frames:v", "1",
            "-q:v", "2",
            str(tmp_frame),
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0 or not tmp_frame.exists():
            log.warning(f"ffmpeg frame extract fail for {src.name}")
            return False
        ok = _resize_with_pil(tmp_frame, dst)
        try:
            tmp_frame.unlink(missing_ok=True)
        except Exception:
            pass
        return ok
    except Exception as e:
        log.warning(f"Video thumbnail fail ({src.name}): {e}")
        return False


def regenerate_thumbnail(
    *,
    project_root: Path,
    scene_id: str,
    visual_path: Path,
    visual_kind: str,
) -> Path | None:
    """Regenerate the cached thumbnail for one scene.

    `visual_kind` is "image" or "video" — picks the right extractor.
    Returns the thumbnail path on success, None on failure.
    """
    thumb_path = Path(project_root) / "thumbnails" / f"{scene_id}.jpg"
    visual_path = Path(visual_path)
    if not visual_path.exists():
        return None

    if visual_kind == "image":
        ok = generate_image_thumbnail(visual_path, thumb_path)
    elif visual_kind == "video":
        ok = generate_video_thumbnail(visual_path, thumb_path)
    else:
        log.warning(f"Unknown visual_kind: {visual_kind}")
        return None
    return thumb_path if ok else None
