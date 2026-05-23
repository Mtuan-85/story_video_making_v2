"""Plan D voice alignment orchestrator.

Pipeline:
    1. Scan voice folder → list of files with cumulative offsets.
    2. Whisper transcribe all files → flat word list with global timestamps.
    3. Deterministic fuzzy align each scene's `script` against the transcript.
    4. LLM fallback (Claude) for scenes whose deterministic score is below
       threshold (and not silent).
    5. Extract subtitle phrases (with word-level timestamps) per scene for
       ASS karaoke rendering.

Output: voice_mapping.json v4.0 dict (also returned by `align_voice_to_scenes`).
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from loguru import logger as log

from voice.deterministic_aligner import (
    SCORE_THRESHOLD,
    align_deterministic,
    calculate_stats,
)
from voice.llm_fallback import claude_align_scene
from voice.voice_scanner import (
    get_total_voice_duration,
    scan_voice_folder,
)
from voice.whisper_runner import transcribe_all_voice_files


async def align_voice_to_scenes(
    scenes: list[dict],
    voice_dir: Path,
    output_dir: Path,
    whisper_model: str = "base",
    language: str = "en",
) -> dict:
    """Plan D entry: align voice to scenes (deterministic + LLM fallback).

    Args:
        scenes: list of scene dicts (from scenes.json) — each must have id +
            script (may be empty/None for silent scenes) and duration.
        voice_dir: folder containing voice mp3 files.
        output_dir: where to save voice_mapping.json (and a .v3.bak backup
            of the previous file, if any).
        whisper_model: Whisper model size (default "base").
        language: "en" or "vi".

    Returns:
        voice_mapping dict (also persisted to output_dir/voice_mapping.json).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("Step 1: Scanning voice folder...")
    voice_files = scan_voice_folder(voice_dir)
    total_duration = get_total_voice_duration(voice_files)

    log.info("Step 2: Whisper transcribe...")
    whisper_words = await transcribe_all_voice_files(
        voice_files,
        language=language,
        model_name=whisper_model,
    )
    if not whisper_words:
        raise RuntimeError("Whisper produced no words. Check voice file quality.")

    log.info("Step 3: Deterministic align...")
    det_results = align_deterministic(scenes, whisper_words, language=language)
    log.info(f"Deterministic stats: {calculate_stats(det_results)}")

    fallback_indices = [
        i for i, r in enumerate(det_results)
        if not r.get("is_silent") and (r.get("score") or 0) < SCORE_THRESHOLD
    ]

    if fallback_indices:
        log.info(f"Step 4: LLM fallback for {len(fallback_indices)} scene(s)...")
        for idx in fallback_indices:
            r = det_results[idx]
            scene = next(s for s in scenes if s["id"] == r["id"])

            prev_end_idx = 0
            next_start_idx = len(whisper_words)

            for j, other in enumerate(det_results):
                if j == idx or other.get("is_silent"):
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
                language=language,
            )
            llm_result["fallback_from_score"] = r.get("score", 0)
            det_results[idx] = llm_result
    else:
        log.info("Step 4: No fallback needed, all scenes pass threshold")

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

    voice_scenes: list[dict] = []
    for scene, r in zip(scenes, det_results):
        if scene["id"] != r["id"]:
            log.error(f"ID mismatch: scene {scene['id']} vs result {r['id']}")
            continue

        if r.get("is_silent"):
            duration_adjusted = scene.get("duration", 5)
        else:
            duration_adjusted = r["voice_out"] - r["voice_in"]

        entry = {
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
        }
        if r.get("warning"):
            entry["warning"] = r["warning"]
        if r.get("reasoning"):
            entry["reasoning"] = r["reasoning"]
        if "fallback_from_score" in r:
            entry["fallback_from_score"] = r["fallback_from_score"]
        voice_scenes.append(entry)

    voice_scenes = add_freeze_pauses(voice_scenes)

    final_stats = calculate_stats(det_results)
    final_stats["llm_fallback_count"] = sum(
        1 for r in det_results if (r.get("method") or "").startswith("llm")
    )

    voice_mapping = {
        "version": "4.0",
        "generated_at": datetime.now().isoformat(),
        "voice_files": [vf.to_dict() for vf in voice_files],
        "total_voice_duration": round(total_duration, 2),
        "scenes": voice_scenes,
        "stats": final_stats,
    }

    output_path = output_dir / "voice_mapping.json"
    if output_path.exists():
        backup_path = output_path.with_suffix(".json.v3.bak")
        shutil.copy(output_path, backup_path)
        log.info(f"Backed up old voice_mapping -> {backup_path.name}")

    output_path.write_text(
        json.dumps(voice_mapping, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # Save whisper words alongside so the review dialog can call realign helpers
    # without re-running Whisper.
    words_path = output_dir / "whisper_words.json"
    words_path.write_text(
        json.dumps(whisper_words, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info(f"Saved {output_path} + {words_path.name}")
    log.info(f"Final stats: {final_stats}")

    return voice_mapping


def add_freeze_pauses(voice_scenes: list[dict]) -> list[dict]:
    """Set ``freeze_pause_after`` for each scene = gap to next non-silent voice_in.

    Voice-led timeline (Sprint 3 final): each rendered scene = voice part +
    freeze-frame for the natural pause to the next scene. Silent scenes and
    the last non-silent scene get 0 (no freeze tail).

    Empty-script scenes are timeline anchors: they keep their design duration
    and should consume voice gaps before any residual freeze is added.
    Mutates and returns the list for ergonomics.
    """
    n = len(voice_scenes)
    for i, vs in enumerate(voice_scenes):
        if vs.get("is_silent"):
            vs["freeze_pause_after"] = 0.0
            continue

        next_voice_in = None
        silent_design_between = 0.0
        for j in range(i + 1, n):
            nxt = voice_scenes[j]
            if nxt.get("is_silent"):
                silent_design_between += float(
                    nxt.get("render_duration")
                    or nxt.get("duration_adjusted")
                    or nxt.get("duration_original")
                    or 0.0
                )
                continue
            if nxt.get("voice_in") is not None:
                next_voice_in = nxt["voice_in"]
                break

        if next_voice_in is None:
            vs["freeze_pause_after"] = 0.0
        else:
            pause = next_voice_in - (vs.get("voice_out") or 0) - silent_design_between
            vs["freeze_pause_after"] = round(max(0.0, pause), 3)
    return voice_scenes


def extract_subtitle_phrases(
    whisper_words: list[dict],
    voice_in: float,
    voice_out: float,
    max_chars: int = 50,
) -> list[dict]:
    """Extract subtitle phrases from words within voice_in/voice_out range."""
    scene_words = [
        w for w in whisper_words
        if voice_in <= w["start"] and w["end"] <= voice_out
    ]
    if not scene_words:
        return []

    phrases: list[dict] = []
    current: list[dict] = []
    current_chars = 0

    for w in scene_words:
        word_text = w["word"].strip()
        new_chars = current_chars + len(word_text) + 1
        ends_with_punct = bool(word_text) and word_text[-1] in ".,!?;:"

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
