"""Whisper subprocess entry — isolates torch from the Qt parent process.

Running torch + whisper.transcribe inside the qasync loop crashes the GUI on
Windows (torch DLLs conflict with Qt's MSVC OpenMP runtime under
`asyncio.to_thread`). This script is invoked via subprocess so torch lives
in a fresh interpreter that never loaded PyQt6.

Usage: invoked by `voice/whisper_runner.py::transcribe_all_voice_files_subproc`
with a JSON job spec on stdin and a JSON word list written to stdout.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _run_job(job: dict) -> list[dict]:
    os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    import whisper  # noqa: PLC0415

    model_name = job.get("model", "base")
    language = job.get("language", "en")
    files = job["files"]  # list of {path, offset, name}

    model = whisper.load_model(model_name)

    all_words: list[dict] = []
    for entry in files:
        path = Path(entry["path"])
        offset = float(entry.get("offset", 0.0))
        name = entry.get("name") or path.name
        result = model.transcribe(
            str(path),
            language=language,
            word_timestamps=True,
            verbose=False,
        )
        for seg in result.get("segments", []):
            for w in seg.get("words", []):
                all_words.append({
                    "word": (w.get("word") or "").strip(),
                    "start": round(float(w["start"]) + offset, 3),
                    "end": round(float(w["end"]) + offset, 3),
                    "source_file": name,
                })

    return all_words


def main() -> None:
    job = json.loads(sys.stdin.read())
    words = _run_job(job)
    sys.stdout.write(json.dumps(words, ensure_ascii=False))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
