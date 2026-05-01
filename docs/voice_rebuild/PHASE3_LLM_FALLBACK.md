# Phase 3 — LLM Fallback + Orchestrator

> **Goal**: Claude CLI fallback per-scene khi deterministic score < 75. Build full pipeline.
> **Effort**: 1-2h
> **Dependency**: Claude CLI (đã có)

---

## Module: `voice/llm_fallback.py` (NEW)

```python
"""
LLM fallback: Claude CLI alignment cho 1 scene.
Chỉ gọi khi deterministic score < SCORE_THRESHOLD.

Search window scoped bởi prev/next scene's word indices để giới hạn token.
"""

import asyncio
import json
import os
import subprocess
from loguru import logger as log


CLAUDE_TIMEOUT = 120  # seconds


async def claude_align_scene(
    scene: dict,
    whisper_words: list[dict],
    search_start_idx: int,
    search_end_idx: int,
) -> dict:
    """
    Use Claude CLI to align ONE scene within a search window.
    
    Args:
        scene: dict with id + story_en
        whisper_words: full whisper word list (global indices)
        search_start_idx: lower bound (inclusive, in whisper_words)
        search_end_idx: upper bound (inclusive)
    
    Returns:
        Result dict similar to deterministic_aligner output, with method="llm".
    """
    
    if search_start_idx >= search_end_idx or search_start_idx >= len(whisper_words):
        log.warning(f"{scene['id']}: invalid search window, skip LLM")
        return {
            "id": scene["id"],
            "voice_in": None,
            "voice_out": None,
            "score": 0,
            "is_silent": True,
            "method": "llm_invalid_window",
            "matched_text": None,
            "word_indices": None,
            "warning": "search_window_invalid",
        }
    
    # Build search window words list with absolute indices
    window_end = min(search_end_idx + 1, len(whisper_words))
    window_words = whisper_words[search_start_idx:window_end]
    
    words_desc = "\n".join(
        f"  [{i + search_start_idx}] {w['start']:.2f}-{w['end']:.2f}s: {w['word']}"
        for i, w in enumerate(window_words)
    )
    
    prompt = f"""You are aligning a scene's narration to Whisper word timestamps.

SCENE:
ID: {scene["id"]}
Story: "{scene["story_en"]}"

WHISPER WORDS (with global timestamps, search window only):
{words_desc}

TASK:
Find the EXACT word timestamps where this scene's narration begins and ends in the voice.

RULES:
1. The scene story is the GROUND TRUTH. Whisper may have minor errors (e.g., "He" vs "She", "you" vs "your").
2. voice_in = start time of FIRST word matching scene story
3. voice_out = end time of LAST word matching scene story
4. Use word indices [N] from above to identify positions
5. The match may span natural pauses (silence between sentences) — that's OK
6. If part of the story is missing in this voice window, match what's present
7. If the scene story has NO match in this window at all, return is_silent=true

OUTPUT JSON ONLY (no markdown, no commentary):
{{
  "is_silent": false,
  "voice_in_word_idx": N,
  "voice_out_word_idx": M,
  "voice_in": <timestamp>,
  "voice_out": <timestamp>,
  "confidence": "high",
  "reasoning": "Brief explanation"
}}

Or if no match:
{{
  "is_silent": true,
  "reasoning": "Why no match"
}}

Confidence levels:
- "high": clear match, voice_in/out exactly correct
- "medium": match but boundaries slightly uncertain
- "low": partial or fuzzy match
"""
    
    log.info(f"{scene['id']}: LLM fallback (window {search_start_idx}-{search_end_idx})")
    
    def _run():
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = ""  # force subscription mode
        return subprocess.run(
            ["claude", "--print"],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=CLAUDE_TIMEOUT,
            env=env,
        )
    
    try:
        result = await asyncio.to_thread(_run)
    except subprocess.TimeoutExpired:
        log.error(f"{scene['id']}: Claude CLI timeout")
        return _build_failure_result(scene["id"], "llm_timeout")
    
    if result.returncode != 0:
        log.error(f"{scene['id']}: Claude CLI failed (rc={result.returncode}): {result.stderr[:300]}")
        return _build_failure_result(scene["id"], "llm_subprocess_failed")
    
    text = result.stdout.strip()
    
    # Strip markdown fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"{scene['id']}: Claude returned invalid JSON: {text[:200]}")
        return _build_failure_result(scene["id"], "llm_invalid_json")
    
    if data.get("is_silent"):
        log.info(f"{scene['id']}: LLM says silent")
        return {
            "id": scene["id"],
            "voice_in": None,
            "voice_out": None,
            "score": 0,
            "is_silent": True,
            "method": "llm_silent",
            "matched_text": None,
            "word_indices": None,
            "reasoning": data.get("reasoning", ""),
        }
    
    # Build matched_text from word indices
    in_idx = data["voice_in_word_idx"]
    out_idx = data["voice_out_word_idx"]
    
    if not (0 <= in_idx <= out_idx < len(whisper_words)):
        log.warning(f"{scene['id']}: LLM returned invalid indices ({in_idx}, {out_idx})")
        return _build_failure_result(scene["id"], "llm_bad_indices")
    
    matched_text = " ".join(
        whisper_words[i]["word"]
        for i in range(in_idx, out_idx + 1)
    )
    
    score = _confidence_to_score(data.get("confidence", "medium"))
    
    log.info(
        f"{scene['id']}: LLM matched score={score} "
        f"({data['voice_in']:.2f}-{data['voice_out']:.2f}s) "
        f"conf={data.get('confidence')}"
    )
    
    return {
        "id": scene["id"],
        "voice_in": data["voice_in"],
        "voice_out": data["voice_out"],
        "score": score,
        "is_silent": False,
        "method": "llm",
        "matched_text": matched_text,
        "word_indices": [in_idx, out_idx],
        "confidence": data.get("confidence", "medium"),
        "reasoning": data.get("reasoning", ""),
    }


def _confidence_to_score(conf: str) -> float:
    return {"high": 90.0, "medium": 75.0, "low": 60.0}.get(conf.lower(), 70.0)


def _build_failure_result(scene_id: str, method: str) -> dict:
    return {
        "id": scene_id,
        "voice_in": None,
        "voice_out": None,
        "score": 0,
        "is_silent": True,
        "method": method,
        "matched_text": None,
        "word_indices": None,
        "warning": method,
    }
```

