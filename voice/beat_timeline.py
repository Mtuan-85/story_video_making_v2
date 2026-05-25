"""Build exact beat-level timeline using ffprobe per beat MP3.

Per sprint_1 spec §5: global cursor is used ONLY here for beat timing.
Scene matching MUST NOT use this global cursor — it gets reset per beat.

Output (per beat):
    beat.voice_in   = cursor at start
    beat.voice_out  = voice_in + measured_duration
    beat.pause_in   = voice_out
    beat.pause_out  = pause_in + pause_after_sec
    cursor          = pause_out  # advance to next beat
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger as log

from voice.s5_loader import Beat


@dataclass
class BeatTiming:
    """Timed beat — same fields as Beat + measured timing."""
    beat_id: str
    beat_index: int
    voice_file: Path
    script: str
    pause_after_sec: float
    scene_ids: list[str]
    beat_role: Optional[str]
    emotion: Optional[str]
    # Timing (added here)
    measured_duration: float        # from ffprobe
    voice_in: float                 # cumulative offset in master timeline
    voice_out: float                # voice_in + measured_duration
    pause_in: float                 # = voice_out
    pause_out: float                # pause_in + pause_after_sec

    def to_dict(self) -> dict:
        return {
            "beat_id": self.beat_id,
            "beat_index": self.beat_index,
            "voice_file": str(self.voice_file).replace("\\", "/"),
            "beat_role": self.beat_role,
            "emotion": self.emotion,
            "voice_in": round(self.voice_in, 3),
            "voice_out": round(self.voice_out, 3),
            "voice_duration": round(self.measured_duration, 3),
            "pause_after_sec": round(self.pause_after_sec, 3),
            "pause_in": round(self.pause_in, 3),
            "pause_out": round(self.pause_out, 3),
            "scene_ids": list(self.scene_ids),
        }


@dataclass
class BeatTimelineResult:
    ok: bool
    beats: list[BeatTiming]
    total_duration: float           # = beats[-1].pause_out
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ffprobe_duration(audio_path: Path) -> float:
    """Return media duration in seconds (raise on failure)."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=30,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {audio_path.name}: {result.stderr}")
    out = (result.stdout or "").strip()
    if not out:
        raise RuntimeError(f"ffprobe returned no duration for {audio_path.name}")
    return float(out)


def build_beat_timeline(beats: list[Beat]) -> BeatTimelineResult:
    """Build exact beat-level timeline from per-beat MP3 durations.

    Cursor starts at 0.0. For each beat (in order):
      voice_in  = cursor
      voice_out = cursor + measured_duration (ffprobe)
      pause_in  = voice_out
      pause_out = pause_in + pause_after_sec
      cursor    = pause_out

    Per spec §5: this is the ONLY place a global cursor is used.
    """
    errors: list[str] = []
    warnings: list[str] = []
    timed: list[BeatTiming] = []

    if not beats:
        return BeatTimelineResult(
            ok=False, beats=[], total_duration=0.0,
            errors=["No beats provided"], warnings=[],
        )

    cursor = 0.0
    for beat in beats:
        try:
            dur = ffprobe_duration(beat.voice_file)
        except Exception as e:
            errors.append(f"{beat.beat_id}: ffprobe failed ({e})")
            continue

        if dur <= 0:
            errors.append(f"{beat.beat_id}: zero/negative duration ({dur})")
            continue

        voice_in = cursor
        voice_out = cursor + dur
        pause_in = voice_out
        pause_out = pause_in + beat.pause_after_sec

        timed.append(BeatTiming(
            beat_id=beat.beat_id,
            beat_index=beat.beat_index,
            voice_file=beat.voice_file,
            script=beat.script,
            pause_after_sec=beat.pause_after_sec,
            scene_ids=list(beat.scene_ids),
            beat_role=beat.beat_role,
            emotion=beat.emotion,
            measured_duration=dur,
            voice_in=voice_in,
            voice_out=voice_out,
            pause_in=pause_in,
            pause_out=pause_out,
        ))

        cursor = pause_out

    total_duration = cursor
    ok = not errors

    if ok:
        log.info(
            f"Beat timeline built: {len(timed)} beats, "
            f"total duration {total_duration:.2f}s "
            f"(voice {sum(b.measured_duration for b in timed):.2f}s + "
            f"pauses {sum(b.pause_after_sec for b in timed):.2f}s)"
        )
    else:
        log.error(f"Beat timeline FAILED: {len(errors)} error(s)")

    return BeatTimelineResult(
        ok=ok,
        beats=timed,
        total_duration=total_duration,
        errors=errors,
        warnings=warnings,
    )
