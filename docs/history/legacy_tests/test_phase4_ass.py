"""Phase 4 — Tests 1, 4, 5 for ass_generator."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pysubs2

from voice.ass_generator import _build_karaoke_text, generate_final_ass, preview_ass

# === Test 1: Generate ASS from real voice_mapping ===
print("=== Test 1: Live voice_mapping -> ASS ===")
vm = json.loads(Path("test_run/voice_mapping.json").read_text(encoding="utf-8"))
ass_path = Path("test_run/final.ass")
if ass_path.exists():
    ass_path.unlink()

generate_final_ass(vm, ass_path, video_width=1920, video_height=1080)
assert ass_path.exists()

subs = pysubs2.load(str(ass_path))
expected_events = sum(
    len(vs.get("subtitle_phrases", []))
    for vs in vm["scenes"]
    if not vs.get("is_silent")
)
print(f"  events in ASS: {len(subs.events)}, expected: {expected_events}")
assert len(subs.events) == expected_events
# PlayRes
assert subs.info["PlayResX"] == "1920"
assert subs.info["PlayResY"] == "1080"
# Style
default = subs.styles["Default"]
assert default.fontname == "Arial"
assert default.fontsize == 50
assert default.bold is True
assert default.alignment == pysubs2.Alignment.BOTTOM_CENTER
print("  Style OK: Arial Bold 50 BOTTOM_CENTER")

# Verify cumulative timing matches duration_adjusted sum
total_sec = sum(vs["duration_adjusted"] for vs in vm["scenes"])
print(f"  total duration_adjusted: {total_sec:.2f}s")
last_event_end = max(e.end for e in subs.events) if subs.events else 0
print(f"  last event end: {last_event_end / 1000:.2f}s (must be <= {total_sec:.2f})")
assert last_event_end / 1000 <= total_sec + 0.01

# Verify monotonic
prev_end = -1
for e in subs.events:
    assert e.start >= 0
    assert e.end > e.start, f"Event {e.start}-{e.end} has invalid range"
    assert e.start >= prev_end - 1, f"Overlap at {e.start} (prev_end={prev_end})"
    prev_end = e.end
print("  Events monotonic + valid ranges")

# Spot-check first event has karaoke tags
first = subs.events[0]
print(f"  first event text: {first.text[:120]}")
assert "{\\kf" in first.text, f"No \\kf tag found: {first.text}"
print("PASS Test 1")

preview_ass(ass_path, num_events=4)

# === Test 4: Silent scene handling ===
print("\n=== Test 4: Silent scene timing ===")
vm_mix = {
    "scenes": [
        {
            "id": "SCENE-01",
            "is_silent": False,
            "duration_adjusted": 5.0,
            "voice_in": 0.0,
            "voice_out": 5.0,
            "subtitle_phrases": [{
                "text": "Hello",
                "start": 0.0, "end": 1.0,
                "words": [{"word": "Hello", "start": 0.0, "end": 1.0}],
            }],
        },
        {
            "id": "SCENE-02",
            "is_silent": True,
            "duration_adjusted": 3.0,
            "voice_in": None,
            "voice_out": None,
            "subtitle_phrases": [],
        },
        {
            "id": "SCENE-03",
            "is_silent": False,
            "duration_adjusted": 4.0,
            "voice_in": 5.0,
            "voice_out": 9.0,
            "subtitle_phrases": [{
                "text": "World",
                "start": 5.0, "end": 6.0,
                "words": [{"word": "World", "start": 5.0, "end": 6.0}],
            }],
        },
    ]
}
out_mix = Path("test_run/_silent_mix.ass")
generate_final_ass(vm_mix, out_mix)
subs_mix = pysubs2.load(str(out_mix))
assert len(subs_mix.events) == 2, f"Expected 2 events, got {len(subs_mix.events)}"

e0, e1 = subs_mix.events[0], subs_mix.events[1]
print(f"  e0: {e0.start}ms - {e0.end}ms text={e0.text}")
print(f"  e1: {e1.start}ms - {e1.end}ms text={e1.text}")
assert e0.start == 0
assert e0.end == 1000
# SCENE-02 is silent (3000ms gap) -> SCENE-03 phrase should start at 8000ms
assert e1.start == 8000, f"Expected e1.start=8000ms (5000+3000), got {e1.start}"
assert e1.end == 9000
out_mix.unlink()
print("PASS Test 4")

# === Test 5a: Empty mapping ===
print("\n=== Test 5a: Empty voice_mapping ===")
out_empty = Path("test_run/_empty.ass")
generate_final_ass({"scenes": []}, out_empty)
subs_empty = pysubs2.load(str(out_empty))
assert len(subs_empty.events) == 0
out_empty.unlink()
print("PASS empty mapping")

# === Test 5b: Special chars { } in word text ===
print("\n=== Test 5b: Escape { } in karaoke ===")
words = [
    {"word": "Hello,", "start": 0.0, "end": 1.0},
    {"word": "{world}!", "start": 1.0, "end": 2.0},
]
text = _build_karaoke_text(words)
print(f"  generated: {text}")
# Should contain escaped braces \{ and \}
assert "\\{world\\}!" in text, f"braces not escaped: {text}"
# Each word still wrapped with its own \kf tag
assert text.count("{\\kf") == 2
print("PASS special-char escaping")

print("\n[ALL PHASE 4 TESTS PASSED]")
