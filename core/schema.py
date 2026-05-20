"""Pydantic models for scenes.json (author-facing schema).

Schema version 1.0. See SPEC.md section 4 for field reference.
Runtime state is kept separately in state.json (see core/project.py).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

VisualType = Literal[
    "Image",
    "Video",
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

    version: str | None = None
    project_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    aspect_ratio: AspectRatio
    language: Language
    baseStyle: str = ""
    baseNegative: str = ""
    image_quality: ImageQuality = "quality"
    video_resolution: VideoResolution = "720p"
    video_duration: VideoDuration = "10s"
    source_citations: str | None = None
    topic: str | None = None
    voice_model_id: str | None = None
    voice_speed: float | None = Field(default=None, ge=0.5, le=2.0)
    voice_volume: int | None = Field(default=None, ge=-20, le=20)


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
    scene_type: str | None = None
    visual_technique: str | None = None
    characters_in_scene: list[str] = Field(default_factory=list)
    core_idea_illustration: str | None = None

    @staticmethod
    def normalize_visual_type(value: str) -> str:
        key = str(value).strip().lower()
        if key in {"image", "image_grok"}:
            return "Image"
        if key in {"video", "video_grok"}:
            return "Video"
        if key == "slideshow":
            return "slideshow"
        return str(value)

    @model_validator(mode="before")
    @classmethod
    def _normalize_ai_scene_keys(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "scene_id" in data and "id" not in data:
            data["id"] = data.pop("scene_id")
        else:
            data.pop("scene_id", None)
        if "script" in data and not data.get("story_en") and not data.get("story_vi"):
            data["story_en"] = data.pop("script")
        else:
            data.pop("script", None)
        if "duration_sec" in data and "duration" not in data:
            data["duration"] = data.pop("duration_sec")
        else:
            data.pop("duration_sec", None)
        if "visual_type" in data:
            data["visual_type"] = cls.normalize_visual_type(data["visual_type"])
        return data

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

    meta: Meta
    scenes: list[Scene] = Field(min_length=1)
    character: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _migrate_root_version_and_settings(cls, data):
        if not isinstance(data, dict):
            return data
        data = dict(data)
        meta = dict(data.get("meta") or {})
        root_version = data.pop("version", None)
        if root_version is not None and not meta.get("version"):
            meta["version"] = str(root_version)
        settings = data.get("settings")
        if isinstance(settings, dict):
            for key in (
                "baseStyle",
                "baseNegative",
                "image_quality",
                "video_resolution",
                "video_duration",
                "voice_model_id",
                "voice_speed",
                "voice_volume",
                "topic",
            ):
                value = settings.get(key)
                if key in settings and key not in meta and value not in (None, ""):
                    meta[key] = value
        for key in ("source_citations", "topic", "voice_model_id"):
            if meta.get(key) in (None, ""):
                meta.pop(key, None)
        if meta.get("voice_speed") == 1.0:
            meta.pop("voice_speed", None)
        if meta.get("voice_volume") == 0:
            meta.pop("voice_volume", None)
        data["meta"] = meta
        data.pop("settings", None)
        return data

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

    def topic_for_prompt(self) -> str:
        return self.meta.topic or self.meta.title

    @property
    def settings(self) -> Settings:
        return Settings(
            baseStyle=self.meta.baseStyle,
            baseNegative=self.meta.baseNegative,
            topic=self.topic_for_prompt(),
            voice_model_id=self.meta.voice_model_id,
            voice_speed=self.meta.voice_speed if self.meta.voice_speed is not None else 1.0,
            voice_volume=self.meta.voice_volume if self.meta.voice_volume is not None else 0,
            image_quality=self.meta.image_quality,
            video_resolution=self.meta.video_resolution,
            video_duration=self.meta.video_duration,
        )
