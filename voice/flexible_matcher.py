"""Per-beat scene matcher with flexible window + weighted scoring.

Per sprint_1 §9: more robust than the same-length-window matcher in
deterministic_aligner.py. Key differences:

1. Variable window length: 70-135% of scene word count (handles whisper
   merging/splitting words and minor recognition errors).
2. Weighted score: start_anchor (25%) + end_anchor (25%) +
   full_window (35%) + order_continuity (15%).
3. LOCAL cursor — reset to 0 at the start of every beat (NEVER global).
   Bounded backward lookahead (cursor - 3 words) to avoid one bad match
   blocking the rest of the beat.
4. Single-scene beat shortcut: if a beat has exactly one voiced scene,
   that scene gets the FULL beat voice window.
5. **no_match keeps voiced** — never silently converts to is_silent.
   Spec acceptance criterion #13.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger as log
from rapidfuzz import fuzz


# Thresholds (per spec §4 + §9)
MATCH_THRESHOLD = 0.82                  # 82% → accepted (or 82 on 0-100 scale)
MIN_WINDOW_RATIO = 0.70                 # window length lower bound
MAX_WINDOW_RATIO = 1.35                 # window length upper bound
ANCHOR_SIZE_MIN = 3                     # min words for anchor
ANCHOR_SIZE_MAX = 7                     # max words for anchor
BACKWARD_LOOKAHEAD_WORDS = 3            # search_start = max(0, cursor - 3)
MIN_START_ANCHOR_SCORE = 30             # below this → no_match (anchor not found)

# Weighted scoring (per §9.3)
W_START_ANCHOR = 0.25
W_END_ANCHOR = 0.25
W_FULL_WINDOW = 0.35
W_ORDER_CONTINUITY = 0.15


@dataclass
class MatchResult:
    """One scene's match outcome inside a beat."""
    scene_id: str
    matched: bool                       # True only when score >= threshold
    voice_in: Optional[float]           # global timestamp (None if not matched)
    voice_out: Optional[float]
    score: float                        # 0-100
    word_start_index: Optional[int]     # global index into whisper_words
    word_end_index: Optional[int]       # inclusive
    matched_text: str = ""
    method: str = "within_beat_flexible_fuzzy"
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

_TAG_PARENS_RE = re.compile(r"\([^)]+\)")
_TAG_BRACKETS_RE = re.compile(r"\[[^\]]+\]")
_NON_WORD_RE = re.compile(r"[^a-z0-9'\s]")
_MULTI_WS_RE = re.compile(r"\s+")
_WORD_PUNCT_RE = re.compile(r"[^a-z0-9']")


def normalize_text(text: str) -> list[str]:
    """Tokenize script text per spec §9.1.

    - strip (emotion) tags
    - strip [pause] / [emphasis] markers
    - normalize dashes/quotes
    - lowercase + drop punctuation
    """
    if not text:
        return []
    s = _TAG_PARENS_RE.sub(" ", text)
    s = _TAG_BRACKETS_RE.sub(" ", s)
    s = s.replace("—", " ").replace("–", " ")
    s = s.replace("\u201c", '"').replace("\u201d", '"')
    s = s.replace("\u2018", "'").replace("\u2019", "'")
    s = s.lower()
    s = _NON_WORD_RE.sub(" ", s)
    s = _MULTI_WS_RE.sub(" ", s).strip()
    return s.split()


def normalize_whisper_word(word: str) -> str:
    """Per spec §9.1 — single-word normalization for Whisper output."""
    w = (word or "").lower()
    w = _WORD_PUNCT_RE.sub("", w)
    return w


