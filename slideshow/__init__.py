"""Slideshow v2 — Zone-based animation reveal engine.

Standalone package (no external dependencies beyond standard libs + FFmpeg + Claude).
Runs synchronously (single-thread).

Pipeline: BG detect → Claude auto-pick zones → refine polygons → render video.

Usage:
    from slideshow import render_slideshow_v2
    mp4_path = render_slideshow_v2(
        image_path=Path("scene.png"),
        output_path=Path("output.mp4"),
        duration_sec=8.0,
        aspect_ratio="16:9",
        hint="zones left to right, slow pacing",
        log_cb=print,
    )
"""

import sys
from pathlib import Path

# Add slideshow directory to sys.path for submodule imports
_slideshow_dir = Path(__file__).resolve().parent
if str(_slideshow_dir) not in sys.path:
    sys.path.insert(0, str(_slideshow_dir))

try:
    from orchestrator import render_slideshow_v2, rerender_slideshow_v2
except ImportError as e:
    raise RuntimeError(f"Failed to import orchestrator: {e}") from e

__all__ = ["render_slideshow_v2", "rerender_slideshow_v2"]
