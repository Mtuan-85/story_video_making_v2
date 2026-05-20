"""Composite a single scene clip: visual + voice slice (no subtitles).

Voice-led timeline: each scene's render = voice part (per render_mode) +
freeze-frame tail for the natural pause to the next scene. The tail keeps
both visuals and audio aligned with the original whisper timestamps so we
never have to chop visual content to fit voice.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from loguru import logger as log

from render.visual_fit import FPS, build_visual_filter_with_fit
from render.voice_slicer import (
    get_silent_audio_args,
    get_voice_slice_args,
)


_STATIC_VISUAL_TYPES = {"Image"}
_STATIC_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _voice_part_duration(voice_scene: dict, voice_dur: float, design_dur: float) -> float:
    """Duration of the voice section (before any freeze-pause tail)."""
    if voice_scene.get("is_silent"):
        return design_dur
    mode = voice_scene.get("render_mode") or "voice"
    if mode == "voice":
        return voice_dur
    if mode == "design":
        return design_dur
    # custom
    return float(voice_scene.get("custom_duration") or design_dur)


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

    Total clip duration = voice_part_dur + freeze_pause_after. The visual
    is fitted to voice_part_dur, then a clone-frame tpad freezes the last
    frame for the freeze pause; audio is padded with apad to match.
    """
    visual_path = Path(visual_path)
    output_path = Path(output_path)
    project_root = Path(project_root)

    duration_design = float(voice_scene["duration_original"])
    is_silent = bool(voice_scene.get("is_silent"))
    if is_silent:
        voice_in = 0.0
        voice_out = 0.0
        voice_dur = 0.0
    else:
        voice_in = float(voice_scene["voice_in"])
        voice_out = float(voice_scene["voice_out"])
        voice_dur = max(0.0, voice_out - voice_in)

    voice_part_dur = _voice_part_duration(voice_scene, voice_dur, duration_design)
    freeze_pause = max(0.0, float(voice_scene.get("freeze_pause_after") or 0.0))
    total_render_dur = voice_part_dur + freeze_pause

    visual_type = scene["visual_type"]
    effect = scene.get("effect", "no_effect") or "no_effect"

    log.info(
        f"composite {scene['id']}: visual={visual_type} effect={effect} "
        f"design={duration_design}s voice_part={voice_part_dur:.2f}s "
        f"freeze_pause={freeze_pause:.2f}s total={total_render_dur:.2f}s "
        f"mode={voice_scene.get('render_mode', 'voice')}"
    )

    is_static = (
        visual_type in _STATIC_VISUAL_TYPES
        or visual_path.suffix.lower() in _STATIC_IMAGE_EXTS
    )
    if is_static:
        visual_input = ["-loop", "1", "-i", str(visual_path)]
    else:
        visual_input = ["-i", str(visual_path)]

    # Visual is fitted to the voice part only; tpad below freezes the last
    # frame for the freeze pause without retiming the motion.
    visual_filter = build_visual_filter_with_fit(
        visual_type=visual_type,
        duration_design=duration_design,
        duration_adjusted=voice_part_dur,
        effect=effect,
        width=width,
        height=height,
        fps=fps,
        source_is_video=not is_static,
    )
    if freeze_pause > 0:
        visual_filter = (
            f"{visual_filter},tpad=stop_mode=clone:stop_duration={freeze_pause:.3f}"
        )

    cleanup_files: list[Path] = []
    if is_silent:
        audio_input, audio_filter = get_silent_audio_args(total_render_dur)
    else:
        audio_input, audio_filter, concat_list = get_voice_slice_args(
            voice_files=voice_files,
            voice_in=voice_in,
            voice_out=voice_out,
            project_root=project_root,
        )
        cleanup_files.append(concat_list)
        # Pad silence for (a) extending past voice in design/custom mode and
        # (b) the freeze-frame pause.
        extra_silence = freeze_pause
        if voice_part_dur > voice_dur + 0.01:
            extra_silence += voice_part_dur - voice_dur
        if extra_silence > 0.001:
            audio_filter = f"{audio_filter},apad=pad_dur={extra_silence:.3f}"
            log.info(
                f"  audio pad: voice={voice_dur:.2f}s pad +{extra_silence:.2f}s "
                f"(freeze={freeze_pause:.2f}s)"
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
        "-t", f"{total_render_dur:.3f}",
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
