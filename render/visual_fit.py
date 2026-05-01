"""Visual fit-to-duration: extend or speedup based on visual_type.

For image_grok / slideshow: zoompan duration = duration_adjusted (auto fit).
For video_grok:
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
    """Build zoompan filter for a still image (or pre-rendered frame stream).

    Linear interpolation over the OUTPUT frame counter `on` so the zoom is
    smooth regardless of how many input frames are emitted by the loop. We
    also force `d=1` so each input frame produces exactly one output frame —
    avoids the multi-output-per-input mode where the `zoom` accumulator
    drifts and frames jitter.
    """
    if effect == "no_effect":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )

    total_frames = max(1, int(round(duration_sec * fps)))
    zoom_target = 1.0 + ZOOM_RANGE  # 1.2
    span = float(ZOOM_RANGE)

    if effect == "zoom_in":
        # 1.0 → 1.2 over total_frames
        z_expr = f"min(1.0+{span:.4f}*on/{total_frames},{zoom_target:.4f})"
    elif effect == "zoom_out":
        # 1.2 → 1.0 over total_frames
        z_expr = f"max({zoom_target:.4f}-{span:.4f}*on/{total_frames},1.0)"
    else:
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )

    return (
        f"zoompan=z='{z_expr}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={width}x{height}:fps={fps},"
        f"setsar=1"
    )


def _zoom_tail(
    effect: str,
    duration_sec: float,
    width: int,
    height: int,
    fps: int,
) -> str | None:
    """Return the trailing zoompan filter for a video stream, or None for no_effect.

    Used by `build_video_filter` to stack a zoom on top of a normalised
    canvas-sized video stream (after setpts/tpad/scale/pad). Same linear
    `on/total_frames` expression as `build_zoom_filter` so motion stays
    continuous.
    """
    if effect == "no_effect":
        return None

    total_frames = max(1, int(round(duration_sec * fps)))
    zoom_target = 1.0 + ZOOM_RANGE
    span = float(ZOOM_RANGE)

    if effect == "zoom_in":
        z_expr = f"min(1.0+{span:.4f}*on/{total_frames},{zoom_target:.4f})"
    elif effect == "zoom_out":
        z_expr = f"max({zoom_target:.4f}-{span:.4f}*on/{total_frames},1.0)"
    else:
        return None

    return (
        f"zoompan=z='{z_expr}':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
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
    """Filter chain for a video-source visual (video_grok / slideshow .mp4).

    Pipeline: setpts/tpad to fit duration → scale/pad to canvas → optional
    zoompan stacked on top. The zoom is applied AFTER the canvas-sized
    stream so it sees stable 1920x1080 frames.
    """
    parts: list[str] = []

    if abs(duration_adjusted - duration_design) >= TOLERANCE:
        if duration_adjusted < duration_design:
            pts_factor = duration_adjusted / duration_design
            log.info(
                f"video speedup: design={duration_design}s adjusted={duration_adjusted}s "
                f"setpts={pts_factor:.4f}*PTS"
            )
            parts.append(f"setpts={pts_factor:.4f}*PTS")
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
            image_grok → False, video_grok → True. `slideshow` is ambiguous
            (the slideshow renderer can emit either an mp4 or a jpg) so
            callers MUST pass `source_is_video` for that visual_type.

    Image-source path: build_zoom_filter (zoompan over a -loop 1 still).
    Video-source path: build_video_filter (setpts/tpad/scale/pad, optional
    zoompan tail).
    """
    if source_is_video is None:
        if visual_type == "image_grok":
            source_is_video = False
        elif visual_type == "video_grok":
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
