"""Whisper on master_voice.wav (single file, global timestamps) + per-beat
word filtering.

Per sprint_1 §7: when `whisper_mode == "master_audio"`, timestamps are
GLOBAL — DO NOT add beat.voice_in again. Words land directly on the
master timeline.

Per §8.1: filter words to a beat window with small tolerance.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

from loguru import logger as log

from voice.beat_timeline import BeatTiming


# Per spec §4 / §8.1
BOUNDARY_TOLERANCE_SEC = 0.05


async def transcribe_master_audio(
    master_path: Path,
    language: str = "en",
    model_name: str = "base",
) -> list[dict]:
    """Transcribe master_voice.wav once. Returns words with GLOBAL timestamps.

    Reuses the in-tree whisper subprocess so torch's OpenMP runtime stays
    isolated from the qasync main loop (same reason as transcribe_all_voice_files).

    Returns list of:
        {word, start, end, source_file}

    `start`/`end` are global (relative to master_voice.wav, which already
    encodes beat order + synthetic silences). DO NOT add any offsets.
    """
    master_path = Path(master_path)
    if not master_path.exists():
        raise FileNotFoundError(f"Master audio not found: {master_path}")

    job = {
        "model": model_name,
        "language": language,
        "files": [
            {"path": str(master_path), "offset": 0.0, "name": master_path.name},
        ],
    }
    payload = json.dumps(job, ensure_ascii=False)

    project_root = Path(__file__).resolve().parents[1]
    log.info(
        f"Whisper master audio: {master_path.name} "
        f"(model={model_name}, lang={language})"
    )

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "voice.whisper_subprocess",
        cwd=str(project_root),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate(payload.encode("utf-8"))

    if proc.returncode != 0:
        err = (stderr.decode("utf-8", errors="replace") or "").strip()
        raise RuntimeError(
            f"Whisper master audio subprocess failed (rc={proc.returncode}): "
            f"{err[-1500:]}"
        )

    text = stdout.decode("utf-8", errors="replace").strip()
    try:
        words = json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Whisper subprocess produced non-JSON output: {text[:300]!r}"
        ) from e

    log.info(f"Whisper master: {len(words)} words on master timeline")
    return words


def filter_words_by_beat(
    whisper_words: list[dict],
    beat: BeatTiming,
    tolerance_sec: float = BOUNDARY_TOLERANCE_SEC,
) -> list[dict]:
    """Return words whose [start, end] lie within beat's [voice_in, voice_out].

    Hard rule (spec §8.1): DO NOT include words inside beat.pause_in →
    beat.pause_out. Tolerance is symmetric and small (±0.05s).

    Returns a NEW list (does not mutate input). Each word dict gets a
    `_beat_word_idx` field added so downstream matchers can refer back to
    the position within the beat window.
    """
    in_lo = beat.voice_in - tolerance_sec
    in_hi = beat.voice_out + tolerance_sec
    result = []
    for w in whisper_words:
        w_start = float(w.get("start", 0))
        w_end = float(w.get("end", 0))
        if w_start >= in_lo and w_end <= in_hi:
            # shallow copy + add local index after filtering
            result.append(dict(w))
    # add local index AFTER filtering so index reflects beat-local position
    for i, w in enumerate(result):
        w["_beat_word_idx"] = i
    return result


def detect_double_offset(
    whisper_words: list[dict],
    beats: list[BeatTiming],
) -> Optional[str]:
    """Sanity check: warn if word timestamps look offset twice.

    If all words have start >= max(beat.voice_in), they may have been
    erroneously shifted by beat offset on top of global timestamps.

    Returns a warning string or None.
    """
    if not whisper_words or not beats:
        return None

    max_beat_in = max(b.voice_in for b in beats)
    last_beat_out = beats[-1].voice_out

    # Check if any word lands EARLIER than any beat.voice_in (sanity: words
    # should span the whole timeline 0 → total_duration).
    first_word_start = min(float(w.get("start", 0)) for w in whisper_words)
    if first_word_start > max_beat_in:
        return (
            f"possible_double_timestamp_offset: first word at "
            f"{first_word_start:.2f}s exceeds max beat.voice_in {max_beat_in:.2f}s — "
            f"timestamps may have been offset twice"
        )

    # Check if words extend WAY past last beat (suggests offset added)
    last_word_end = max(float(w.get("end", 0)) for w in whisper_words)
    if last_word_end > last_beat_out * 1.5:
        return (
            f"possible_double_timestamp_offset: last word at "
            f"{last_word_end:.2f}s far exceeds master duration {last_beat_out:.2f}s"
        )

    return None
