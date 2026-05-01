"""Phase 2 — synthetic tests for deterministic_aligner."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from voice.deterministic_aligner import (
    align_deterministic,
    calculate_stats,
    find_match_with_anchors,
    normalize_phrase,
    normalize_word,
)


def make_words(text: str, t_start: float = 0.0, dt: float = 0.4) -> list[dict]:
    """Build whisper-style word list."""
    out = []
    t = t_start
    for w in text.split():
        out.append({"word": w, "start": round(t, 2), "end": round(t + dt, 2)})
        t += dt
    return out


# === Test 1: Normalize ===
print("=== Test 1: Normalize ===")
assert normalize_word("Hello,") == "hello"
assert normalize_word("World!") == "world"
assert normalize_phrase("Hello, World!") == ["hello", "world"]
assert normalize_phrase("") == []
assert normalize_phrase("  ") == []
assert normalize_word("Don't") == "dont"  # apostrophe stripped
print("PASS")

# === Test 2: Perfect match ===
print("\n=== Test 2: Perfect match ===")
whisper = [
    {"word": "Rain", "start": 0.0, "end": 0.5},
    {"word": "taps", "start": 0.5, "end": 0.9},
    {"word": "softly", "start": 0.9, "end": 1.4},
    {"word": "on", "start": 1.4, "end": 1.6},
    {"word": "the", "start": 1.6, "end": 1.8},
    {"word": "cafe", "start": 1.8, "end": 2.2},
    {"word": "window", "start": 2.2, "end": 2.7},
]
scene_words = normalize_phrase("Rain taps softly on the cafe window")
match = find_match_with_anchors(scene_words, whisper, 0)
assert match is not None, "Expected match"
print(f"  voice_in={match.voice_in}, voice_out={match.voice_out}, score={match.score}")
assert match.voice_in == 0.0
assert match.voice_out == 2.7
assert match.score >= 95, f"Expected >= 95, got {match.score}"
print("PASS")

# === Test 3: Minor variation (Whisper transcribed "She" but story says "He") ===
print("\n=== Test 3: Minor variation ===")
whisper3 = make_words("She opens the notebook and starts writing")
scene_words3 = normalize_phrase("He opens the notebook and starts writing")
match3 = find_match_with_anchors(scene_words3, whisper3, 0)
assert match3 is not None
print(f"  matched_text='{match3.matched_text}', score={match3.score}")
assert match3.score >= 75, f"Expected >= 75, got {match3.score}"
print("PASS")

# === Test 5: Silent scene + recovery ===
print("\n=== Test 5: Silent scene handling ===")
whisper5 = (
    make_words("Rain taps softly on the cafe window")
    + make_words("Outside the window people pass by", t_start=4.0)
)
scenes5 = [
    {"id": "SCENE-01", "story_en": "Rain taps softly on the cafe window"},
    {"id": "SCENE-02", "story_en": ""},
    {"id": "SCENE-03", "story_en": "Outside the window people pass by"},
]
results5 = align_deterministic(scenes5, whisper5)
assert len(results5) == 3
assert results5[0]["is_silent"] is False
assert results5[1]["is_silent"] is True
assert results5[1]["method"] == "silent"
assert results5[2]["is_silent"] is False, f"SCENE-03 unexpectedly silent: {results5[2]}"
print(f"  SCENE-01 score={results5[0]['score']}, SCENE-03 score={results5[2]['score']}")
print("PASS")

# === Test 6: Completely unrelated text ===
print("\n=== Test 6: No-match scenario ===")
whisper6 = make_words("Rain taps softly on the cafe window")
scenes6 = [
    {"id": "SCENE-X", "story_en": "Completely unrelated text about dragons castles flying"}
]
results6 = align_deterministic(scenes6, whisper6)
print(f"  result={results6[0]}")
# Either is_silent=True (no_match) OR score < SCORE_THRESHOLD (Phase 3 will handle).
# Acceptable: anchor score must drop low (< 30 -> no_match) OR combined score below 75.
r = results6[0]
assert (r["is_silent"] is True and r["method"] == "no_match") or (r.get("score") or 0) < 75, (
    f"Expected no_match or low score, got {r}"
)
print("PASS")

# === Stats sanity ===
print("\n=== Stats ===")
stats5 = calculate_stats(results5)
print(f"  Test 5 stats: {stats5}")
assert stats5["total_scenes"] == 3
assert stats5["silent"] == 1
print("PASS")

print("\n[ALL PHASE 2 SYNTHETIC TESTS PASSED]")
