"""Scan voice folder, return sorted list with cumulative offsets."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger as log


@dataclass
class VoiceFileMeta:
    path: Path
    name: str
    duration: float       # seconds
    offset: float         # cumulative offset in global timeline

    def to_dict(self) -> dict:
        return {
            "file": self.name,
            "duration": self.duration,
            "offset": self.offset,
        }


def get_audio_duration(audio_path: Path) -> float:
    """Use ffprobe to get duration in seconds."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")
    return float(result.stdout.strip())


def scan_voice_folder(voice_dir: Path) -> list[VoiceFileMeta]:
    """Scan voice folder, return sorted voice files with cumulative offsets.

    Sort by filename (ascending). Common conventions supported:
    - voice1.mp3, voice2.mp3, ... (NOTE: voice10 sorts before voice2 — use 0-pad)
    - voice_01.mp3, voice_02.mp3, ...
    - 01.mp3, 02.mp3, ...
    """
    voice_dir = Path(voice_dir)
    if not voice_dir.exists():
        raise FileNotFoundError(f"Voice folder not found: {voice_dir}")

    audio_files: list[Path] = []
    for ext in (".mp3", ".wav", ".m4a", ".flac"):
        audio_files.extend(voice_dir.glob(f"*{ext}"))

    if not audio_files:
        raise ValueError(f"No audio files in {voice_dir}")

    audio_files.sort(key=lambda f: f.name)

    log.info(f"Found {len(audio_files)} voice file(s):")
    for f in audio_files:
        log.info(f"  - {f.name}")

    result: list[VoiceFileMeta] = []
    cursor = 0.0

    for f in audio_files:
        duration = get_audio_duration(f)
        meta = VoiceFileMeta(
            path=f,
            name=f.name,
            duration=duration,
            offset=cursor,
        )
        result.append(meta)
        log.info(f"  {f.name}: {duration:.2f}s (offset {cursor:.2f}s)")
        cursor += duration

    log.info(f"Total voice duration: {cursor:.2f}s")
    return result


def get_total_voice_duration(voice_files: list[VoiceFileMeta]) -> float:
    """Sum all durations."""
    if not voice_files:
        return 0.0
    last = voice_files[-1]
    return last.offset + last.duration


def voice_files_changed(
    voice_dir: Path,
    cached_meta: list[dict],
) -> bool:
    """Detect if voice folder content changed since last scan.

    Compare:
    - File count
    - File names
    - File durations (in case file replaced with same name)
    """
    voice_dir = Path(voice_dir)
    if not voice_dir.exists():
        return bool(cached_meta)

    current = scan_voice_folder(voice_dir)

    if len(current) != len(cached_meta):
        return True

    for cur, cached in zip(current, cached_meta):
        if cur.name != cached.get("file"):
            return True
        if abs(cur.duration - cached.get("duration", 0)) > 0.01:
            return True

    return False