---

## Module: `voice/voice_aligner.py` (REWRITE — main orchestrator)

```python
"""
Voice alignment orchestrator (Plan D: deterministic + LLM fallback).
"""

import asyncio
import json
import shutil
from pathlib import Path
from datetime import datetime

from loguru import logger as log

from voice.voice_scanner import (
    scan_voice_folder,
    get_total_voice_duration,
    VoiceFileMeta,
)
from voice.whisper_runner import transcribe_all_voice_files
from voice.deterministic_aligner import (
    align_deterministic,
    calculate_stats,
    SCORE_THRESHOLD,
)
from voice.llm_fallback import claude_align_scene


async def align_voice_to_scenes(
    scenes: list[dict],
    voice_dir: Path,
    output_dir: Path,
    whisper_model: str = "base",
    language: str = "en",
) -> dict:
    """
    Main entry: align voice to scenes using Plan D.
    
    Args:
        scenes: list of scene dicts (from scenes.json)
        voice_dir: folder containing voice mp3 files
        output_dir: where to save voice_mapping.json
        whisper_model: Whisper model size
        language: "en" or "vi"
    
    Returns:
        voice_mapping dict (also saved to output_dir/voice_mapping.json)
    """
    
    # ============================================================
    # Step 1: Scan voice folder
    # ============================================================
    log.info("Step 1: Scanning voice folder...")
    voice_files = scan_voice_folder(voice_dir)
    total_duration = get_total_voice_duration(voice_files)
    
    # ============================================================
    # Step 2: Whisper transcribe all files
    # ============================================================
    log.info("Step 2: Whisper transcribe...")
    whisper_words = await transcribe_all_voice_files(
        voice_files,
        language=language,
        model_name=whisper_model,
    )
    
    if not whisper_words:
        raise RuntimeError("Whisper produced no words. Check voice file quality.")
    
    # ============================================================
    # Step 3: Deterministic align
    # ============================================================
    log.info("Step 3: Deterministic align...")
    det_results = align_deterministic(scenes, whisper_words)
    
    stats_before = calculate_stats(det_results)
    log.info(f"Deterministic stats: {stats_before}")
    
    # ============================================================
    # Step 4: LLM fallback for low-score scenes
    # ============================================================
    fallback_indices = []
    for i, r in enumerate(det_results):
        if r.get("is_silent"):
            continue
        if r.get("score", 0) < SCORE_THRESHOLD:
            fallback_indices.append(i)
    
    if fallback_indices:
        log.info(f"Step 4: LLM fallback for {len(fallback_indices)} scene(s)...")
        
        for idx in fallback_indices:
            r = det_results[idx]
            scene = next(s for s in scenes if s["id"] == r["id"])
            
            # Determine search window from neighbors
            prev_end_idx = 0
            next_start_idx = len(whisper_words)
            
            for j, other in enumerate(det_results):
                if j == idx:
                    continue
                if other.get("is_silent"):
                    continue
                wi = other.get("word_indices")
                if not wi:
                    continue
                if j < idx:
                    prev_end_idx = max(prev_end_idx, wi[1] + 1)
                if j > idx:
                    next_start_idx = min(next_start_idx, wi[0])
            
            llm_result = await claude_align_scene(
                scene=scene,
                whisper_words=whisper_words,
                search_start_idx=prev_end_idx,
                search_end_idx=next_start_idx - 1,
            )
            
            # Save fallback context
            llm_result["fallback_from_score"] = r.get("score", 0)
            
            # Replace
            det_results[idx] = llm_result
    else:
        log.info("Step 4: No fallback needed, all scenes pass threshold")
    
    # ============================================================
    # Step 5: Extract subtitle phrases for matched scenes
    # ============================================================
    log.info("Step 5: Extract subtitle phrases...")
    for r in det_results:
        if r.get("is_silent"):
            r["subtitle_phrases"] = []
            continue
        
        r["subtitle_phrases"] = extract_subtitle_phrases(
            whisper_words,
            r["voice_in"],
            r["voice_out"],
        )
    
    # ============================================================
    # Step 6: Build voice_mapping with duration_adjusted
    # ============================================================
    voice_scenes = []
    for scene, r in zip(scenes, det_results):
        if scene["id"] != r["id"]:
            log.error(f"ID mismatch: scene {scene['id']} vs result {r['id']}")
            continue
        
        if r.get("is_silent"):
            duration_adjusted = scene.get("duration", 5)  # use design
        else:
            duration_adjusted = r["voice_out"] - r["voice_in"]
        
        voice_scenes.append({
            "id": scene["id"],
            "voice_in": r.get("voice_in"),
            "voice_out": r.get("voice_out"),
            "duration_original": scene.get("duration", 5),
            "duration_adjusted": round(duration_adjusted, 2),
            "is_silent": r.get("is_silent", False),
            "method": r.get("method"),
            "score": r.get("score"),
            "matched_text": r.get("matched_text"),
            "subtitle_phrases": r.get("subtitle_phrases", []),
            **({"warning": r["warning"]} if r.get("warning") else {}),
            **({"reasoning": r["reasoning"]} if r.get("reasoning") else {}),
            **({"fallback_from_score": r["fallback_from_score"]} if "fallback_from_score" in r else {}),
        })
    
    final_stats = calculate_stats(det_results)
    final_stats["llm_fallback_count"] = sum(
        1 for r in det_results if r.get("method", "").startswith("llm")
    )
    
    voice_mapping = {
        "version": "4.0",
        "generated_at": datetime.now().isoformat(),
        "voice_files": [vf.to_dict() for vf in voice_files],
        "total_voice_duration": round(total_duration, 2),
        "scenes": voice_scenes,
        "stats": final_stats,
    }
    
    # ============================================================
    # Step 7: Backup old + save new
    # ============================================================
    output_path = output_dir / "voice_mapping.json"
    
    if output_path.exists():
        backup_path = output_path.with_suffix(".json.v3.bak")
        shutil.copy(output_path, backup_path)
        log.info(f"Backed up old voice_mapping → {backup_path.name}")
    
    output_path.write_text(
        json.dumps(voice_mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Saved {output_path}")
    log.info(f"Final stats: {final_stats}")
    
    return voice_mapping


def extract_subtitle_phrases(
    whisper_words: list[dict],
    voice_in: float,
    voice_out: float,
    max_chars: int = 50,
) -> list[dict]:
    """Extract subtitle phrases from words within voice_in/voice_out range."""
    
    # Get words in range
    scene_words = [
        w for w in whisper_words
        if voice_in <= w["start"] and w["end"] <= voice_out
    ]
    
    if not scene_words:
        return []
    
    # Chunk into phrases by max_chars + punctuation breaks
    phrases = []
    current = []
    current_chars = 0
    
    for w in scene_words:
        word_text = w["word"].strip()
        new_chars = current_chars + len(word_text) + 1
        ends_with_punct = word_text and word_text[-1] in ".,!?;:"
        
        if new_chars > max_chars and current:
            phrases.append(_build_phrase(current))
            current = [w]
            current_chars = len(word_text) + 1
        elif ends_with_punct and new_chars > max_chars * 0.6:
            current.append(w)
            phrases.append(_build_phrase(current))
            current = []
            current_chars = 0
        else:
            current.append(w)
            current_chars = new_chars
    
    if current:
        phrases.append(_build_phrase(current))
    
    return phrases


def _build_phrase(words: list[dict]) -> dict:
    return {
        "text": " ".join(w["word"].strip() for w in words),
        "start": round(words[0]["start"], 2),
        "end": round(words[-1]["end"], 2),
        "words": [
            {
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
            }
            for w in words
        ],
    }
```