def _anchor_size(n_words: int) -> int:
    """Anchor length scales with scene size, clamped to [3, 7]."""
    if n_words < ANCHOR_SIZE_MIN:
        return max(1, n_words)
    return min(ANCHOR_SIZE_MAX, max(ANCHOR_SIZE_MIN, n_words // 3))


# ---------------------------------------------------------------------------
# Scoring components
# ---------------------------------------------------------------------------

def _window_text(beat_words: list[dict], start: int, end: int) -> str:
    """Concat normalized whisper words [start, end] inclusive."""
    parts = []
    for i in range(start, min(end + 1, len(beat_words))):
        nw = normalize_whisper_word(beat_words[i].get("word", ""))
        if nw:
            parts.append(nw)
    return " ".join(parts)


def _continuity_score(start_idx: int, cursor: int) -> float:
    """Higher when the match starts close to the cursor.

    Cursor is the local word index inside the beat after the last accepted
    match. Strict order: start_idx == cursor → 100. Drifts down as the
    match begins further away. Always >= 0.
    """
    if start_idx < cursor:
        # Backward lookahead — small penalty
        dist = cursor - start_idx
        return max(0.0, 100.0 - dist * 20.0)
    dist = start_idx - cursor
    # Gentle decay so a small gap doesn't dominate
    return max(0.0, 100.0 - dist * 8.0)


# ---------------------------------------------------------------------------
# Per-scene matcher (within one beat)
# ---------------------------------------------------------------------------

def find_match_in_beat(
    scene_id: str,
    scene_text: str,
    beat_words: list[dict],
    local_cursor: int,
) -> MatchResult:
    """Find best match for ONE voiced scene inside its beat word window.

    Args:
        scene_id: scene id (for logging)
        scene_text: scene.script (raw)
        beat_words: words filtered to this beat's [voice_in, voice_out],
            each carrying a `_beat_word_idx` field
        local_cursor: position to start searching from (relative to beat words)

    Returns:
        MatchResult — matched=True iff score >= MATCH_THRESHOLD * 100
    """
    scene_words = normalize_text(scene_text)
    if not scene_words:
        return MatchResult(
            scene_id=scene_id, matched=False, voice_in=None, voice_out=None,
            score=0.0, word_start_index=None, word_end_index=None,
            warnings=["scene_script_empty_after_normalize"],
        )

    if not beat_words:
        return MatchResult(
            scene_id=scene_id, matched=False, voice_in=None, voice_out=None,
            score=0.0, word_start_index=None, word_end_index=None,
            warnings=["beat_has_no_words"],
        )

    n_scene = len(scene_words)
    n_beat = len(beat_words)
    anchor_size = _anchor_size(n_scene)

    start_anchor = " ".join(scene_words[:anchor_size])
    end_anchor = " ".join(scene_words[-anchor_size:])

    # ---- Step 1: Find best START position ----
    # Allow small backward lookahead (avoid one bad match blocking everything)
    search_start = max(0, local_cursor - BACKWARD_LOOKAHEAD_WORDS)
    search_end = max(search_start + 1, n_beat - anchor_size + 1)

    best_start_score = 0.0
    best_start_idx = -1

    for i in range(search_start, search_end):
        if i + anchor_size > n_beat:
            break
        window = _window_text(beat_words, i, i + anchor_size - 1)
        s = fuzz.ratio(start_anchor, window)
        if s > best_start_score:
            best_start_score = s
            best_start_idx = i

    if best_start_idx == -1 or best_start_score < MIN_START_ANCHOR_SCORE:
        # No usable anchor — scene story likely not in this beat at all
        return MatchResult(
            scene_id=scene_id, matched=False, voice_in=None, voice_out=None,
            score=round(best_start_score, 1),
            word_start_index=None, word_end_index=None,
            warnings=[
                f"no_start_anchor (best score {best_start_score:.1f} < {MIN_START_ANCHOR_SCORE})"
            ],
        )

    # ---- Step 2: Find best END position with flexible window ----
    # Window length varies 70-135% of scene
    min_len = max(anchor_size, int(n_scene * MIN_WINDOW_RATIO))
    max_len = max(min_len, int(n_scene * MAX_WINDOW_RATIO))

    end_search_lo = best_start_idx + min_len - 1
    end_search_hi = min(n_beat - 1, best_start_idx + max_len - 1)

    if end_search_hi < end_search_lo:
        end_search_hi = end_search_lo

    best_end_score = 0.0
    best_end_idx = -1

    for end_i in range(end_search_lo, end_search_hi + 1):
        anchor_start = max(best_start_idx, end_i - anchor_size + 1)
        window = _window_text(beat_words, anchor_start, end_i)
        s = fuzz.ratio(end_anchor, window)
        if s > best_end_score:
            best_end_score = s
            best_end_idx = end_i

    if best_end_idx == -1:
        # fallback: assume scene takes ~n_scene words
        best_end_idx = min(best_start_idx + n_scene - 1, n_beat - 1)
        best_end_score = 50.0

    # ---- Step 3: Full window match (token sort handles minor reordering) ----
    full_window = _window_text(beat_words, best_start_idx, best_end_idx)
    full_scene = " ".join(scene_words)
    full_score = fuzz.token_sort_ratio(full_scene, full_window)

    # ---- Step 4: Continuity score (closer to cursor = better) ----
    continuity = _continuity_score(best_start_idx, local_cursor)

    # ---- Combined ----
    combined = (
        W_START_ANCHOR * best_start_score
        + W_END_ANCHOR * best_end_score
        + W_FULL_WINDOW * full_score
        + W_ORDER_CONTINUITY * continuity
    )
    combined = round(combined, 1)

    # ---- Resolve to global timestamps via beat_words[i]'s _beat_word_idx ----
    # beat_words[i] is the i-th word inside this beat; .start/.end are global
    voice_in = float(beat_words[best_start_idx]["start"])
    voice_out = float(beat_words[best_end_idx]["end"])
    matched_text = " ".join(
        beat_words[i].get("word", "").strip()
        for i in range(best_start_idx, best_end_idx + 1)
    )

    matched = combined >= MATCH_THRESHOLD * 100
    log.debug(
        f"{scene_id}: start={best_start_score:.0f} end={best_end_score:.0f} "
        f"full={full_score:.0f} cont={continuity:.0f} → {combined:.1f} "
        f"{'PASS' if matched else 'FAIL'} "
        f"[{best_start_idx}..{best_end_idx}] {voice_in:.2f}-{voice_out:.2f}s"
    )

    return MatchResult(
        scene_id=scene_id,
        matched=matched,
        voice_in=voice_in,
        voice_out=voice_out,
        score=combined,
        word_start_index=best_start_idx,
        word_end_index=best_end_idx,
        matched_text=matched_text,
        method="within_beat_flexible_fuzzy",
        warnings=[],
    )
