from pathlib import Path

from core.schema import Scene, ScenesJson
from voice.deterministic_aligner import align_deterministic
from voice.voice_aligner import add_freeze_pauses
from voice import voice_scanner


def test_schema_keeps_script_as_canonical_scene_text():
    parsed = ScenesJson.model_validate(
        {
            "meta": {
                "project_id": "p1",
                "title": "T",
                "aspect_ratio": "16:9",
                "language": "vi",
            },
            "scenes": [
                {
                    "id": "s1",
                    "visual_type": "Image",
                    "script": "Xin chao",
                    "duration": 3,
                }
            ],
        }
    )

    assert parsed.scenes[0].script == "Xin chao"
    dumped = parsed.model_dump(exclude_none=True)
    assert dumped["scenes"][0]["script"] == "Xin chao"
    assert "story_en" not in dumped["scenes"][0]
    assert "story_vi" not in dumped["scenes"][0]


def test_legacy_story_populates_script_without_being_alignment_source():
    scene = Scene(
        id="s1",
        visual_type="Image",
        story_en="Legacy story",
        duration=3,
    )

    assert scene.script == "Legacy story"


def test_deterministic_alignment_uses_script_only():
    scenes = [
        {
            "id": "SCENE-01",
            "script": "xin chao ban",
            "story_en": "wrong words",
            "story_vi": "also wrong",
            "duration": 3,
        }
    ]
    whisper_words = [
        {"word": "xin", "start": 0.0, "end": 0.2},
        {"word": "chao", "start": 0.3, "end": 0.5},
        {"word": "ban", "start": 0.6, "end": 0.8},
    ]

    result = align_deterministic(scenes, whisper_words, language="vi")

    assert result[0]["is_silent"] is False
    assert result[0]["matched_text"] == "xin chao ban"


def test_empty_script_scene_is_silent_and_does_not_consume_voice_words():
    scenes = [
        {
            "id": "SCENE-01",
            "script": "",
            "duration": 4,
        },
        {
            "id": "SCENE-02",
            "script": "xin chao ban",
            "duration": 3,
        },
    ]
    whisper_words = [
        {"word": "xin", "start": 10.0, "end": 10.2},
        {"word": "chao", "start": 10.3, "end": 10.5},
        {"word": "ban", "start": 10.6, "end": 10.8},
    ]

    result = align_deterministic(scenes, whisper_words, language="vi")

    assert result[0]["is_silent"] is True
    assert result[0]["word_indices"] is None
    assert result[1]["is_silent"] is False
    assert result[1]["voice_in"] == 10.0


def test_freeze_pause_subtracts_empty_script_anchor_duration():
    voice_scenes = [
        {
            "id": "SCENE-01",
            "voice_in": 0.0,
            "voice_out": 5.0,
            "duration_original": 5,
            "is_silent": False,
        },
        {
            "id": "SCENE-02",
            "voice_in": None,
            "voice_out": None,
            "duration_original": 4,
            "is_silent": True,
        },
        {
            "id": "SCENE-03",
            "voice_in": 11.0,
            "voice_out": 14.0,
            "duration_original": 3,
            "is_silent": False,
        },
    ]

    result = add_freeze_pauses(voice_scenes)

    assert result[0]["freeze_pause_after"] == 2.0
    assert result[1]["freeze_pause_after"] == 0.0
    assert result[2]["freeze_pause_after"] == 0.0


def test_voice_scanner_accepts_same_extensions_as_ui(tmp_path, monkeypatch):
    voice_file = tmp_path / "voice_01.flac"
    voice_file.write_bytes(b"fake")

    monkeypatch.setattr(voice_scanner, "get_audio_duration", lambda _: 1.25)

    result = voice_scanner.scan_voice_folder(tmp_path)

    assert [item.name for item in result] == ["voice_01.flac"]
    assert result[0].duration == 1.25


def test_main_window_exposes_process_voice_button():
    source = Path("ui/main_window.py").read_text(encoding="utf-8")

    assert "btn_process_voice" in source
    assert "clicked.connect(self._on_process_voice)" in source