---

## Test plan

### Test 1: End-to-end với voice hiện tại

```python
import asyncio
import json
from pathlib import Path
from voice.voice_aligner import align_voice_to_scenes

scenes = json.loads(Path("test_run/scenes.json").read_text())["scenes"]

result = asyncio.run(align_voice_to_scenes(
    scenes=scenes,
    voice_dir=Path("test_run/voice"),
    output_dir=Path("test_run"),
    whisper_model="base",
    language="en",
))

# Verify schema
assert result["version"] == "4.0"
assert len(result["scenes"]) == len(scenes)

# Verify each scene has correct structure
for vs in result["scenes"]:
    if vs["is_silent"]:
        assert vs["voice_in"] is None
        assert vs["duration_adjusted"] == vs["duration_original"]
    else:
        assert vs["voice_in"] is not None
        assert vs["voice_out"] > vs["voice_in"]
        assert vs["duration_adjusted"] > 0
        assert vs["score"] >= 0

# Print stats
print(json.dumps(result["stats"], indent=2))
```

### Test 2: SCENE-03 mismatch case

Voice mp3 hiện tại có SCENE-03 story trải qua silence. Expect:

```
SCENE-03: deterministic score < 75 → fallback LLM
SCENE-03: LLM result method="llm", score >= 75
```

