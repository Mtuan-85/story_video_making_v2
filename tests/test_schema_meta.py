from core.schema import ScenesJson


def test_loads_meta_schema_without_settings():
    data = {
        "meta": {
            "version": "1.1",
            "project_id": "Naomi_01",
            "title": "Raising Children Who Cooperate Willingly",
            "aspect_ratio": "16:9",
            "language": "en",
            "baseStyle": "Cozy flat cartoon",
            "baseNegative": "photorealistic",
            "image_quality": "quality",
            "video_resolution": "720p",
            "video_duration": "10s",
            "source_citations": "source doc",
        },
        "character": {"Naomi": "A calm Japanese woman."},
        "scenes": [{
            "id": "1",
            "visual_type": "Image",
            "effect": "zoom_in",
            "story_en": "Story",
            "imagePrompt": "Prompt",
            "duration": 8,
        }],
    }
    parsed = ScenesJson.model_validate(data)
    assert parsed.meta.version == "1.1"
    assert parsed.meta.baseStyle == "Cozy flat cartoon"
    assert parsed.character["Naomi"].startswith("A calm")
    assert parsed.topic_for_prompt() == parsed.meta.title


def test_root_version_moves_to_meta_version():
    data = {
        "version": "1.1",
        "meta": {
            "project_id": "Naomi_01",
            "title": "Title",
            "aspect_ratio": "16:9",
            "language": "en",
            "baseStyle": "Style",
            "baseNegative": "Negative",
        },
        "scenes": [{
            "id": "1",
            "visual_type": "Image",
            "story_en": "Story",
            "duration": 8,
        }],
    }
    parsed = ScenesJson.model_validate(data)
    dumped = parsed.model_dump(exclude_none=True)
    assert parsed.meta.version == "1.1"
    assert "version" not in dumped


def test_meta_schema_exposes_legacy_settings_property_without_dumping_settings():
    data = {
        "meta": {
            "version": "1.1",
            "project_id": "Naomi_01",
            "title": "Title",
            "aspect_ratio": "16:9",
            "language": "en",
            "baseStyle": "Style",
            "baseNegative": "Negative",
            "topic": "Prompt Topic",
            "image_quality": "speed",
            "video_resolution": "480p",
            "video_duration": "6s",
            "voice_model_id": "voice-1",
            "voice_speed": 1.2,
            "voice_volume": 3,
        },
        "scenes": [{
            "id": "1",
            "visual_type": "Image",
            "story_en": "Story",
            "duration": 8,
        }],
    }
    parsed = ScenesJson.model_validate(data)
    dumped = parsed.model_dump(exclude_none=True)
    assert parsed.settings.baseStyle == "Style"
    assert parsed.settings.baseNegative == "Negative"
    assert parsed.settings.topic == "Prompt Topic"
    assert parsed.settings.image_quality == "speed"
    assert parsed.settings.video_resolution == "480p"
    assert parsed.settings.video_duration == "6s"
    assert parsed.settings.voice_model_id == "voice-1"
    assert parsed.settings.voice_speed == 1.2
    assert parsed.settings.voice_volume == 3
    assert "settings" not in dumped


def test_legacy_root_settings_migrates_to_meta_without_dumping_settings():
    data = {
        "meta": {
            "project_id": "Naomi_01",
            "title": "Title",
            "aspect_ratio": "16:9",
            "language": "en",
        },
        "settings": {
            "baseStyle": "Legacy Style",
            "baseNegative": "Legacy Negative",
            "topic": "",
            "image_quality": "speed",
            "video_resolution": "480p",
            "video_duration": "6s",
        },
        "scenes": [{
            "id": "1",
            "visual_type": "Image",
            "story_en": "Story",
            "duration": 8,
        }],
    }
    parsed = ScenesJson.model_validate(data)
    dumped = parsed.model_dump(exclude_none=True)
    assert parsed.meta.baseStyle == "Legacy Style"
    assert parsed.meta.baseNegative == "Legacy Negative"
    assert parsed.meta.topic is None
    assert parsed.meta.image_quality == "speed"
    assert parsed.meta.video_resolution == "480p"
    assert parsed.meta.video_duration == "6s"
    assert parsed.meta.voice_speed is None
    assert parsed.meta.voice_volume is None
    assert parsed.settings.baseStyle == "Legacy Style"
    assert parsed.settings.baseNegative == "Legacy Negative"
    assert parsed.settings.topic == "Title"
    assert parsed.settings.image_quality == "speed"
    assert parsed.settings.video_resolution == "480p"
    assert parsed.settings.video_duration == "6s"
    assert "settings" not in dumped


def test_project_s4_style_ai_json_normalizes_to_app_schema():
    data = {
        "version": "1.2",
        "meta": {
            "project_id": "Naomi_01",
            "title": "Raising a Child Who Chooses to Cooperate",
            "aspect_ratio": "16:9",
            "language": "en",
            "baseStyle": "Cozy flat cartoon",
            "baseNegative": "photorealistic",
            "image_quality": "quality",
            "video_resolution": "720p",
            "video_duration": "10s",
        },
        "character": {"Naomi": "A 38-year-old Japanese woman."},
        "scenes": [
            {
                "scene_id": "scene-01",
                "script": "Last Tuesday evening, Jinro left his shoes in the hallway.",
                "duration_sec": 10,
                "scene_type": "Narrative Anchor",
                "visual_technique": "Single Vignette",
                "characters_in_scene": ["Jinro", "Sakura"],
                "core_idea_illustration": "Shoes in the hallway become the emotional trigger.",
                "imagePrompt": "A warm family hallway floor.",
                "visual_type": "video_grok",
                "videoPrompt": "The hallway shadows breathe softly.",
                "effect": "no_effect",
            }
        ],
    }

    parsed = ScenesJson.model_validate(data)
    dumped = parsed.model_dump(exclude_none=True)
    scene = parsed.scenes[0]

    assert parsed.meta.version == "1.2"
    assert "version" not in dumped
    assert "settings" not in dumped
    assert scene.id == "scene-01"
    assert scene.story_en.startswith("Last Tuesday")
    assert scene.duration == 10
    assert scene.scene_type == "Narrative Anchor"
    assert scene.visual_technique == "Single Vignette"
    assert scene.characters_in_scene == ["Jinro", "Sakura"]
    assert scene.core_idea_illustration.startswith("Shoes")
    assert scene.visual_type == "Video"
    assert dumped["scenes"][0]["visual_type"] == "Video"
    assert "scene_id" not in dumped["scenes"][0]
    assert "script" not in dumped["scenes"][0]
    assert "duration_sec" not in dumped["scenes"][0]


def test_visual_type_aliases_normalize_to_basic_app_values():
    def parse_visual_type(value: str) -> str:
        parsed = ScenesJson.model_validate({
            "meta": {
                "project_id": "Naomi_01",
                "title": "Title",
                "aspect_ratio": "16:9",
                "language": "en",
                "baseStyle": "Style",
                "baseNegative": "Negative",
            },
            "scenes": [{
                "id": f"scene-{value}",
                "visual_type": value,
                "story_en": "Story",
                "duration": 8,
            }],
        })
        return parsed.model_dump()["scenes"][0]["visual_type"]

    assert parse_visual_type("image_grok") == "Image"
    assert parse_visual_type("image") == "Image"
    assert parse_visual_type("Image") == "Image"
    assert parse_visual_type("video_grok") == "Video"
    assert parse_visual_type("video") == "Video"
    assert parse_visual_type("Video") == "Video"
    assert parse_visual_type("slideshow") == "slideshow"
