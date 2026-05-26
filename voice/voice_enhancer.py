"""Deterministic voice pacing helpers.

The first implementation is intentionally conservative: it only inserts
silence after clear punctuation when the existing word gap is too short.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


SENTENCE_PUNCTUATION = (".", "?", "!", "。", "？", "！")
CLAUSE_PUNCTUATION = (":", ";")


def build_voice_pacing_operations(
    source: Path,
    output: Path,
    words: list[dict[str, Any]],
) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []

    for idx, word in enumerate(words[:-1]):
        text = str(word.get("word") or "").strip()
        if not text:
            continue
        end = float(word.get("end", 0.0) or 0.0)
        next_start = float(words[idx + 1].get("start", end) or end)
        gap_ms = max(0, int(round((next_start - end) * 1000)))

        if text.endswith(SENTENCE_PUNCTUATION) and gap_ms < 180:
            operations.append(
                {
                    "type": "insert_pause",
                    "after_word_i": idx,
                    "at_sec": round(end, 3),
                    "insert_ms": max(0, 500 - gap_ms),
                    "reason": "missing_sentence_pause",
                }
            )
        elif text.endswith(CLAUSE_PUNCTUATION) and gap_ms < 120:
            operations.append(
                {
                    "type": "insert_pause",
                    "after_word_i": idx,
                    "at_sec": round(end, 3),
                    "insert_ms": max(0, 320 - gap_ms),
                    "reason": "missing_strong_clause_pause",
                }
            )

    return {
        "version": "voice_pacing_operations.v1",
        "source": str(source).replace("\\", "/"),
        "output": str(output).replace("\\", "/"),
        "operations": operations,
    }


def load_whisper_words(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    words = data.get("words")
    if not isinstance(words, list):
        raise ValueError(f"Whisper words file has no words list: {path}")
    return words


def save_voice_pacing_plan(plan: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_voice_pacing_operations(
    source: Path,
    output: Path,
    plan: dict[str, Any],
) -> dict[str, Any]:
    source = Path(source)
    output = Path(output)
    operations = [
        op for op in plan.get("operations", [])
        if op.get("type") == "insert_pause" and float(op.get("insert_ms", 0) or 0) > 0
    ]
    output.parent.mkdir(parents=True, exist_ok=True)

    if not operations:
        shutil.copy2(source, output)
        return {
            "version": "voice_enhance_report.v1",
            "source": str(source).replace("\\", "/"),
            "output": str(output).replace("\\", "/"),
            "operation_count": 0,
            "inserted_pause_ms": 0,
        }

    filter_complex, segment_count, inserted_ms = _build_insert_pause_filter(operations)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:a",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "2",
        str(output),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg voice enhance failed: {(result.stderr or '')[-1000:]}")
    if not output.exists():
        raise RuntimeError(f"ffmpeg voice enhance did not create output: {output}")

    return {
        "version": "voice_enhance_report.v1",
        "source": str(source).replace("\\", "/"),
        "output": str(output).replace("\\", "/"),
        "operation_count": len(operations),
        "inserted_pause_ms": inserted_ms,
        "segment_count": segment_count,
    }


def _build_insert_pause_filter(operations: list[dict[str, Any]]) -> tuple[str, int, int]:
    ordered = sorted(operations, key=lambda op: float(op.get("at_sec", 0.0) or 0.0))
    parts: list[str] = []
    labels: list[str] = []
    start = 0.0
    inserted_ms = 0
    seg_i = 0

    for op_i, op in enumerate(ordered):
        at_sec = max(start, float(op.get("at_sec", start) or start))
        pause_ms = int(round(float(op.get("insert_ms", 0) or 0)))
        if at_sec > start:
            label = f"s{seg_i}"
            parts.append(
                f"[0:a]atrim=start={start:.3f}:end={at_sec:.3f},"
                f"asetpts=PTS-STARTPTS[{label}]"
            )
            labels.append(label)
            seg_i += 1
        silence = f"sil{op_i}"
        parts.append(
            f"anullsrc=channel_layout=stereo:sample_rate=44100:"
            f"d={pause_ms / 1000:.3f}[{silence}]"
        )
        labels.append(silence)
        inserted_ms += pause_ms
        start = at_sec

    label = f"s{seg_i}"
    parts.append(f"[0:a]atrim=start={start:.3f},asetpts=PTS-STARTPTS[{label}]")
    labels.append(label)
    parts.append(
        "".join(f"[{label}]" for label in labels)
        + f"concat=n={len(labels)}:v=0:a=1[out]"
    )
    return ";".join(parts), len(labels), inserted_ms