→ Verify SCENE-03 trong output có `method: "llm"` và `voice_out - voice_in` ≈ duration của full story.

### Test 3: All silent scenes

```python
scenes = [
    {"id": "SCENE-01", "story_en": "", "duration": 5},
    {"id": "SCENE-02", "story_en": None, "duration": 8},
]
# Should not call LLM at all (all silent)
result = asyncio.run(align_voice_to_scenes(scenes, ...))

for vs in result["scenes"]:
    assert vs["is_silent"] == True
    assert vs["method"] == "silent"
```

### Test 4: Verify backup

```python
# Run alignment
asyncio.run(align_voice_to_scenes(...))

# Run again
asyncio.run(align_voice_to_scenes(...))

# Verify backup exists
assert Path("test_run/voice_mapping.json.v3.bak").exists()
```

### Test 5: Calibration log

```bash
# Run with current voice + scenes
python -c "import asyncio; from voice.voice_aligner import align_voice_to_scenes; ..."

# Inspect log:
# Should print per-scene scores so user có thể tweak threshold sau
```

---

## Build order

1. Create `voice/llm_fallback.py` (45 phút)
2. Rewrite `voice/voice_aligner.py` (45 phút)
3. Test 1 với voice hiện tại (15 phút)
4. Verify SCENE-03 fallback work (15 phút)
5. Test 3, 4, 5 (15 phút)
6. Commit

**Total: ~1.5-2h**

---

## Confirm trước khi code

- [ ] Phase 1 + 2 đã build xong và test pass
- [ ] Claude CLI available và login Pro/Max
- [ ] ANTHROPIC_API_KEY env var KHÔNG set (test: `echo $env:ANTHROPIC_API_KEY` trống)
- [ ] Test voice hiện tại có SCENE-03 mismatch để verify LLM fallback work

→ Build xong test pass → Phase 4 (ASS karaoke).
