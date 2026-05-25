"""Build master_voice.wav by concatenating beat MP3s + synthesized silence
between them (pause_after_sec).

Per sprint_1 spec §6:
  - Output WAV (timing-stable, no MP3 re-encode drift)
  - Consistent sample rate (default 48000Hz)
  - Stereo (Whisper handles mono/stereo, stereo is the friendly default)
  - Validation: abs(measured_master - expected_total) <= 0.05s

Strategy:
  Use ffmpeg filter_complex with anullsrc segments interleaved between
  beat audio inputs. Each input is normalized to the target sample rate
  + channel layout before concat. anullsrc generates silence inline so
  we don't have to write temp silence files.

  Example for 3 beats with pauses [0.5, 1.5, 0]:

    -i beat-01.mp3
    -f lavfi -t 0.5 -i anullsrc=sr=48000:cl=stereo
    -i beat-02.mp3
    -f lavfi -t 1.5 -i anullsrc=sr=48000:cl=stereo
    -i beat-03.mp3
    # (no trailing silence for last beat if pause_after_sec == 0)
    -filter_complex "[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];
                     [1:a]aformat=channel_layouts=stereo[a1];
                     ...
                     [a0][a1][a2][a3][a4]concat=n=5:v=0:a=1[out]"
    -map "[out]"
    -c:a pcm_s16le master_voice.wav

Trailing pause: if last beat has pause_after_sec > 0 we still append
the silence so the master duration matches the beat timeline exactly.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger as log

from voice.beat_timeline import BeatTiming, ffprobe_duration


DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNEL_LAYOUT = "stereo"
DURATION_TOLERANCE_SEC = 0.05      # sprint_1 §6 acceptance: ±0.05s


@dataclass
class MasterAudioResult:
    ok: bool
    output_path: Optional[Path]
    expected_duration: float
    measured_duration: float
    delta_sec: float
    error: Optional[str] = None


def build_master_audio(
    timed_beats: list[BeatTiming],
    output_path: Path,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    channel_layout: str = DEFAULT_CHANNEL_LAYOUT,
) -> MasterAudioResult:
    """Concat beat MP3s + synthesized silence → master WAV.

    Args:
        timed_beats: from build_beat_timeline (already measured)
        output_path: where to write master_voice.wav

    Returns:
        MasterAudioResult with verification details.
    """
    if not timed_beats:
        return MasterAudioResult(
            ok=False, output_path=None,
            expected_duration=0, measured_duration=0, delta_sec=0,
            error="No beats provided",
        )

    expected_total = timed_beats[-1].pause_out
    log.info(
        f"Building master audio: {len(timed_beats)} beats → {output_path.name} "
        f"(expected {expected_total:.2f}s, sr={sample_rate}Hz {channel_layout})"
    )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build ffmpeg command
    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]

    # Inputs interleaved: beat-N, silence-after-N (if > 0), beat-N+1, ...
    # Track input indices for filter_complex
    input_idx = 0
    segment_labels: list[str] = []
    filter_parts: list[str] = []

    for beat in timed_beats:
        # Beat audio input
        cmd.extend(["-i", str(beat.voice_file)])
        beat_input_idx = input_idx
        input_idx += 1

        # Normalize this beat input
        seg_label = f"s{len(segment_labels)}"
        filter_parts.append(
            f"[{beat_input_idx}:a]"
            f"aresample={sample_rate},"
            f"aformat=sample_fmts=s16:channel_layouts={channel_layout}"
            f"[{seg_label}]"
        )
        segment_labels.append(seg_label)

        # Silence after this beat (if > 0)
        if beat.pause_after_sec > 0:
            cmd.extend([
                "-f", "lavfi",
                "-t", f"{beat.pause_after_sec:.3f}",
                "-i", f"anullsrc=channel_layout={channel_layout}:sample_rate={sample_rate}",
            ])
            silence_input_idx = input_idx
            input_idx += 1
            seg_label = f"s{len(segment_labels)}"
            filter_parts.append(
                f"[{silence_input_idx}:a]"
                f"aformat=sample_fmts=s16:channel_layouts={channel_layout}"
                f"[{seg_label}]"
            )
            segment_labels.append(seg_label)

    # Concat all segments
    concat_inputs = "".join(f"[{lbl}]" for lbl in segment_labels)
    filter_parts.append(
        f"{concat_inputs}concat=n={len(segment_labels)}:v=0:a=1[out]"
    )

    filter_complex = ";".join(filter_parts)

    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "pcm_s16le",     # uncompressed WAV
        "-ar", str(sample_rate),
        "-ac", "2" if channel_layout == "stereo" else "1",
        str(output_path),
    ])

    log.debug(f"ffmpeg cmd ({len(cmd)} args): {' '.join(cmd[:6])}...")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=300,
        )
    except subprocess.TimeoutExpired:
        return MasterAudioResult(
            ok=False, output_path=output_path,
            expected_duration=expected_total, measured_duration=0, delta_sec=0,
            error="ffmpeg timeout (300s)",
        )

    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-1500:]
        log.error(f"ffmpeg master-audio failed:\n{stderr_tail}")
        return MasterAudioResult(
            ok=False, output_path=output_path,
            expected_duration=expected_total, measured_duration=0, delta_sec=0,
            error=f"ffmpeg failed (rc={result.returncode}): {stderr_tail[-300:]}",
        )

    if not output_path.exists():
        return MasterAudioResult(
            ok=False, output_path=output_path,
            expected_duration=expected_total, measured_duration=0, delta_sec=0,
            error="Output file not created",
        )

    # Verify duration
    try:
        measured = ffprobe_duration(output_path)
    except Exception as e:
        return MasterAudioResult(
            ok=False, output_path=output_path,
            expected_duration=expected_total, measured_duration=0, delta_sec=0,
            error=f"ffprobe verification failed: {e}",
        )

    delta = measured - expected_total

    if abs(delta) > DURATION_TOLERANCE_SEC:
        log.warning(
            f"Master audio duration drift: expected {expected_total:.3f}s, "
            f"measured {measured:.3f}s, delta {delta:+.3f}s "
            f"(tolerance ±{DURATION_TOLERANCE_SEC}s)"
        )
    else:
        log.info(
            f"Master audio OK: {output_path.name} "
            f"({measured:.3f}s, delta {delta:+.3f}s within tolerance)"
        )

    return MasterAudioResult(
        ok=abs(delta) <= DURATION_TOLERANCE_SEC,
        output_path=output_path,
        expected_duration=expected_total,
        measured_duration=measured,
        delta_sec=delta,
        error=None if abs(delta) <= DURATION_TOLERANCE_SEC
              else f"Duration drift {delta:+.3f}s exceeds ±{DURATION_TOLERANCE_SEC}s",
    )
