"""Generate placeholder image for missing scene visuals.

Per Sprint 2 §11: if `missing_asset_policy="placeholder"`, write a
human-readable JPG so the timeline still has a visible clip. Black
background, scene id + path in white text.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PIL import Image, ImageDraw, ImageFont


def generate_placeholder(
    scene_id: str,
    expected_path: str,
    output_jpg: Path,
    width: int = 1920,
    height: int = 1080,
) -> bool:
    """Render a black placeholder labelled with scene_id + missing path.

    Returns True on success. Idempotent — skips if file already exists.
    """
    output_jpg = Path(output_jpg)
    if output_jpg.exists():
        return True

    output_jpg.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Best-effort font load (fall back to default bitmap font)
    title_font = _load_font(72)
    body_font = _load_font(36)

    title = scene_id
    line2 = "Missing visual source"
    line3 = f"Expected: {expected_path}"

    # Center-stack 3 lines
    bbox = draw.textbbox((0, 0), title, font=title_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    y = (height // 2) - th - 60

    draw.text(((width - tw) // 2, y), title, fill=(255, 255, 255), font=title_font)

    bbox2 = draw.textbbox((0, 0), line2, font=body_font)
    tw2 = bbox2[2] - bbox2[0]
    draw.text(((width - tw2) // 2, y + th + 30), line2, fill=(200, 80, 80), font=body_font)

    bbox3 = draw.textbbox((0, 0), line3, font=body_font)
    tw3 = bbox3[2] - bbox3[0]
    th3 = bbox3[3] - bbox3[1]
    draw.text(
        ((width - tw3) // 2, y + th + 30 + th3 + 20),
        line3, fill=(180, 180, 180), font=body_font,
    )

    try:
        img.save(output_jpg, "JPEG", quality=88)
    except Exception as e:
        log.error(f"placeholder save failed for {scene_id}: {e}")
        return False

    log.info(f"placeholder generated: {output_jpg.name}")
    return True


def _load_font(size: int) -> ImageFont.ImageFont:
    """Try common system fonts. Fall back to default."""
    candidates = (
        "arial.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "DejaVuSans.ttf",
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()
