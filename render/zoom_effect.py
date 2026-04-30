"""Zoom effect filter for ffmpeg zoompan — applied ONLY at final render.

`build_zoom_effect_filter` returns the zoompan/scale-crop chunk to splice into
`composite_scene`'s filter_complex. Three modes:

  zoom_in   — 1.0 → 1.2 (linear over duration)
  zoom_out  — 1.2 → 1.0
  no_effect — straight scale + crop, no motion

Apply uniformly across visual_types (image_grok / slideshow / video_grok)
so the user controls the rhythm via Scene.effect.
"""

from __future__ import annotations

ZOOM_RANGE = 0.2  # 1.0 → 1.2 (20% over the clip)
ZOOM_MIN_BOUND = 1.0001  # zoompan needs >1 to avoid div-by-zero
DEFAULT_FPS = 30


def _crop_only(canvas_w: int, canvas_h: int) -> str:
    return (
        f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
        f"crop={canvas_w}:{canvas_h},setsar=1"
    )


def build_zoom_effect_filter(
    effect: str,
    duration_sec: float,
    canvas_w: int,
    canvas_h: int,
    fps: int = DEFAULT_FPS,
) -> str:
    """Return the ffmpeg filter expression for one scene's visual track.

    Args:
        effect: "zoom_in" | "zoom_out" | "no_effect"
        duration_sec: scene duration (use voice-first duration_adjusted).
        canvas_w/h: output canvas (1920x1080 for 16:9, 1080x1920 for 9:16).
        fps: frame rate (default 30).
    """
    if effect == "no_effect":
        return _crop_only(canvas_w, canvas_h)

    frames = max(1, int(round(duration_sec * fps)))
    per_frame = ZOOM_RANGE / frames
    zoom_target = 1.0 + ZOOM_RANGE  # 1.2

    if effect == "zoom_in":
        z_expr = f"min(zoom+{per_frame:.6f},{zoom_target:.4f})"
    elif effect == "zoom_out":
        z_expr = (
            f"if(eq(on,0),{zoom_target:.4f},"
            f"max(zoom-{per_frame:.6f},{ZOOM_MIN_BOUND}))"
        )
    else:
        return _crop_only(canvas_w, canvas_h)

    # Oversample to ~2x for headroom (avoid pixel-edge tearing under zoom).
    over_w, over_h = canvas_w * 2, canvas_h * 2
    return (
        f"scale={over_w}:{over_h}:force_original_aspect_ratio=increase,"
        f"crop={over_w}:{over_h},"
        f"zoompan=z='{z_expr}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={frames}:s={canvas_w}x{canvas_h}:fps={fps},"
        f"setsar=1"
    )
