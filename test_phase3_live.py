"""Phase 3 — Test 1, 3, 4: e2e align_voice_to_scenes."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voice.voice_aligner import align_voice_to_scenes

ROOT = Path("test_run")
VOICE_DIR = ROOT / "voice"
SCENES_JSON = ROOT / "scenes.json"
OUT = ROOT / "voice_mapping.json"
BACKUP = ROOT / "voice_mapping.json.v3.bak"


def cleanup() -> None:
    for p in (OUT, BACKUP):
        if p.exists():
            p.unlink()


# === Test 1: First run (no backup) ===
print("=== Test 1: First run on test_run ===")
cleanup()
scenes_full = json.loads(SCENES_JSON.read_text(encoding="utf-8"))["scenes"]
result = asyncio.run(align_voice_to_scenes(
    scenes=scenes_full,
    voice_dir=VOICE_DIR,
    output_dir=ROOT,
    whisper_model="base",
    language="en",
))

assert result["version"] == "4.0", result["version"]
assert len(result["scenes"]) == len(scenes_full)
assert OUT.exists()
assert not BACKUP.exists(), "First run should not produce backup"

print(f"\nScenes ({len(result['scenes'])}):")
for vs in result["scenes"]:
    if vs["is_silent"]:
        print(
            f"  {vs['id']}: SILENT method={vs['method']} "
            f"duration_adj={vs['duration_adjusted']} (== duration_orig {vs['duration_original']})"
        )
        assert vs["voice_in"] is None
        assert vs["duration_adjusted"] == vs["duration_original"]
    else:
        print(
            f"  {vs['id']}: method={vs['method']} score={vs['score']} "
            f"voice=[{vs['voice_in']:.2f},{vs['voice_out']:.2f}]s "
            f"adj={vs['duration_adjusted']} orig={vs['duration_original']} "
            f"phrases={len(vs['subtitle_phrases'])}"
        )
        assert vs["voice_in"] is not None
        assert vs["voice_out"] > vs["voice_in"]
        assert vs["duration_adjusted"] > 0

print("\nStats:", json.dumps(result["stats"], indent=2))
print("PASS Test 1")

# === Test: subtitle_phrases sanity for SCENE-01 ===
print("\n=== Subtitle phrases (SCENE-01 sample) ===")
s1 = next(vs for vs in result["scenes"] if vs["id"] == "SCENE-01")
for ph in s1["subtitle_phrases"]:
    print(f"  [{ph['start']:.2f}-{ph['end']:.2f}] '{ph['text']}'  (words={len(ph['words'])})")
assert len(s1["subtitle_phrases"]) > 0
assert all(ph["start"] < ph["end"] for ph in s1["subtitle_phrases"])
print("PASS subtitle_phrases")

# === Test 4: Backup on second run ===
print("\n=== Test 4: Backup created on second run ===")
result2 = asyncio.run(align_voice_to_scenes(
    scenes=scenes_full,
    voice_dir=VOICE_DIR,
    output_dir=ROOT,
    whisper_model="base",
    language="en",
))
assert BACKUP.exists(), f"Expected backup at {BACKUP}"
print(f"PASS — backup at {BACKUP.name}")

# === Test 3: All silent ===
print("\n=== Test 3: All silent scenes ===")
silent_scenes = [
    {"id": "SCENE-01", "story_en": "", "duration": 5},
    {"id": "SCENE-02", "story_en": None, "duration": 8},
]
# Use a different output dir so we don't overwrite the real one
out_silent = ROOT / "_silent_test"
out_silent.mkdir(exist_ok=True)
result_s = asyncio.run(align_voice_to_scenes(
    scenes=silent_scenes,
    voice_dir=VOICE_DIR,
    output_dir=out_silent,
    whisper_model="base",
    language="en",
))
for vs in result_s["scenes"]:
    print(f"  {vs['id']}: is_silent={vs['is_silent']} method={vs['method']} dur_adj={vs['duration_adjusted']}")
    assert vs["is_silent"] is True
    assert vs["method"] == "silent"
    assert vs["duration_adjusted"] == vs["duration_original"]
assert result_s["stats"]["llm_fallback_count"] == 0
# Cleanup silent test artifacts
import shutil
shutil.rmtree(out_silent)
print("PASS Test 3")

print("\n[ALL PHASE 3 LIVE TESTS PASSED]")
