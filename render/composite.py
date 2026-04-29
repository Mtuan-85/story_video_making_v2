"""Compose 1 scene = visual + voice slice + subtitle drawtext.

Output is a self-contained MP4 sized to the canvas, with embedded audio if
the scene has a voice assignment. Concatenation happens later in `assemble.py`.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from loguru import logger as log

from core.voice_mapping import SceneVoiceAssignment, SubtitlePhrase
from render.subtitle_filter import build_subtitle_drawtext_chain

VISUAL_STATIC_TYPES = {"image_grok", "ken_burns_self", "ken_burns_cont", "slideshow"}
FADE_DURATION = 0.25  # per-side fade; total transition between two scenes = 0.5s


def get_duration(media_path: Path) -> float:
    """ffprobe-based duration in seconds, 0.0 on error."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(media_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        return float(json.loads(result.stdout)["format"]["duration"])
    except Exception as e:
        log.warning(f"ffprobe failed for {media_path}: {e}")
        return 0.0


def _aspect_canvas(aspect: str) -> tuple[int, int]:
    return (1080, 1920) if aspect == "9:16" else (1920, 1080)


def _build_visual_filter(
    visual_path: Path,
    visual_type: str,
    target_dur: float,
    canvas_w: int,
    canvas_h: int,
) -> tuple[str, list[str]]:
    """Return (filter_string, warnings).

    Static visuals (image / ken_burns / slideshow already-rendered) are scaled
    + cropped to canvas. Grok video may need speedup or freeze-tail to match
    target duration; speedup capped at 1.20x to avoid chipmunk-effect.
    """
    warnings: list[str] = []
    crop_filter = (
        f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,"
        f"crop={canvas_w}:{canvas_h},setsar=1"
    )

    if visual_type in VISUAL_STATIC_TYPES:
        # Source is either a still image (image_grok) or a pre-rendered mp4
        # (ken_burns_*, slideshow). Either way, just scale/crop to canvas
        # and let the outer `-t target_dur` clamp duration. For images we
        # additionally rely on `-loop 1` upstream.
        return crop_filter, warnings

    if visual_type == "video_grok":
        video_dur = get_duration(visual_path)
        if video_dur <= 0:
            return crop_filter, warnings  # ffprobe failed; ffmpeg will error later.

        diff_pct = abs(video_dur - target_dur) / target_dur if target_dur > 0 else 0
        if diff_pct < 0.05:
            return crop_filter, warnings
        if video_dur < target_dur:
            freeze = target_dur - video_dur
            return (
                f"{crop_filter},tpad=stop_duration={freeze:.3f}:stop_mode=clone",
                warnings,
            )
        speed = video_dur / target_dur
        if speed <= 1.20:
            return f"{crop_filter},setpts={1 / speed:.4f}*PTS", warnings
        warnings.append(f"video_speedup_capped_at_1.20x (needed {speed:.2f}x)")
        return (
            f"{crop_filter},setpts={1 / 1.20:.4f}*PTS,trim=duration={target_dur:.3f}",
            warnings,
        )

    # Unknown visual type — best-effort scale.
    return crop_filter, warnings


async def composite_scene(
    *,
    scene_id: str,
    voice_file_path: Path | None,
    voice_assignment: SceneVoiceAssignment | None,
    visual_path: Path,
    visual_type: str,
    declared_duration: float,
    subtitle_phrases: list[SubtitlePhrase],
    output_path: Path,
    aspect_ratio: str = "16:9",
    font_path: Path | None = None,
    is_first: bool = True,
    is_last: bool = True,
) -> dict:
    """Render one scene MP4. Returns `{"ok", "duration", "warnings", "error"}`."""
    canvas_w, canvas_h = _aspect_canvas(aspect_ratio)
    warnings: list[str] = []

    if voice_assignment is None:
        target_dur = float(declared_duration)
    else:
        target_dur = max(0.1, voice_assignment.voice_out - voice_assignment.voice_in)

    visual_filter, vw = _build_visual_filter(
        visual_path, visual_type, target_dur, canvas_w, canvas_h
    )
    warnings.extend(vw)

    # Fade-in/out built into each scene; concat (assemble.py) is hard-cut so
    # neighbouring fades blend into a 0.5s cross transition. Audio NOT faded
    # (would clip voice tail; spec §SPRINT_2.1).
    fade_parts: list[str] = []
    if not is_first:
        fade_parts.append(f"fade=t=in:st=0:d={FADE_DURATION}")
    if not is_last and target_dur > FADE_DURATION:
        fade_parts.append(f"fade=t=out:st={target_dur - FADE_DURATION:.3f}:d={FADE_DURATION}")
    if fade_parts:
        visual_filter = f"{visual_filter}," + ",".join(fade_parts)

    # Subtitle phrases stored in absolute timestamps; shift to scene-relative.
    if subtitle_phrases and voice_assignment is not None:
        rel_phrases = [
            SubtitlePhrase(
                text=p.text,
                start=max(0.0, p.start - voice_assignment.voice_in),
                end=max(0.0, min(target_dur, p.end - voice_assignment.voice_in)),
            )
            for p in subtitle_phrases
        ]
        subtitle_filter = build_subtitle_drawtext_chain(
            rel_phrases, canvas_w, canvas_h, font_path
        )
    else:
        subtitle_filter = ""

    final_video_filter = (
        f"{visual_filter},{subtitle_filter}" if subtitle_filter else visual_filter
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd: list[str] = ["ffmpeg", "-y"]

    is_static = visual_type in VISUAL_STATIC_TYPES and visual_type != "video_grok"
    # image_grok = still: must -loop 1. ken_burns/slideshow are already mp4.
    if visual_type == "image_grok":
        cmd += ["-loop", "1", "-framerate", "30", "-i", str(visual_path)]
    else:
        cmd += ["-i", str(visual_path)]

    has_audio = voice_assignment is not None and voice_file_path is not None
    if has_audio:
        cmd += [
            "-ss", f"{voice_assignment.voice_in:.3f}",
            "-t", f"{target_dur:.3f}",
            "-i", str(voice_file_path),
        ]

    cmd += ["-filter_complex", f"[0:v]{final_video_filter}[v]"]
    cmd += ["-map", "[v]"]
    if has_audio:
        cmd += ["-map", "1:a"]

    cmd += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-t", f"{target_dur:.3f}",
    ]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "192k"]
    cmd += [str(output_path)]

    log.debug(f"[{scene_id}] composite cmd: ffmpeg ... -t {target_dur:.2f} → {output_path.name}")
    # subprocess.run + asyncio.to_thread — avoids create_subprocess_exec quirks
    # on Windows (CMD .bat/.cmd resolution, PATH lookup, codec init).
    result = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=False,
    )

    if result.returncode != 0:
        err = (result.stderr.decode("utf-8", errors="replace") or "").strip()[-800:]
        log.error(f"[{scene_id}] ffmpeg failed: {err}")
        return {"ok": False, "warnings": warnings, "error": err}

    return {"ok": True, "duration": target_dur, "warnings": warnings}
