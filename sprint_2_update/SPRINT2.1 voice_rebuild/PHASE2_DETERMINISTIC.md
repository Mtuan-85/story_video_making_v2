# Phase 2 — Deterministic Fuzzy Aligner

> **Goal**: Match scenes story → Whisper words bằng rapidfuzz, không LLM.
> **Effort**: 2-3h
> **Dependency**: rapidfuzz (NEW)

---

## Install rapidfuzz

Add vào `requirements.txt`:
```
rapidfuzz>=3.5.0
```

Install:
```bash
.venv\Scripts\activate
uv pip install rapidfuzz
```

Verify:
```python
python -c "from rapidfuzz import fuzz; print(fuzz.ratio('hello', 'helo'))"
# Should print 88 or similar
```

---

## Module: `voice/deterministic_aligner.py` (NEW)

```python
"""
Deterministic fuzzy matching: scenes story → Whisper words timestamps.

No LLM. Uses rapidfuzz for text similarity.

Algorithm:
1. For each scene (in order):
2.   Extract first N words as "start anchor", last N as "end anchor"
3.   Search start anchor in [cursor, cursor+SEARCH_WINDOW] of whisper words
4.   Search end anchor in window after start match
5.   Compute combined score (start_anchor + end_anchor + full_match)
6.   If score >= THRESHOLD: use deterministic result
7.   Advance cursor past this scene's last word
"""

import re
from dataclasses import dataclass, asdict
from typing import Optional
from rapidfuzz import fuzz
from loguru import logger as log


# === Configurable thresholds ===
SCORE_THRESHOLD = 75.0           # Below this → fallback LLM (set in Phase 3)
MIN_ANCHOR_SIZE = 3              # Minimum words for anchor
MAX_ANCHOR_SIZE = 7              # Maximum words for anchor
SEARCH_WINDOW = 50               # Word lookahead from cursor
END_ANCHOR_TOLERANCE = 0.5       # ±50% of scene length to search end anchor


@dataclass
class MatchResult:
    voice_in: float
    voice_out: float
    score: float
    matched_text: str
    word_indices: tuple        # (start_idx, end_idx) inclusive
    method: str = "deterministic"
    
    def to_dict(self):
        d = asdict(self)
        d["word_indices"] = list(self.word_indices)  # tuple → list for JSON
        return d


def normalize_word(word: str) -> str:
    """Lowercase + strip punctuation."""
    word = word.lower().strip()
    word = re.sub(r"[^\w]", "", word)
    return word


def normalize_phrase(text: str) -> list[str]:
    """Tokenize and normalize text into clean words."""
    if not text:
        return []
    words = text.split()
    normalized = [normalize_word(w) for w in words]
    return [w for w in normalized if w]


def get_anchor_size(scene_words_count: int) -> int:
    """Determine anchor size based on scene length."""
    if scene_words_count < MIN_ANCHOR_SIZE:
        return scene_words_count  # short scene: use all words as anchor
    return min(MAX_ANCHOR_SIZE, max(MIN_ANCHOR_SIZE, scene_words_count // 3))


def find_match_with_anchors(
    scene_words: list[str],
    whisper_words: list[dict],
    cursor: int,
) -> Optional[MatchResult]:
    """
    Find best match for scene_words starting from cursor in whisper_words.
    
    Returns None if no reasonable match (no start anchor found).
    """
    if not scene_words or cursor >= len(whisper_words):
        return None
    
    n_scene = len(scene_words)
    anchor_size = get_anchor_size(n_scene)
    
    start_anchor = " ".join(scene_words[:anchor_size])
    end_anchor = " ".join(scene_words[-anchor_size:])
    
    # === Step 1: Find start anchor ===
    search_end = min(cursor + SEARCH_WINDOW, len(whisper_words) - anchor_size + 1)
    if search_end <= cursor:
        return None
    
    best_start_idx = -1
    best_start_score = 0
    
    for i in range(cursor, search_end):
        if i + anchor_size > len(whisper_words):
            break
        window = " ".join(
            normalize_word(whisper_words[j]["word"])
            for j in range(i, i + anchor_size)
        )
        score = fuzz.ratio(start_anchor, window)
        if score > best_start_score:
            best_start_score = score
            best_start_idx = i
    
    # Sanity check: at least somewhat plausible start
    if best_start_idx == -1 or best_start_score < 30:
        log.warning(
            f"No reasonable start anchor (best score {best_start_score:.1f}). "
            f"Anchor: '{start_anchor}'"
        )
        return None
    
    # === Step 2: Find end anchor ===
    estimated_end = best_start_idx + n_scene
    tolerance = int(n_scene * END_ANCHOR_TOLERANCE)
    
    search_end_min = max(best_start_idx + anchor_size, estimated_end - tolerance)
    search_end_max = min(estimated_end + tolerance, len(whisper_words) - anchor_size + 1)
    
    if search_end_max <= search_end_min:
        # Voice may be ending soon, use what we have
        best_end_idx = min(best_start_idx + n_scene - 1, len(whisper_words) - 1)
        best_end_score = 50  # mid score (uncertain)
    else:
        best_end_idx = -1
        best_end_score = 0
        
        for i in range(search_end_min, search_end_max):
            if i + anchor_size > len(whisper_words):
                break
            window = " ".join(
                normalize_word(whisper_words[j]["word"])
                for j in range(i, i + anchor_size)
            )
            score = fuzz.ratio(end_anchor, window)
            if score > best_end_score:
                best_end_score = score
                best_end_idx = i + anchor_size - 1
        
        if best_end_idx == -1:
            best_end_idx = min(best_start_idx + n_scene - 1, len(whisper_words) - 1)
            best_end_score = 50
    
    # === Step 3: Verify with full match ===
    full_whisper = " ".join(
        normalize_word(whisper_words[j]["word"])
        for j in range(best_start_idx, best_end_idx + 1)
    )
    full_scene = " ".join(scene_words)
    
    # Use partial_ratio because matched range may have minor extras
    full_score = fuzz.token_sort_ratio(full_scene, full_whisper)
    
    # Combined score: weighted average
    combined_score = (
        best_start_score * 0.3 +
        best_end_score * 0.3 +
        full_score * 0.4
    )
    
    return MatchResult(
        voice_in=whisper_words[best_start_idx]["start"],
        voice_out=whisper_words[best_end_idx]["end"],
        score=round(combined_score, 1),
        matched_text=" ".join(
            whisper_words[j]["word"]
            for j in range(best_start_idx, best_end_idx + 1)
        ),
        word_indices=(best_start_idx, best_end_idx),
        method="deterministic",
    )


def align_deterministic(
    scenes: list[dict],
    whisper_words: list[dict],
) -> list[dict]:
    """
    Run deterministic align for all scenes.
    
    Returns list of result dicts (one per scene), with:
    - id, voice_in, voice_out, score, is_silent, method, matched_text, word_indices
    
    Silent scenes (story_en empty) marked is_silent=True.
    Unmatched scenes (no start anchor) also is_silent=True with warning.
    """
    
    results = []
    cursor = 0
    
    for scene in scenes:
        scene_id = scene["id"]
        story = (scene.get("story_en") or "").strip()
        
        # Silent scene: no story
        if not story:
            log.info(f"{scene_id}: silent (no story_en)")
            results.append({
                "id": scene_id,
                "voice_in": None,
                "voice_out": None,
                "score": None,
                "is_silent": True,
                "method": "silent",
                "matched_text": None,
                "word_indices": None,
            })
            continue
        
        scene_words = normalize_phrase(story)
        
        if not scene_words:
            results.append({
                "id": scene_id,
                "voice_in": None,
                "voice_out": None,
                "score": 0,
                "is_silent": True,
                "method": "no_match",
                "matched_text": None,
                "word_indices": None,
                "warning": "story_normalized_empty",
            })
            continue
        
        match = find_match_with_anchors(scene_words, whisper_words, cursor)
        
        if match is None:
            log.warning(f"{scene_id}: no match found, marking silent")
            results.append({
                "id": scene_id,
                "voice_in": None,
                "voice_out": None,
                "score": 0,
                "is_silent": True,
                "method": "no_match",
                "matched_text": None,
                "word_indices": None,
                "warning": "no_match_in_voice",
            })
            continue
        
        # Log per scene
        status = "✓" if match.score >= SCORE_THRESHOLD else "✗"
        log.info(
            f"{scene_id}: deterministic score={match.score:.1f} {status} "
            f"({match.voice_in:.2f}-{match.voice_out:.2f}s)"
        )
        
        result = match.to_dict()
        result["id"] = scene_id
        result["is_silent"] = False
        results.append(result)
        
        # Advance cursor past matched range
        cursor = match.word_indices[1] + 1
    
    return results


def calculate_stats(results: list[dict]) -> dict:
    """Calculate alignment statistics."""
    total = len(results)
    silent = sum(1 for r in results if r.get("method") == "silent")
    no_match = sum(1 for r in results if r.get("method") == "no_match")
    deterministic_pass = sum(
        1 for r in results
        if r.get("method") == "deterministic" and r.get("score", 0) >= SCORE_THRESHOLD
    )
    deterministic_fail = sum(
        1 for r in results
        if r.get("method") == "deterministic" and r.get("score", 0) < SCORE_THRESHOLD
    )
    
    return {
        "total_scenes": total,
        "deterministic_pass": deterministic_pass,
        "deterministic_fail_need_fallback": deterministic_fail,
        "silent": silent,
        "no_match": no_match,
    }
```

