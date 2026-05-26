import json
from pathlib import Path

from core.project import Project
from ui.main_window import voice_source_ui_state


def _write_minimal_project(root: Path) -> Path:
    scenes = root / "Story.json"
    scenes.write_text(
        json.dumps(
            {
                "meta": {
                    "project_id": "story",
                    "title": "Story",
                    "language": "en",
                    "aspect_ratio": "16:9",
                },
                "scenes": [
                    {
                        "id": "SCENE-01",
                        "script": "Hello world",
                        "visual_type": "Image",
                        "duration": 5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return scenes


def test_project_defaults_active_voice_source_to_raw(tmp_path: Path):
    project = Project.load(_write_minimal_project(tmp_path))

    active = project.get_active_voice_source()

    assert active["source"] == "raw"
    assert active["master_voice"] == "voice/raw/master_voice.wav"
    assert active["whisper_words"] == "voice/raw/whisper_words.json"
    assert project.active_master_voice_path == tmp_path / "voice" / "raw" / "master_voice.wav"
    assert project.active_whisper_words_path == tmp_path / "voice" / "raw" / "whisper_words.json"


def test_project_persists_enhance_as_active_after_successful_whisper(tmp_path: Path):
    project = Project.load(_write_minimal_project(tmp_path))

    project.set_active_whisper_source("enhance")
    reloaded = Project.load(tmp_path / "Story.json")

    active = reloaded.get_active_voice_source()
    assert active["source"] == "enhance"
    assert active["master_voice"] == "voice/enhance/master_voice.wav"
    assert active["whisper_words"] == "voice/enhance/whisper_words.json"
    assert reloaded.active_master_voice_path == tmp_path / "voice" / "enhance" / "master_voice.wav"


def test_project_uses_legacy_master_voice_when_raw_file_has_not_been_migrated(tmp_path: Path):
    legacy = tmp_path / "voice" / "master_voice.wav"
    legacy.parent.mkdir()
    legacy.write_bytes(b"legacy")
    project = Project.load(_write_minimal_project(tmp_path))

    assert project.active_master_voice_path == legacy


def test_voice_source_ui_disables_enhance_source_until_enhanced_master_exists(tmp_path: Path):
    project = Project.load(_write_minimal_project(tmp_path))
    project.paths.whisper_words_raw_json.parent.mkdir(parents=True)
    project.paths.whisper_words_raw_json.write_text('{"words":[]}', encoding="utf-8")

    state = voice_source_ui_state(project)

    assert state["can_enhance_voice"] is True
    assert state["can_whisper_raw"] is False
    assert state["can_whisper_enhance"] is False


def test_voice_source_ui_enables_enhance_source_after_enhanced_master_exists(tmp_path: Path):
    project = Project.load(_write_minimal_project(tmp_path))
    project.paths.whisper_words_raw_json.parent.mkdir(parents=True)
    project.paths.whisper_words_raw_json.write_text('{"words":[]}', encoding="utf-8")
    project.paths.master_voice_enhanced_wav.parent.mkdir(parents=True)
    project.paths.master_voice_enhanced_wav.write_bytes(b"enhanced")

    state = voice_source_ui_state(project)

    assert state["can_whisper_enhance"] is True
