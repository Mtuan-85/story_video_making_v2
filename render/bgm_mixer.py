"""BGM picker + ffmpeg filter chain (loop, trim, volume, fade)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def pick_bgm_files(bgm_dir: Path | None) -> list[Path]:
    """Sorted list of mp3/wav files in the BGM folder. Empty if dir missing."""
    if bgm_dir is None or not bgm_dir.exists():
        return []
    return sorted(bgm_dir.glob("*.mp3")) + sorted(bgm_dir.glob("*.wav"))


def _ass_filter_path(ass_path: Path) -> str:
    return str(Path(ass_path).resolve()).replace("\\", "/").replace(":", "\\:")


def _ffprobe_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}")
    return float((result.stdout or "0").strip())


def build_bgm_filter(
    target_duration: float,
    bgm_db: float = -17.0,
    fade_in: float = 1.0,
    fade_out: float = 2.0,
) -> str:
    """Build the ffmpeg filter for the BGM input.

    Order: loop → trim to target → volume → fade in/out. Use `astream_loop=-1`
    so ffmpeg loops cleanly regardless of BGM length.
    """
    fade_out_start = max(0.0, target_duration - fade_out)
    return (
        f"aloop=loop=-1:size=2147483647,"
        f"atrim=duration={target_duration:.3f},"
        f"asetpts=N/SR/TB,"
        f"volume={bgm_db}dB,"
        f"afade=t=in:st=0:d={fade_in:.2f},"
        f"afade=t=out:st={fade_out_start:.2f}:d={fade_out:.2f}"
    )


def build_bgm_mix_command(
    input_video: Path,
    ass_path: Path | None,
    output_video: Path,
    bgm_files: list[Path],
    target_duration: float,
    bgm_db: float = -17.0,
    fade_sec: float = 2.0,
) -> list[str]:
    """Build one ffmpeg command that burns subtitles and mixes continuous BGM."""
    if not bgm_files:
        raise ValueError("No BGM files to mix")

    input_video = Path(input_video)
    output_video = Path(output_video)
    bgm_files = sorted(Path(p) for p in bgm_files)

    input_args: list[str] = ["-i", str(input_video)]
    for bgm in bgm_files:
        input_args.extend(["-i", str(bgm)])

    bgm_inputs: list[str] = []
    if ass_path is not None:
        video_filter = f"[0:v]subtitles='{_ass_filter_path(Path(ass_path))}'[v]"
    else:
        video_filter = "[0:v]copy[v]"
    filters: list[str] = [
        video_filter,
        "[0:a]aformat=sample_fmts=fltp:channel_layouts=stereo[voice]",
    ]
    for idx, _bgm in enumerate(bgm_files, start=1):
        label = f"bgm{idx}"
        filters.append(
            f"[{idx}:a]aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo[{label}]"
        )
        bgm_inputs.append(f"[{label}]")

    filter_body = build_bgm_filter(
        target_duration=target_duration,
        bgm_db=bgm_db,
        fade_in=fade_sec,
        fade_out=fade_sec,
    )
    filters.extend(
        [
            f"{''.join(bgm_inputs)}concat=n={len(bgm_files)}:v=0:a=1[bgm_cycle]",
            f"[bgm_cycle]{filter_body}[bgm]",
            "[voice][bgm]amix=inputs=2:duration=first:normalize=0[a]",
        ]
    )

    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *input_args,
        "-filter_complex", ";".join(filters),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_video),
    ]


def build_master_audio_mix_command(
    input_video: Path,
    master_audio: Path,
    ass_path: Path | None,
    output_video: Path,
    bgm_files: list[Path],
    target_duration: float,
    bgm_db: float = -17.0,
    fade_sec: float = 2.0,
) -> list[str]:
    """Build ffmpeg command: video-only + normalized master voice + optional BGM."""
    input_video = Path(input_video)
    master_audio = Path(master_audio)
    output_video = Path(output_video)
    bgm_files = sorted(Path(p) for p in bgm_files)

    input_args: list[str] = ["-i", str(input_video), "-i", str(master_audio)]
    for bgm in bgm_files:
        input_args.extend(["-i", str(bgm)])

    if ass_path is not None:
        video_filter = f"[0:v]subtitles='{_ass_filter_path(Path(ass_path))}'[v]"
    else:
        video_filter = "[0:v]copy[v]"

    filters: list[str] = [
        video_filter,
        "[1:a]aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "loudnorm=I=-16:TP=-1.5:LRA=11[voice]",
    ]

    if bgm_files:
        bgm_inputs: list[str] = []
        for idx, _bgm in enumerate(bgm_files, start=2):
            label = f"bgm{idx - 1}"
            filters.append(
                f"[{idx}:a]aresample=48000,"
                f"aformat=sample_fmts=fltp:channel_layouts=stereo[{label}]"
            )
            bgm_inputs.append(f"[{label}]")
        filter_body = build_bgm_filter(
            target_duration=target_duration,
            bgm_db=bgm_db,
            fade_in=fade_sec,
            fade_out=fade_sec,
        )
        filters.extend(
            [
                f"{''.join(bgm_inputs)}concat=n={len(bgm_files)}:v=0:a=1[bgm_cycle]",
                f"[bgm_cycle]{filter_body}[bgm]",
                "[voice][bgm]amix=inputs=2:duration=first:normalize=0[a]",
            ]
        )
    else:
        filters.append("[voice]anull[a]")

    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        *input_args,
        "-filter_complex", ";".join(filters),
        "-map", "[v]",
        "-map", "[a]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_video),
    ]


def burn_subtitle_mix_master_audio_bgm(
    input_video: Path,
    master_audio: Path,
    ass_path: Path | None,
    output_video: Path,
    bgm_dir: Path | None,
    bgm_db: float = -17.0,
    fade_sec: float = 2.0,
) -> Path:
    """Final pass for native timeline render: master voice stays continuous."""
    input_video = Path(input_video)
    master_audio = Path(master_audio)
    ass_path = Path(ass_path) if ass_path is not None else None
    output_video = Path(output_video)
    output_video.parent.mkdir(parents=True, exist_ok=True)

    bgm_files = pick_bgm_files(bgm_dir)
    duration = _ffprobe_duration(input_video)
    cmd = build_master_audio_mix_command(
        input_video=input_video,
        master_audio=master_audio,
        ass_path=ass_path if ass_path is not None and ass_path.exists() else None,
        output_video=output_video,
        bgm_files=bgm_files,
        target_duration=duration,
        bgm_db=bgm_db,
        fade_sec=fade_sec,
    )
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg master audio mix failed: {(result.stderr or '')[-1500:]}")
    return output_video


def burn_subtitle_and_mix_bgm(
    input_video: Path,
    ass_path: Path,
    output_video: Path,
    bgm_dir: Path | None,
    bgm_db: float = -17.0,
    fade_sec: float = 2.0,
) -> Path:
    """Burn ASS and optionally mix BGM in a single final ffmpeg pass."""
    input_video = Path(input_video)
    ass_path = Path(ass_path)
    output_video = Path(output_video)

    bgm_files = pick_bgm_files(bgm_dir)
    if not bgm_files:
        if not ass_path.exists():
            shutil.copy(input_video, output_video)
            return output_video
        from render.assemble import apply_ass_subtitle

        return apply_ass_subtitle(input_video, ass_path, output_video)

    output_video.parent.mkdir(parents=True, exist_ok=True)
    duration = _ffprobe_duration(input_video)
    cmd = build_bgm_mix_command(
        input_video=input_video,
        ass_path=ass_path if ass_path.exists() else None,
        output_video=output_video,
        bgm_files=bgm_files,
        target_duration=duration,
        bgm_db=bgm_db,
        fade_sec=fade_sec,
    )
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg BGM/subtitle mix failed: {(result.stderr or '')[-1500:]}")
    return output_video
