"""Deterministic fuzzy matching: scenes story -> Whisper words timestamps.

No LLM. Uses rapidfuzz for text similarity.

Algorithm:
1. For each scene (in order):
2.   Read scene.script.
3.   Extract first N words as start anchor, last N as end anchor
4.   Search start anchor in [cursor, cursor+SEARCH_WINDOW] of whisper words
5.   Search end anchor in window after start match
6.   Compute combined score (start_anchor + end_anchor + full_match)
7.   If score >= THRESHOLD: use deterministic result
8.   Advance cursor past this scene's last word
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

from loguru import logger as log
from rapidfuzz import fuzz


# === Configurable thresholds ===
SCORE_THRESHOLD = 75.0           # Below this -> fallback LLM (Phase 3)
MIN_ANCHOR_SIZE = 3              # Minimum words for anchor
MAX_ANCHOR_SIZE = 7              # Maximum words for anchor
SEARCH_WINDOW = 50               # Word lookahead from cursor
END_ANCHOR_TOLERANCE = 0.5       # +/-50% of scene length to search end anchor


@dataclass
class MatchResult:
    voice_in: float
    voice_out: float
    score: float
    matched_text: str
    word_indices: tuple        # (start_idx, end_idx) inclusive
    method: str = "deterministic"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["word_indices"] = list(self.word_indices)  # tuple -> list for JSON
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


def scene_script(scene: dict) -> str:
    """Return the canonical narration script for this scene."""
    return str(scene.get("script") or "").strip()


def get_anchor_size(scene_words_count: int) -> int:
    """Determine anchor size based on scene length."""
    if scene_words_count < MIN_ANCHOR_SIZE:
        return scene_words_count
    return min(MAX_ANCHOR_SIZE, max(MIN_ANCHOR_SIZE, scene_words_count // 3))


def find_match_with_anchors(
    scene_words: list[str],
    whisper_words: list[dict],
    cursor: int,
) -> Optional[MatchResult]:
    """Find best match for scene_words starting from cursor in whisper_words.

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
    best_start_score = 0.0

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
        best_end_score = 50.0
    else:
        best_end_idx = -1
        best_end_score = 0.0

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
            best_end_score = 50.0

    # === Step 3: Verify with full match ===
    full_whisper = " ".join(
        normalize_word(whisper_words[j]["word"])
        for j in range(best_start_idx, best_end_idx + 1)
    )
    full_scene = " ".join(scene_words)

    full_score = fuzz.token_sort_ratio(full_scene, full_whisper)

    combined_score = (
        best_start_score * 0.3
        + best_end_score * 0.3
        + full_score * 0.4
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
    language: str = "en",
) -> list[dict]:
    """Run deterministic align for all scenes.

    Returns list of result dicts (one per scene), with:
    id, voice_in, voice_out, score, is_silent, method, matched_text, word_indices

    Silent scenes (empty script) marked is_silent=True.
    Unmatched scenes (no start anchor) also is_silent=True with warning.
    """
    results: list[dict] = []
    cursor = 0

    for scene in scenes:
        scene_id = scene["id"]
        story = scene_script(scene)

        if not story:
            log.info(f"{scene_id}: silent (empty script)")
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

        status = "PASS" if match.score >= SCORE_THRESHOLD else "FAIL"
        log.info(
            f"{scene_id}: deterministic score={match.score:.1f} {status} "
            f"({match.voice_in:.2f}-{match.voice_out:.2f}s)"
        )

        result = match.to_dict()
        result["id"] = scene_id
        result["is_silent"] = False
        results.append(result)

        cursor = match.word_indices[1] + 1

    return results


def calculate_stats(results: list[dict]) -> dict:
    """Calculate alignment statistics."""
    total = len(results)
    silent = sum(1 for r in results if r.get("method") == "silent")
    no_match = sum(1 for r in results if r.get("method") == "no_match")
    deterministic_pass = sum(
        1 for r in results
        if r.get("method") == "deterministic" and (r.get("score") or 0) >= SCORE_THRESHOLD
    )
    deterministic_fail = sum(
        1 for r in results
        if r.get("method") == "deterministic" and (r.get("score") or 0) < SCORE_THRESHOLD
    )

    return {
        "total_scenes": total,
        "deterministic_pass": deterministic_pass,
        "deterministic_fail_need_fallback": deterministic_fail,
        "silent": silent,
        "no_match": no_match,
    }
