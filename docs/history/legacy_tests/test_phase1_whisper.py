"""Phase 1 — Test 3, 4 for whisper_runner multi-file."""

import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voice.voice_scanner import scan_voice_folder
from voice.whisper_runner import transcribe_single_file, transcribe_all_voice_files

VOICE_DIR = Path("test_run/voice")
VOICE_01 = VOICE_DIR / "voice_01.mp3"

# === Test 3: Whisper single file with offset ===
print("\n=== Test 3: Single file with offset=10.0 ===")
words = transcribe_single_file(
    voice_path=VOICE_01,
    offset=10.0,
    language="en",
    model_name="base",
)
print(f"Got {len(words)} words.  First 3: {words[:3]}")
assert len(words) > 0, "No words extracted"
assert words[0]["start"] >= 10.0, f"First word start should be >= 10.0, got {words[0]['start']}"
assert words[0]["source_file"] == "voice_01.mp3"
# Check that timestamps are monotonic
for i in range(1, len(words)):
    assert words[i]["start"] >= words[i - 1]["start"], (
        f"Timestamps not monotonic at idx {i}: {words[i-1]['start']} -> {words[i]['start']}"
    )
print(f"PASS: offset applied; first word @ {words[0]['start']}s, last @ {words[-1]['start']}s")

# === Test 4: All files (multi-file with cumulative offsets) ===
print("\n=== Test 4: Multi-file transcribe ===")
voice_02 = VOICE_DIR / "voice_02.mp3"
shutil.copy(VOICE_01, voice_02)
try:
    voice_files = scan_voice_folder(VOICE_DIR)
    assert len(voice_files) == 2
    print(f"Files: {[(f.name, f.offset) for f in voice_files]}")

    all_words = asyncio.run(transcribe_all_voice_files(voice_files, language="en"))
    print(f"Total words: {len(all_words)}")

    # Verify monotonic timestamps across both files
    for i in range(1, len(all_words)):
        assert all_words[i]["start"] >= all_words[i - 1]["start"], (
            f"Non-monotonic at idx {i}: "
            f"{all_words[i-1]['source_file']}@{all_words[i-1]['start']} -> "
            f"{all_words[i]['source_file']}@{all_words[i]['start']}"
        )

    # Verify some words come from voice_02 with offset >= file1 duration
    file2_words = [w for w in all_words if w["source_file"] == "voice_02.mp3"]
    assert len(file2_words) > 0, "No words from voice_02"
    assert file2_words[0]["start"] >= voice_files[1].offset - 0.1, (
        f"voice_02 first word should be >= {voice_files[1].offset}, got {file2_words[0]['start']}"
    )
    print(f"PASS: monotonic across files, voice_02 first word @ {file2_words[0]['start']}s")
finally:
    voice_02.unlink()
    print(f"[cleanup] removed {voice_02.name}")

print("\n[ALL PHASE 1 WHISPER TESTS PASSED]")
