"""Whisper CLI wrapper — transcribe audio to JSON with word-level timestamps."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger as log


def run_whisper(
    audio_path: Path,
    output_dir: Path,
    model: str = "base",
    language: str = "en",
) -> dict[str, Any]:
    """Run Whisper CLI on `audio_path`, return parsed JSON.

    Output JSON shape:
        {
            "text": "<full transcript>",
            "language": "<lang>",
            "segments": [
                {"id", "start", "end", "text",
                 "words": [{"word", "start", "end", "probability"}, ...]},
                ...
            ]
        }

    Whisper writes `<audio_stem>.json` into `output_dir`; this function loads it.
    Blocks until done — call from a thread when running on the qasync main loop
    (e.g. `await asyncio.to_thread(run_whisper, ...)`).
    """
    audio_path = Path(audio_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not audio_path.exists():
        raise FileNotFoundError(f"Audio không tồn tại: {audio_path}")

    # Run as a module via the same Python that's running us — robust whether
    # the venv's Scripts dir is on PATH or not.
    cmd = [
        sys.executable, "-m", "whisper",
        str(audio_path),
        "--model", model,
        "--language", language,
        "--word_timestamps", "True",
        "--output_format", "json",
        "--output_dir", str(output_dir),
        "--verbose", "False",
    ]

    log.info(f"Whisper transcribing: {audio_path.name} (model={model}, lang={language})")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"Whisper failed (rc={result.returncode}): "
            f"{(result.stderr or '')[:500]}"
        )

    json_file = output_dir / f"{audio_path.stem}.json"
    if not json_file.exists():
        raise FileNotFoundError(
            f"Whisper output JSON không thấy: {json_file} "
            f"(stderr={(result.stderr or '')[:200]})"
        )

    with json_file.open(encoding="utf-8") as f:
        data = json.load(f)

    seg_count = len(data.get("segments", []))
    log.info(f"Whisper done: {seg_count} segments, {len(data.get('text', ''))} chars")
    return data