---

## Test plan

### Test 1: Normalize functions

```python
assert normalize_word("Hello,") == "hello"
assert normalize_word("World!") == "world"
assert normalize_phrase("Hello, World!") == ["hello", "world"]
assert normalize_phrase("") == []
```

### Test 2: Match with perfect text

```python
whisper_words = [
    {"word": "Rain", "start": 0.0, "end": 0.5},
    {"word": "taps", "start": 0.5, "end": 0.9},
    {"word": "softly", "start": 0.9, "end": 1.4},
    {"word": "on", "start": 1.4, "end": 1.6},
    {"word": "the", "start": 1.6, "end": 1.8},
    {"word": "cafe", "start": 1.8, "end": 2.2},
    {"word": "window", "start": 2.2, "end": 2.7},
]
scene_words = normalize_phrase("Rain taps softly on the cafe window")

match = find_match_with_anchors(scene_words, whisper_words, 0)
assert match is not None
assert match.voice_in == 0.0
assert match.voice_out == 2.7
assert match.score >= 95  # near perfect
```

### Test 3: Match with minor variation (Whisper sai 1 từ)

```python
# Whisper transcribed "She" but script says "He"
whisper_words = [...]  # "She opens the notebook..."
scene_words = normalize_phrase("He opens the notebook")

match = find_match_with_anchors(scene_words, whisper_words, 0)
assert match is not None
assert match.score >= 75  # still pass threshold
```

