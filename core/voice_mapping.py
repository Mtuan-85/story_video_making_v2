"""Schema for voice_mapping.json v4.0 — Plan D deterministic + LLM fallback.

v4.0 changes vs v3.0:
  - Phase grouping removed. Scenes are aligned individually via deterministic
    fuzzy match against Whisper transcript, with LLM fallback for low-score
    cases.
  - Top-level `scenes` array replaces the per-voice-file nesting.
  - `voice_files` only carries metadata (file/duration/offset).
  - `subtitle_phrases` now carry word-level timestamps for ASS karaoke.

Produced by `voice/voice_aligner.py::align_voice_to_scenes` (Whisper +
deterministic_aligner + llm_fallback).
Consumed by `render/composite_v2.py` + `voice/ass_generator.py`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WordTimestamp(BaseModel):
    model_config = ConfigDict(extra="allow")

    word: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class SubtitlePhrase(BaseModel):
    model_config = ConfigDict(extra="allow")

    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    words: list[WordTimestamp] = Field(default_factory=list)


RenderMode = Literal["voice", "design", "custom"]


class SceneVoiceAssignment(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    voice_in: float | None = None
    voice_out: float | None = None
    duration_original: float = Field(default=0.0, ge=0)
    duration_adjusted: float = Field(default=0.0, ge=0)
    is_silent: bool = False
    method: str | None = None  # "deterministic" | "llm" | "llm_fallback" | "manual" | None
    score: float | None = None
    matched_text: str | None = None
    subtitle_phrases: list[SubtitlePhrase] = Field(default_factory=list)
    warning: str | None = None
    reasoning: str | None = None
    fallback_from_score: float | None = None
    # Render duration override (Step 5/6 of Phase 6).
    render_mode: RenderMode = "voice"
    render_duration: float | None = None  # populated on save; falls back to duration_adjusted at render time
    custom_duration: float | None = None  # only meaningful when render_mode == "custom"


class VoiceFileMeta(BaseModel):
    """Top-level voice file metadata (cumulative offsets in global timeline)."""

    model_config = ConfigDict(extra="allow")

    file: str  # filename only, e.g. "voice1.mp3"
    duration: float = Field(ge=0)
    offset: float = Field(default=0.0, ge=0)


class VoiceMappingStats(BaseModel):
    model_config = ConfigDict(extra="allow")

    total_scenes: int = 0
    deterministic_pass: int = 0
    deterministic_fail_need_fallback: int = 0
    silent: int = 0
    no_match: int = 0
    llm_fallback_count: int = 0


class VoiceMapping(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: Literal["4.0"] = "4.0"
    generated_at: str | None = None
    voice_files: list[VoiceFileMeta] = Field(default_factory=list)
    total_voice_duration: float = Field(default=0.0, ge=0)
    scenes: list[SceneVoiceAssignment] = Field(default_factory=list)
    stats: VoiceMappingStats = Field(default_factory=VoiceMappingStats)

    # ------------------------------------------------------------------
    # Convenience accessors (compatibility shims for callers that used the
    # old v3.0 API while we migrate the rest of the code base).
    # ------------------------------------------------------------------

    def get_assignment_for_scene(self, scene_id: str) -> SceneVoiceAssignment | None:
        for s in self.scenes:
            if s.id == scene_id:
                return s
        return None

    def is_silent(self, scene_id: str) -> bool:
        s = self.get_assignment_for_scene(scene_id)
        return bool(s and s.is_silent)

    @property
    def silent_scenes(self) -> list[str]:
        return [s.id for s in self.scenes if s.is_silent]

    def to_render_dict(self) -> dict[str, Any]:
        """Plain dict shape consumed by composite_v2 / ass_generator."""
        return self.model_dump(mode="json")
