"""Schema for voice_mapping.json v2 — voice files + per-scene timestamps.

Produced by `voice/voice_aligner.py` (Whisper + Claude). Consumed by
`render/composite.py` to extract the right slice of audio + render
subtitle drawtext for each scene.
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
    confidence: float = Field(default=1.0, ge=0, le=1)
    method: Literal["whisper_claude", "user_override"] = "whisper_claude"
    subtitle_phrases: list[SubtitlePhrase] = Field(default_factory=list)


class VoiceFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str  # project-relative, e.g. "voice/voice_01.mp3"
    duration: float = Field(ge=0)
    transcript: str = ""
    scenes: list[SceneVoiceAssignment] = Field(default_factory=list)


class VoiceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["2.0"] = "2.0"
    voice_files: list[VoiceFile] = Field(default_factory=list)
    silent_scenes: list[str] = Field(default_factory=list)

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
