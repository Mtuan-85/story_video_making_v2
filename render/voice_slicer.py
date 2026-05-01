"""Slice voice audio for one scene from possibly multiple voice files.

Strategy: ffmpeg concat demuxer joins voice files on-the-fly into a single
virtual stream, then atrim slices the global [voice_in, voice_out] window.
For silent scenes, anullsrc generates silence of the right duration.
"""

from __future__ import annotations

import tempfile
from pathlib import Path


def build_voice_concat_list(voice_files: list[dict], project_root: Path) -> Path:
    """Write a concat-demuxer list file to a temp directory and return its path.

    Format:
        file 'C:/abs/path/voice_01.mp3'
        file 'C:/abs/path/voice_02.mp3'

    The list file lives in a tempdir; caller is responsible for unlinking
    it (and the parent dir) after ffmpeg finishes.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="voice_concat_"))
    list_file = tmp_dir / "voice_concat.txt"

    project_root = Path(project_root).resolve()
    voice_root = project_root / "voice"

    lines: list[str] = []
    for vf in voice_files:
        full_path = (voice_root / vf["file"]).resolve()
        path_str = str(full_path).replace("\\", "/").replace("'", r"\'")
        lines.append(f"file '{path_str}'")

    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return list_file


def get_voice_slice_args(
    voice_files: list[dict],
    voice_in: float,
    voice_out: float,
    project_root: Path,
) -> tuple[list[str], str, Path]:
    """Build ffmpeg input args + audio filter for slicing the voice window.

    Returns:
        (input_args, audio_filter, concat_list_path_to_cleanup)
    """
    concat_list = build_voice_concat_list(voice_files, project_root)

    input_args = [
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
    ]

    duration = max(0.0, voice_out - voice_in)
    audio_filter = (
        f"atrim=start={voice_in:.3f}:duration={duration:.3f},"
        f"asetpts=PTS-STARTPTS"
    )

    return input_args, audio_filter, concat_list


def get_silent_audio_args(duration: float) -> tuple[list[str], str]:
    """Build ffmpeg input + filter for a silent-scene audio stream."""
    input_args = [
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", f"{duration:.3f}",
    ]
    audio_filter = "anull"
    return input_args, audio_filter
