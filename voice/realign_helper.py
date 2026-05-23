"""Manual realign helpers for the review dialog.

Each helper trims the matched range of one scene and gives the leftover words
to its neighbour, then recomputes the affected scene scores via fuzzy ratio.

Both helpers mutate `voice_mapping` in place and also return it for chaining.
The mapping shape is the v4.0 Plan D dict: top-level `scenes`, each with
`voice_in`, `voice_out`, `matched_text`, `score`, `subtitle_phrases`.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger as log
from rapidfuzz import fuzz

from voice.voice_aligner import extract_subtitle_phrases


def _normalize(text: str | None) -> str:
    s = (text or "").lower().strip()
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _words_in_range(
    whisper_words: list[dict[str, Any]],
    voice_in: float,
    voice_out: float,
) -> list[dict[str, Any]]:
    return [
        w for w in whisper_words
        if voice_in <= w["start"] and w["end"] <= voice_out
    ]


def _scene_script(scenes_data: list[dict[str, Any]], scene_id: str) -> str:
    for s in scenes_data:
        if s["id"] == scene_id:
            return (s.get("script") or "").strip()
    return ""


def _refresh_assignment(
    assignment: dict[str, Any],
    whisper_words: list[dict[str, Any]],
    script: str,
) -> None:
    """Recompute matched_text + score + subtitle_phrases from the current voice_in/voice_out."""
    voice_in = assignment.get("voice_in")
    voice_out = assignment.get("voice_out")
    if voice_in is None or voice_out is None or voice_in >= voice_out:
        return

    words = _words_in_range(whisper_words, voice_in, voice_out)
    matched_text = " ".join(w["word"].strip() for w in words)
    assignment["matched_text"] = matched_text

    if script:
        assignment["score"] = float(
            fuzz.ratio(_normalize(script), _normalize(matched_text))
        )

    assignment["subtitle_phrases"] = extract_subtitle_phrases(
        whisper_words, voice_in, voice_out
    )
    assignment["duration_adjusted"] = round(voice_out - voice_in, 2)


def move_tail_to_next(
    voice_mapping: dict[str, Any],
    scene_id: str,
    whisper_words: list[dict[str, Any]],
    scenes_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Shrink the current scene's tail until it best matches the script.

    Spillover words (the trimmed tail) are donated to the next non-silent
    scene by extending its `voice_in` earlier. Both scenes' scores are
    refreshed.
    """
    scenes = voice_mapping["scenes"]
    cur_idx = next((i for i, s in enumerate(scenes) if s["id"] == scene_id), -1)
    if cur_idx < 0:
        raise ValueError(f"Scene {scene_id} not found in voice_mapping")
    if cur_idx >= len(scenes) - 1:
        raise ValueError(f"Scene {scene_id} is the last scene — nothing to move tail into")

    cur = scenes[cur_idx]
    if cur.get("is_silent"):
        raise ValueError(f"Cannot move from silent scene {scene_id}")

    script = _scene_script(scenes_data, scene_id)
    if not script:
        raise ValueError(f"Scene {scene_id} has no script")

    cur_words = _words_in_range(whisper_words, cur["voice_in"], cur["voice_out"])
    if len(cur_words) < 2:
        raise ValueError("Too few words in current range to split")

    script_norm = _normalize(script)
    best_end = len(cur_words) - 1
    best_score = 0.0
    min_keep = max(2, len(cur_words) // 3)
    for end_idx in range(min_keep - 1, len(cur_words)):
        candidate = " ".join(_normalize(w["word"]) for w in cur_words[: end_idx + 1])
        score = float(fuzz.ratio(script_norm, candidate))
        if score > best_score:
            best_score = score
            best_end = end_idx

    if best_end >= len(cur_words) - 1:
        log.info(f"{scene_id}: best match keeps all words — nothing to donate")
        return voice_mapping

    new_cur_out = cur_words[best_end]["end"]
    donated_first_start = cur_words[best_end + 1]["start"]

    cur["voice_out"] = round(new_cur_out, 2)
    _refresh_assignment(cur, whisper_words, script)

    nxt = scenes[cur_idx + 1]
    if not nxt.get("is_silent") and nxt.get("voice_in") is not None:
        if donated_first_start < nxt["voice_in"]:
            nxt["voice_in"] = round(donated_first_start, 2)
            nxt_script = _scene_script(scenes_data, nxt["id"])
            _refresh_assignment(nxt, whisper_words, nxt_script)

    log.info(
        f"Moved tail of {scene_id}: voice_out={cur['voice_out']:.2f}s "
        f"score={cur.get('score', 0):.1f}"
    )
    return voice_mapping


def move_head_to_previous(
    voice_mapping: dict[str, Any],
    scene_id: str,
    whisper_words: list[dict[str, Any]],
    scenes_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Shrink the current scene's head until it best matches the script.

    Spillover head words are donated to the previous non-silent scene by
    extending its `voice_out` later.
    """
    scenes = voice_mapping["scenes"]
    cur_idx = next((i for i, s in enumerate(scenes) if s["id"] == scene_id), -1)
    if cur_idx < 0:
        raise ValueError(f"Scene {scene_id} not found in voice_mapping")
    if cur_idx == 0:
        raise ValueError(f"Scene {scene_id} is the first scene — nothing to move head into")

    cur = scenes[cur_idx]
    if cur.get("is_silent"):
        raise ValueError(f"Cannot move from silent scene {scene_id}")

    script = _scene_script(scenes_data, scene_id)
    if not script:
        raise ValueError(f"Scene {scene_id} has no script")

    cur_words = _words_in_range(whisper_words, cur["voice_in"], cur["voice_out"])
    if len(cur_words) < 2:
        raise ValueError("Too few words in current range to split")

    script_norm = _normalize(script)
    best_start = 0
    best_score = 0.0
    max_skip = (2 * len(cur_words)) // 3
    for start_idx in range(max_skip + 1):
        candidate = " ".join(_normalize(w["word"]) for w in cur_words[start_idx:])
        score = float(fuzz.ratio(script_norm, candidate))
        if score > best_score:
            best_score = score
            best_start = start_idx

    if best_start == 0:
        log.info(f"{scene_id}: best match keeps all words — nothing to donate")
        return voice_mapping

    new_cur_in = cur_words[best_start]["start"]
    donated_last_end = cur_words[best_start - 1]["end"]

    cur["voice_in"] = round(new_cur_in, 2)
    _refresh_assignment(cur, whisper_words, script)

    prev = scenes[cur_idx - 1]
    if not prev.get("is_silent") and prev.get("voice_out") is not None:
        if donated_last_end > prev["voice_out"]:
            prev["voice_out"] = round(donated_last_end, 2)
            prev_script = _scene_script(scenes_data, prev["id"])
            _refresh_assignment(prev, whisper_words, prev_script)

    log.info(
        f"Moved head of {scene_id}: voice_in={cur['voice_in']:.2f}s "
        f"score={cur.get('score', 0):.1f}"
    )
    return voice_mapping
