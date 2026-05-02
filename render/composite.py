"""Composite a single scene clip: visual + voice slice (no subtitles)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger as log

from render.visual_fit import FPS, build_visual_filter_with_fit
from render.voice_slicer import (
    get_silent_audio_args,
    get_voice_slice_args,
)


_STATIC_VISUAL_TYPES = {"image_grok"}
_STATIC_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def composite_scene(
    scene: dict,                 # scenes.json scene dict (id, visual_type, effect, duration)
    voice_scene: dict,           # voice_mapping scene dict
    visual_path: Path,
    voice_files: list[dict],     # voice_mapping["voice_files"]
    project_root: Path,
    output_path: Path,
    width: int,
    height: int,
    fps: int = FPS,
) -> Path:
    """Render a single scene clip (visual + audio, no subtitles).

    Output is `duration_adjusted` long, h264 + aac, sized to (width, height).
    """
    visual_path = Path(visual_path)
    output_path = Path(output_path)
    project_root = Path(project_root)

    duration_adjusted = float(voice_scene["duration_adjusted"])
    duration_design = float(voice_scene["duration_original"])
    render_duration = float(voice_scene.get("render_duration") or duration_adjusted)
    visual_type = scene["visual_type"]
    effect = scene.get("effect", "no_effect") or "no_effect"

    log.info(
        f"composite {scene['id']}: visual={visual_type} effect={effect} "
        f"design={duration_design}s adjusted={duration_adjusted}s "
        f"render={render_duration}s mode={voice_scene.get('render_mode', 'voice')}"
    )

    # The visual is fitted to render_duration (what actually gets played);
    # ratio used by ken-burns/zoom kept against design so motion still feels
    # designed.
    visual_filter = build_visual_filter_with_fit(
        visual_type=visual_type,
        duration_design=duration_design,
        duration_adjusted=render_duration,
        effect=effect,
        width=width,
        height=height,
        fps=fps,
    )

    is_static = (
        visual_type in _STATIC_VISUAL_TYPES
        or visual_path.suffix.lower() in _STATIC_IMAGE_EXTS
    )
    if is_static:
        visual_input = ["-loop", "1", "-i", str(visual_path)]
    else:
        visual_input = ["-i", str(visual_path)]

    # Re-fit the visual filter with the actual source kind so slideshow .mp4
    # routes through the video pipeline (setpts/tpad + optional zoompan tail)
    # instead of the still-image zoompan path.
    visual_filter = build_visual_filter_with_fit(
        visual_type=visual_type,
        duration_design=duration_design,
        duration_adjusted=render_duration,
        effect=effect,
        width=width,
        height=height,
        fps=fps,
        source_is_video=not is_static,
    )

    cleanup_files: list[Path] = []
    if voice_scene.get("is_silent"):
        audio_input, audio_filter = get_silent_audio_args(render_duration)
    else:
        voice_in = float(voice_scene["voice_in"])
        voice_out = float(voice_scene["voice_out"])
        voice_dur = max(0.0, voice_out - voice_in)
        audio_input, audio_filter, concat_list = get_voice_slice_args(
            voice_files=voice_files,
            voice_in=voice_in,
            voice_out=voice_out,
            project_root=project_root,
        )
        cleanup_files.append(concat_list)
        # Pad silence at the tail when the user wants a longer render than
        # the voice actually covers (design / custom modes).
        if render_duration > voice_dur + 0.01:
            pad_dur = render_duration - voice_dur
            audio_filter = f"{audio_filter},apad=pad_dur={pad_dur:.3f}"
            log.info(
                f"  audio pad: voice={voice_dur:.2f}s render={render_duration:.2f}s "
                f"pad +{pad_dur:.2f}s"
            )

    filter_complex = (
        f"[0:v]{visual_filter}[v];"
        f"[1:a]{audio_filter}[a]"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *visual_input,
        *audio_input,
        "-filter_complex", filter_complex,
        "-map", "[v]",
        "-map", "[a]",
        "-t", f"{render_duration:.3f}",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", str(fps),
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=600,
        )
    finally:
        for f in cleanup_files:
            try:
                f.unlink()
                f.parent.rmdir()
            except OSError:
                pass

    if result.returncode != 0:
        log.error(f"composite {scene['id']} failed: {(result.stderr or '')[-1500:]}")
        raise RuntimeError(f"FFmpeg composite failed for {scene['id']}")

    log.info(f"  -> {output_path.name}")
    return output_path
