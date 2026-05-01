"""Read-only audit script for VERIFY_FLOW.md.

Runs Plan D `align_voice_to_scenes` on test_live data, dumps Whisper transcript
and voice_mapping for inspection. Does NOT modify source code.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from voice.voice_aligner import align_voice_to_scenes
from voice.voice_scanner import scan_voice_folder
from voice.whisper_runner import transcribe_all_voice_files


async def main() -> None:
    project = ROOT / "test_live"
    scenes = json.loads((project / "scenes.json").read_text(encoding="utf-8"))["scenes"]
    voice_dir = project / "voice"

    print("=== STEP A: Voice scan ===")
    files = scan_voice_folder(voice_dir)
    for vf in files:
        print(f"  - {vf.path.name}: {vf.duration:.2f}s")

    print("\n=== STEP B: Whisper transcribe ===")
    words = await transcribe_all_voice_files(files, language="en", model_name="base")
    print(f"  Total words: {len(words)}")
    if words:
        print(f"  First word: {words[0]}")
        print(f"  Last word:  {words[-1]}")
    transcript = " ".join(w["word"] for w in words)
    print(f"\n  Transcript ({len(transcript)} chars):")
    print(f"  > {transcript}")

    (project / "whisper_words_audit.json").write_text(
        json.dumps(words, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n=== STEP C: align_voice_to_scenes (Plan D) ===")
    voice_mapping = await align_voice_to_scenes(
        scenes=scenes,
        voice_dir=voice_dir,
        output_dir=project,
        whisper_model="base",
        language="en",
    )
    print(json.dumps(voice_mapping.get("stats", {}), indent=2))

    print("\n=== STEP D: Per-scene summary ===")
    for s in voice_mapping["scenes"]:
        print(
            f"  [{s['id']}] "
            f"in={s.get('voice_in')} out={s.get('voice_out')} "
            f"score={s.get('score')} method={s.get('method')} "
            f"phrases={len(s.get('subtitle_phrases', []))}"
        )


if __name__ == "__main__":
    asyncio.run(main())