### Test 4: Multi scenes alignment with current data

```python
# Use test_run scenes.json + voice mp3
from voice.voice_scanner import scan_voice_folder
from voice.whisper_runner import transcribe_all_voice_files

voice_files = scan_voice_folder(Path("test_run/voice"))
words = asyncio.run(transcribe_all_voice_files(voice_files))

import json
scenes_json = json.loads(Path("test_run/scenes.json").read_text())
scenes = scenes_json["scenes"]

results = align_deterministic(scenes, words)

# Verify each scene has a result
assert len(results) == len(scenes)

# Print stats
stats = calculate_stats(results)
print(f"Stats: {stats}")

# Expected:
# - SCENE-01, 02, 04, 05: high score (>= 75)
# - SCENE-03: may be lower if story spans silence (test threshold)
```

### Test 5: Silent scene handling

```python
scenes = [
    {"id": "SCENE-01", "story_en": "Rain taps softly..."},
    {"id": "SCENE-02", "story_en": ""},  # silent
    {"id": "SCENE-03", "story_en": "Outside the window..."},
]
results = align_deterministic(scenes, whisper_words)

assert results[0]["is_silent"] == False
assert results[1]["is_silent"] == True
assert results[1]["method"] == "silent"
assert results[2]["is_silent"] == False
# SCENE-03 should match correctly even after silent scene
```

### Test 6: No match scenarios

```python
scenes = [
    {"id": "SCENE-X", "story_en": "Completely unrelated text about dragons and castles"}
]
whisper_words = [...]  # text about coffee shop
results = align_deterministic(scenes, whisper_words)

assert results[0]["is_silent"] == True
assert results[0]["method"] == "no_match"
```

---

## Build order

1. Install rapidfuzz (5 phút)
2. Create `voice/deterministic_aligner.py` (1.5h)
3. Test 1, 2, 3 (30 phút)
4. Test 4 với voice hiện tại (30 phút)
5. Tweak threshold nếu cần (15 phút)
6. Commit

**Total: ~2-3h**

---

## Expected output cho voice hiện tại

Voice mp3 hiện tại + scenes.json hiện tại, expected log:

```
[INFO] SCENE-01: deterministic score=92.5 ✓ (0.00-8.22s)
[INFO] SCENE-02: deterministic score=88.0 ✓ (8.22-13.50s)
[INFO] SCENE-03: deterministic score=??.? (need test)
[INFO] SCENE-04: deterministic score=??.? (need test)
[INFO] SCENE-05: deterministic score=95.1 ✓ (25.08-29.88s)

Stats: {
  "total_scenes": 5,
  "deterministic_pass": 3-5 (tùy SCENE-03 và 04),
  "deterministic_fail_need_fallback": 0-2,
  "silent": 0,
  "no_match": 0
}
```

→ Bro chạy test sẽ biết SCENE-03 score bao nhiêu. Nếu < 75 → Phase 3 LLM fallback sẽ xử lý.

---

## Confirm trước khi code

- [ ] rapidfuzz install thành công
- [ ] Phase 1 đã build xong (voice_scanner + whisper_runner multi-file)
- [ ] Voice mp3 hiện tại sẵn sàng test
- [ ] scenes.json hiện tại có 5 scenes với story_en

→ Build xong, run Test 4 (full alignment) trước khi proceed Phase 3.
