"""Schema for voice_mapping.json v3 — voice-first phase grouping.

v3 changes vs v2:
  - Voice is grouped into PHASES (consecutive segments separated by silence > threshold).
  - Each phase contains 1+ scenes; scale factor scales the design durations to fit
    the phase's actual voice duration WHILE PRESERVING THE DESIGN RATIO.
  - Each scene assignment carries `duration_original`, `duration_adjusted`,
    `scale_factor`, `phase_id` so render can use `duration_adjusted` directly
    (no more voice_out - voice_in override that crushed visuals).

Produced by `voice/voice_aligner.py` (Whisper + Claude phase mapper).
Consumed by `render/composite.py` to time each scene's visual + voice slice.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SubtitlePhrase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)


class SceneVoiceAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    voice_in: float = Field(ge=0)
    voice_out: float = Field(ge=0)
    # v3 voice-first additions:
    duration_original: float = Field(default=0.0, ge=0)
    duration_adjusted: float = Field(default=0.0, ge=0)
    scale_factor: float = Field(default=1.0, ge=0)
    phase_id: int = Field(default=0, ge=0)
    # Lifecycle:
    confidence: float = Field(default=1.0, ge=0, le=1)
    method: Literal["whisper_claude", "user_override"] = "whisper_claude"
    subtitle_phrases: list[SubtitlePhrase] = Field(default_factory=list)


class VoicePhaseMeta(BaseModel):
    """Top-level phase summary so the review dialog can render a grouping view."""

    model_config = ConfigDict(extra="forbid")

    phase_id: int = Field(ge=1)
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    duration: float = Field(ge=0)
    scenes: list[str] = Field(default_factory=list)
    scale_factor: float = Field(default=1.0, ge=0)
    text: str = ""


class VoiceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str  # project-relative, e.g. "voice/voice_01.mp3"
    duration: float = Field(ge=0)
    transcript: str = ""
    phases: list[VoicePhaseMeta] = Field(default_factory=list)
    scenes: list[SceneVoiceAssignment] = Field(default_factory=list)


class VoiceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["3.0"] = "3.0"
    voice_files: list[VoiceFile] = Field(default_factory=list)
    silent_scenes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def get_assignment_for_scene(
        self, scene_id: str
    ) -> tuple[VoiceFile, SceneVoiceAssignment] | None:
        for vf in self.voice_files:
            for s in vf.scenes:
                if s.id == scene_id:
                    return vf, s
        return None

    def is_silent(self, scene_id: str) -> bool:
        return scene_id in self.silent_scenes
