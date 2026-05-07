"""Pydantic models for scenes.json (author-facing schema).

Schema version 1.0. See SPEC.md section 4 for field reference.
Runtime state is kept separately in state.json (see core/project.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VisualType = Literal[
    "image_grok",
    "video_grok",
    "slideshow",
]

EffectType = Literal[
    "zoom_in",
    "zoom_out",
    "no_effect",
]

AspectRatio = Literal["16:9", "9:16"]
Language = Literal["vi", "en"]
ImageQuality = Literal["speed", "quality"]
VideoResolution = Literal["480p", "720p"]
VideoDuration = Literal["6s", "10s"]


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    aspect_ratio: AspectRatio
    language: Language


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseStyle: str
    baseNegative: str
    topic: str
    voice_model_id: str | None = None
    voice_speed: float = Field(default=1.0, ge=0.5, le=2.0)
    voice_volume: int = Field(default=0, ge=-20, le=20)
    image_quality: ImageQuality = "quality"
    video_resolution: VideoResolution = "720p"
    video_duration: VideoDuration = "10s"


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    visual_type: VisualType
    effect: EffectType = "no_effect"
    story_vi: str | None = None
    story_en: str | None = None
    imagePrompt: str | None = None
    videoPrompt: str | None = None
    duration: int = Field(ge=1, le=60)
    emotion: str | None = None

    @model_validator(mode="after")
    def _at_least_one_story(self) -> "Scene":
        if not self.story_vi and not self.story_en:
            raise ValueError(f"Scene {self.id}: phải có ít nhất story_vi hoặc story_en")
        return self

    def get_story(self, lang: Language) -> str:
        """Return story text for the given language. Falls back to the other language if missing."""
        if lang == "vi":
            return self.story_vi or self.story_en or ""
        return self.story_en or self.story_vi or ""


class ScenesJson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["1.0"]
    meta: Meta
    settings: Settings
    scenes: list[Scene] = Field(min_length=1)

    @field_validator("scenes")
    @classmethod
    def _unique_ids(cls, scenes: list[Scene]) -> list[Scene]:
        seen: set[str] = set()
        for scene in scenes:
            if scene.id in seen:
                raise ValueError(f"Trùng scene id: {scene.id}")
            seen.add(scene.id)
        return scenes

    def scene_by_id(self, scene_id: str) -> Scene | None:
        for scene in self.scenes:
            if scene.id == scene_id:
                return scene
        return None

