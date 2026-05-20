"""Visual fit-to-duration: extend or speedup based on visual_type.

For Image / slideshow: zoompan duration = duration_adjusted (auto fit).
For Video:
  - duration_adjusted < duration_design: setpts speedup
  - duration_adjusted > duration_design: tpad freeze last frame

Aspect/resolution is configurable per-call so 16:9 (1920x1080) and 9:16
(1080x1920) both work.
"""

from __future__ import annotations

from loguru import logger as log


FPS = 30
ZOOM_RANGE = 0.2          # 1.0 -> 1.2
TOLERANCE = 0.1           # within 0.1s of design -> no fit


def aspect_to_size(aspect: str) -> tuple[int, int]:
    """Map "16:9" / "9:16" to (width, height)."""
    if aspect == "16:9":
        return 1920, 1080
    if aspect == "9:16":
        return 1080, 1920
    raise ValueError(f"aspect_ratio không hỗ trợ: {aspect}")


def build_zoom_filter(
    effect: str,
    duration_sec: float,
    width: int,
    height: int,
    fps: int = FPS,
) -> str:
    """Build a smooth zoompan filter for a still image (used with `-loop 1`).

    Anti-jitter strategy:
      1. Pre-scale the source 4x via lanczos so zoompan has sub-pixel headroom
         and rounding produces less visible shake.
      2. Wrap x/y in trunc() to eliminate sub-pixel drift between frames.
      3. d=total_frames — `-loop 1` emits exactly one input frame; zoompan
         must extend that single input across every output frame, otherwise
         the zoom accumulator resets each emitted frame and the motion stops.
    """
    if effect == "no_effect":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )

    total_frames = max(1, int(round(duration_sec * fps)))
    upscale_w = width * 4
    upscale_h = height * 4
    zoom_target = 1.0 + ZOOM_RANGE  # 1.2
    span = float(ZOOM_RANGE)

    if effect == "zoom_in":
        z_expr = f"min(1.0+{span:.4f}*on/{total_frames},{zoom_target:.4f})"
    elif effect == "zoom_out":
        z_expr = f"max({zoom_target:.4f}-{span:.4f}*on/{total_frames},1.0)"
    else:
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )

    return (
        f"scale={upscale_w}:{upscale_h}:flags=lanczos,"
        f"zoompan=z='{z_expr}':"
        f"x='trunc(iw/2-(iw/zoom/2))':"
        f"y='trunc(ih/2-(ih/zoom/2))':"
        f"d={total_frames}:s={width}x{height}:fps={fps},"
        f"setsar=1"
    )


def _zoom_tail(
    effect: str,
    duration_sec: float,
    width: int,
    height: int,
    fps: int,
) -> str | None:
    """Trailing zoompan tail for a video stream (or None for no_effect).

    Uses d=1 because the upstream is already a continuous video — one input
    frame yields one output frame. Same anti-jitter knobs as the still-image
    path: 4x lanczos pre-scale + trunc() on x/y.
    """
    if effect == "no_effect":
        return None

    total_frames = max(1, int(round(duration_sec * fps)))
    upscale_w = width * 4
    upscale_h = height * 4
    zoom_target = 1.0 + ZOOM_RANGE
    span = float(ZOOM_RANGE)

    if effect == "zoom_in":
        z_expr = f"min(1.0+{span:.4f}*on/{total_frames},{zoom_target:.4f})"
    elif effect == "zoom_out":
        z_expr = f"max({zoom_target:.4f}-{span:.4f}*on/{total_frames},1.0)"
    else:
        return None

    return (
        f"scale={upscale_w}:{upscale_h}:flags=lanczos,"
        f"zoompan=z='{z_expr}':"
        f"x='trunc(iw/2-(iw/zoom/2))':"
        f"y='trunc(ih/2-(ih/zoom/2))':"
        f"d=1:s={width}x{height}:fps={fps}"
    )


def build_video_filter(
    duration_design: float,
    duration_adjusted: float,
    effect: str,
    width: int,
    height: int,
    fps: int = FPS,
) -> str:
    """Filter chain for a video-source visual (Video / slideshow .mp4).

    Pipeline:
      1. setpts speedup OR tpad freeze-extend to fit duration_adjusted.
         Speedup is capped at 1.2x — anything tighter is unnatural for
         spoken-narration timing — so a steeper ratio caps the speedup at
         1.2x then trims the excess.
      2. scale + pad to canvas.
      3. fps normalize.
      4. Optional zoom tail (with its own pre-scale).
    """
    parts: list[str] = []

    if abs(duration_adjusted - duration_design) >= TOLERANCE:
        if duration_adjusted < duration_design:
            ratio = duration_design / duration_adjusted
            if ratio <= 1.2:
                pts_factor = duration_adjusted / duration_design
                log.info(
                    f"video speedup: design={duration_design}s "
                    f"adjusted={duration_adjusted}s "
                    f"setpts={pts_factor:.4f}*PTS (ratio {ratio:.2f}x)"
                )
                parts.append(f"setpts={pts_factor:.4f}*PTS")
            else:
                # Cap at 1.2x then trim the leftover.
                pts_factor_capped = 1.0 / 1.2  # ≈ 0.8333
                log.info(
                    f"video speedup capped 1.2x + trim: design={duration_design}s "
                    f"adjusted={duration_adjusted}s (raw ratio {ratio:.2f}x)"
                )
                parts.append(f"setpts={pts_factor_capped:.4f}*PTS")
                parts.append(f"trim=duration={duration_adjusted:.3f}")
                parts.append("setpts=PTS-STARTPTS")
        else:
            extra = duration_adjusted - duration_design
            log.info(
                f"video extend: design={duration_design}s adjusted={duration_adjusted}s "
                f"freeze tail +{extra:.2f}s"
            )
            parts.append(f"tpad=stop_mode=clone:stop_duration={extra:.3f}")

    parts.append(
        f"scale={width}:{height}:force_original_aspect_ratio=decrease"
    )
    parts.append(f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2")
    parts.append(f"fps={fps}")

    zoom = _zoom_tail(effect, duration_adjusted, width, height, fps)
    if zoom is not None:
        parts.append(zoom)

    parts.append("setsar=1")
    return ",".join(parts)


def build_visual_filter_with_fit(
    visual_type: str,
    duration_design: float,
    duration_adjusted: float,
    effect: str,
    width: int,
    height: int,
    fps: int = FPS,
    *,
    source_is_video: bool | None = None,
) -> str:
    """Return the filter string for a scene's visual stream.

    Args:
        source_is_video: explicit override. If None, derived from visual_type:
            Image → False, Video → True. `slideshow` is ambiguous
            (the slideshow renderer can emit either an mp4 or a jpg) so
            callers MUST pass `source_is_video` for that visual_type.

    Image-source path: build_zoom_filter (zoompan over a -loop 1 still).
    Video-source path: build_video_filter (setpts/tpad/scale/pad, optional
    zoompan tail).
    """
    if source_is_video is None:
        if visual_type == "Image":
            source_is_video = False
        elif visual_type == "Video":
            source_is_video = True
        else:
            log.warning(
                f"visual_type={visual_type} ambiguous about source — "
                "defaulting to video; pass source_is_video to override"
            )
            source_is_video = True

    if not source_is_video:
        return build_zoom_filter(effect, duration_adjusted, width, height, fps)

    return build_video_filter(
        duration_design=duration_design,
        duration_adjusted=duration_adjusted,
        effect=effect,
        width=width,
        height=height,
        fps=fps,
    )
