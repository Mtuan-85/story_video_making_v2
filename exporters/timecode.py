"""Time conversion utilities for Kdenlive/MLT export.

Per Sprint 2 §12: timeline JSON uses seconds, MLT uses frames. This module
is the SINGLE source of truth for sec↔frame conversion. Never duplicate
time math in callers.

MLT `out` field convention:
    out = last_frame_index_inclusive
    so a 30-frame clip uses in=0, out=29.
"""

from __future__ import annotations


def sec_to_frame(sec: float, fps: int) -> int:
    """Round to nearest frame at given fps. Negative inputs clamp to 0."""
    if sec < 0:
        return 0
    return int(round(sec * fps))


def frame_to_sec(frame: int, fps: int) -> float:
    """Inverse of sec_to_frame. Useful for log readouts."""
    return frame / max(1, fps)


def duration_frames(render_in: float, render_out: float, fps: int) -> int:
    """Clip duration in frames. Always >= 0."""
    return max(0, sec_to_frame(render_out, fps) - sec_to_frame(render_in, fps))


def mlt_in_out(render_in: float, render_out: float, fps: int) -> tuple[int, int]:
    """Return (mlt_in, mlt_out) where mlt_out is INCLUSIVE last frame.

    mlt_in stays at 0 for new producer placements; the timeline position
    is handled by playlist <entry> attributes, not by producer in/out.
    """
    length = duration_frames(render_in, render_out, fps)
    if length <= 0:
        # Single-frame fallback to avoid out=-1 which breaks Kdenlive
        return (0, 0)
    return (0, length - 1)
