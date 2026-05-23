"""Auto-detect solid background color from image border pixels."""

from pathlib import Path
from typing import Tuple

import numpy as np
from PIL import Image


def detect_bg_color(image_path: Path) -> Tuple[int, int, int]:
    """Return median RGB of border pixels as (r, g, b).

    Samples 4 corners + every w/20 and h/20 stride along edges.
    Robust to small foreground objects touching the border.
    """
    with Image.open(image_path) as img:
        rgb = np.array(img.convert("RGB"))

    h, w = rgb.shape[:2]

    samples = [rgb[0, 0], rgb[0, w - 1], rgb[h - 1, 0], rgb[h - 1, w - 1]]
    step_x = max(1, w // 20)
    step_y = max(1, h // 20)

    for x in range(0, w, step_x):
        samples.append(rgb[0, x])
        samples.append(rgb[h - 1, x])
    for y in range(0, h, step_y):
        samples.append(rgb[y, 0])
        samples.append(rgb[y, w - 1])

    arr = np.array(samples)
    bg = np.median(arr, axis=0).astype(np.uint8)
    return (int(bg[0]), int(bg[1]), int(bg[2]))
