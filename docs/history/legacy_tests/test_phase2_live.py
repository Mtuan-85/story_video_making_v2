"""Phase 2 — Test 4: live data alignment on test_run."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voice.deterministic_aligner import (
    align_deterministic,
    calculate_stats,
    SCORE_THRESHOLD,
)
from voice.voice_scanner import scan_voice_folder
from voice.whisper_runner import transcribe_all_voice_files

VOICE_DIR = Path("test_run/voice")
SCENES_JSON = Path("test_run/scenes.json")

print("=== Step 1: Scan voice folder ===")
voice_files = scan_voice_folder(VOICE_DIR)
print(f"  -> {len(voice_files)} file(s)")

print("\n=== Step 2: Whisper transcribe ===")
words = asyncio.run(transcribe_all_voice_files(voice_files, language="en", model_name="base"))
print(f"  -> {len(words)} words")
print(f"  First 8 words: {[w['word'] for w in words[:8]]}")

print("\n=== Step 3: Load scenes ===")
scenes_json = json.loads(SCENES_JSON.read_text(encoding="utf-8"))
scenes = scenes_json["scenes"]
print(f"  -> {len(scenes)} scenes")
for s in scenes:
    print(f"    {s['id']}: '{(s.get('story_en') or '')[:60]}...'")

print("\n=== Step 4: Align deterministic ===")
results = align_deterministic(scenes, words)

print("\n=== Per-scene results ===")
for r in results:
    sid = r["id"]
    if r["is_silent"]:
        print(f"  {sid}: SILENT (method={r['method']})")
        continue
    score = r["score"]
    flag = "PASS" if score >= SCORE_THRESHOLD else "FAIL (need fallback)"
    print(
        f"  {sid}: score={score:.1f} [{flag}] "
        f"voice_in={r['voice_in']:.2f}s voice_out={r['voice_out']:.2f}s"
    )
    print(f"    matched: '{r['matched_text'][:70]}...'")

print("\n=== Stats ===")
stats = calculate_stats(results)
for k, v in stats.items():
    print(f"  {k}: {v}")

# Sanity: every scene gets a result
assert len(results) == len(scenes)
print("\n[Live test complete]")
