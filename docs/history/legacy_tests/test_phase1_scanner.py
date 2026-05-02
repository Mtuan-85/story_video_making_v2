"""Phase 1 — Test 1, 2, 5 for voice_scanner."""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voice.voice_scanner import (
    scan_voice_folder,
    get_total_voice_duration,
    voice_files_changed,
)

VOICE_DIR = Path("test_run/voice")

# Backup state: keep only voice_01.mp3 for test
backup_xlsx = VOICE_DIR / "Excel.xlsx"
if backup_xlsx.exists():
    print(f"[setup] Excel.xlsx exists in voice dir — ignored by scanner (only mp3/wav/m4a)")

# === Test 1: Scan single voice file ===
print("\n=== Test 1: Single file ===")
files = scan_voice_folder(VOICE_DIR)
assert len(files) == 1, f"Expected 1 file, got {len(files)}"
assert files[0].offset == 0.0, f"Expected offset 0, got {files[0].offset}"
assert files[0].duration > 0, f"Expected duration > 0, got {files[0].duration}"
print(f"PASS: 1 file, name={files[0].name}, duration={files[0].duration:.2f}s, offset={files[0].offset}")

original_duration = files[0].duration
single_meta = [vf.to_dict() for vf in files]

# === Test 2: Scan multiple voice files ===
print("\n=== Test 2: Multiple files ===")
voice2 = VOICE_DIR / "voice_02.mp3"
shutil.copy(VOICE_DIR / "voice_01.mp3", voice2)
try:
    files = scan_voice_folder(VOICE_DIR)
    assert len(files) == 2, f"Expected 2, got {len(files)}"
    assert files[0].offset == 0.0
    assert abs(files[1].offset - files[0].duration) < 0.01, (
        f"Expected offset {files[0].duration}, got {files[1].offset}"
    )
    print(f"PASS: 2 files, offsets={[f.offset for f in files]}")

    total = get_total_voice_duration(files)
    expected_total = files[0].duration + files[1].duration
    assert abs(total - expected_total) < 0.01
    print(f"PASS: total duration = {total:.2f}s")

    # === Test 5 (partial): No-change detection ===
    cached_two = [vf.to_dict() for vf in files]
    assert voice_files_changed(VOICE_DIR, cached_two) is False
    print("PASS: voice_files_changed=False when no change")

    # File count differs
    assert voice_files_changed(VOICE_DIR, single_meta) is True
    print("PASS: voice_files_changed=True when count differs")

finally:
    voice2.unlink()
    print(f"[cleanup] removed {voice2.name}")

# === Test 5 final: file removed ===
print("\n=== Test 5: Detect deletion ===")
# After cleanup, dir has 1 file — compare against cached_two (2 files) → True
assert voice_files_changed(VOICE_DIR, cached_two) is True
print("PASS: voice_files_changed=True after deletion")

print("\n[ALL PHASE 1 SCANNER TESTS PASSED]")
