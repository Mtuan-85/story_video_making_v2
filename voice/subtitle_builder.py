"""Subtitle phrase builder — fallback path when Claude fails.

Groups raw Whisper words into phrases with start/end derived from the words'
own timestamps. Breaks at punctuation or after `max_words`.
"""

from __future__ import annotations

import re
from typing import Any

from core.voice_mapping import SubtitlePhrase

_PUNCT_END = ".!?"


def split_text_to_phrases(text: str, max_words: int = 8) -> list[str]:
    """Split a string into rough phrases — punctuation + word-count cap."""
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    phrases: list[str] = []
    for part in parts:
        words = part.split()
        for i in range(0, len(words), max_words):
            chunk = " ".join(words[i : i + max_words])
            if chunk:
                phrases.append(chunk)
    return phrases


def build_phrases_from_whisper_words(
    words: list[dict[str, Any]],
    max_words: int = 8,
) -> list[SubtitlePhrase]:
    """Group consecutive Whisper words into SubtitlePhrase entries.

    Each phrase's `start` is the first word's start time, `end` is the last
    word's end time. Breaks on terminal punctuation or `max_words`.
    """
    if not words:
        return []

    phrases: list[SubtitlePhrase] = []
    current_words: list[tuple[str, float]] = []
    current_start: float | None = None

    for w in words:
        word_text = (w.get("word") or "").strip()
        if not word_text:
            continue
        if current_start is None:
            current_start = float(w.get("start", 0.0))

        end_ts = float(w.get("end", current_start))
        current_words.append((word_text, end_ts))

        ends_with_punct = word_text[-1] in _PUNCT_END
        is_max = len(current_words) >= max_words
        if ends_with_punct or is_max:
            text = " ".join(t for t, _ in current_words)
            phrases.append(
                SubtitlePhrase(
                    text=text,
                    start=current_start,
                    end=current_words[-1][1],
                )
            )
            current_words = []
            current_start = None

    if current_words and current_start is not None:
        text = " ".join(t for t, _ in current_words)
        phrases.append(
            SubtitlePhrase(
                text=text,
                start=current_start,
                end=current_words[-1][1],
            )
        )
    return phrases
