"""BGM picker + ffmpeg filter chain (loop, trim, volume, fade)."""

from __future__ import annotations

from pathlib import Path


def pick_bgm_files(bgm_dir: Path | None) -> list[Path]:
    """Sorted list of mp3/wav files in the BGM folder. Empty if dir missing."""
    if bgm_dir is None or not bgm_dir.exists():
        return []
    return sorted(bgm_dir.glob("*.mp3")) + sorted(bgm_dir.glob("*.wav"))


def build_bgm_filter(
    target_duration: float,
    bgm_db: float = -15.0,
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
