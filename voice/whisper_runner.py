"""Whisper CLI wrapper — transcribe audio to JSON with word-level timestamps.

Two surfaces:
- Legacy: `run_whisper(audio, output_dir, ...)` — subprocess CLI, used by
  `voice/voice_aligner.py` (Sprint 2 flow).
- New (voice rebuild Phase 1): `transcribe_single_file` /
  `transcribe_all_voice_files` — in-process whisper.load_model with global
  timestamps for multi-file scenarios.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger as log

if TYPE_CHECKING:
    from voice.voice_scanner import VoiceFileMeta


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


# ============================================================================
# Voice rebuild Phase 1 — in-process whisper with global timestamps
# ============================================================================

_whisper_model = None
_torch_imported = False


def warmup_torch() -> None:
    """Force torch + whisper module imports on the calling thread.

    Windows DLL loader sometimes fails (WinError 1114) when torch is imported
    for the first time inside an `asyncio.to_thread` worker. Calling this from
    the main thread before kicking off the worker avoids that path.
    """
    global _torch_imported
    if _torch_imported:
        return
    import torch  # noqa: F401, PLC0415
    import whisper  # noqa: F401, PLC0415
    _torch_imported = True


def get_whisper_model(model_name: str = "base"):
    """Lazy-load Whisper model (singleton).

    `import whisper` is deferred to here so the UI process doesn't pay the
    torch DLL load cost at startup — only when transcription is actually run.
    """
    global _whisper_model
    if _whisper_model is None:
        warmup_torch()
        import whisper  # noqa: PLC0415 — intentional lazy import

        log.info(f"Loading Whisper model: {model_name}")
        _whisper_model = whisper.load_model(model_name)
    return _whisper_model


def transcribe_single_file(
    voice_path: Path,
    offset: float = 0.0,
    language: str = "en",
    model_name: str = "base",
) -> list[dict]:
    """Transcribe single audio file, return words with global timestamps.

    Returns list of word dicts: [{word, start, end, source_file}, ...]
    Timestamps are GLOBAL (offset added).
    """
    model = get_whisper_model(model_name)

    log.info(f"Transcribing {voice_path.name} (offset={offset:.2f}s)...")

    result = model.transcribe(
        str(voice_path),
        language=language,
        word_timestamps=True,
        verbose=False,
    )

    all_words: list[dict] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            all_words.append({
                "word": w["word"].strip(),
                "start": round(w["start"] + offset, 3),
                "end": round(w["end"] + offset, 3),
                "source_file": voice_path.name,
            })

    log.info(f"  -> {len(all_words)} words extracted")
    return all_words


async def transcribe_all_voice_files(
    voice_files: list[VoiceFileMeta],
    language: str = "en",
    model_name: str = "base",
) -> list[dict]:
    """Transcribe all voice files in a subprocess (Windows-safe under Qt).

    Calling whisper.transcribe via `asyncio.to_thread` from inside the qasync
    loop crashes the GUI on Windows (torch's OpenMP runtime fights with Qt's
    MSVC vcomp140). Off-loading to a subprocess fully isolates torch from the
    parent interpreter — no shared DLL state, no event-loop interaction.
    """
    if not voice_files:
        return []

    proc = await _run_whisper_subprocess(voice_files, language, model_name)

    log.info(f"Total transcribed words: {len(proc)}")
    return proc


async def _run_whisper_subprocess(
    voice_files: list[VoiceFileMeta],
    language: str,
    model_name: str,
) -> list[dict]:
    """Launch the in-tree whisper subprocess and return its parsed word list."""
    import json
    import sys

    job = {
        "model": model_name,
        "language": language,
        "files": [
            {"path": str(vf.path), "offset": vf.offset, "name": vf.name}
            for vf in voice_files
        ],
    }
    payload = json.dumps(job, ensure_ascii=False)

    project_root = Path(__file__).resolve().parents[1]
    log.info(
        f"Whisper subprocess: model={model_name} lang={language} "
        f"files={len(voice_files)}"
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
            f"Whisper subprocess failed (rc={proc.returncode}): {err[-1500:]}"
        )

    text = stdout.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Whisper subprocess produced non-JSON output: {text[:300]!r}"
        ) from e
