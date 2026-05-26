import json
from pathlib import Path

from core.paths import ProjectPaths
from core.project_cleanup import clean_temp_outputs
from exporters.asset_registry import build_registry
from voice.s5_loader import load_and_validate_s5


def test_project_paths_define_structured_voice_and_cache_dirs(tmp_path: Path):
    paths = ProjectPaths(tmp_path / "Story.json")

    assert paths.voice_source_dir == tmp_path / "voice" / "source"
    assert paths.voice_source_s6_dir == tmp_path / "voice" / "source" / "s6"
    assert paths.voice_raw_dir == tmp_path / "voice" / "raw"
    assert paths.voice_enhance_dir == tmp_path / "voice" / "enhance"
    assert paths.master_voice_wav == tmp_path / "voice" / "raw" / "master_voice.wav"
    assert paths.master_voice_raw_wav == tmp_path / "voice" / "raw" / "master_voice.wav"
    assert paths.master_voice_enhanced_wav == tmp_path / "voice" / "enhance" / "master_voice.wav"
    assert paths.whisper_words_raw_json == tmp_path / "voice" / "raw" / "whisper_words.json"
    assert paths.whisper_words_enhanced_json == tmp_path / "voice" / "enhance" / "whisper_words.json"
    assert paths.voice_pacing_operations_json == tmp_path / "voice" / "enhance" / "voice_pacing_operations.json"
    assert paths.voice_enhance_report_json == tmp_path / "voice" / "enhance" / "voice_enhance_report.json"
    assert paths.cache_dir == tmp_path / "cache"
    assert paths.kdenlive_cache_dir == tmp_path / "cache" / "kdenlive"


def test_s5_loader_prefers_structured_s6_voice_dir(tmp_path: Path):
    s5_path = tmp_path / "Story_S5.json"
    scenes_path = tmp_path / "Story_edited.json"
    voice_dir = tmp_path / "voice"
    structured = voice_dir / "source" / "s6"
    structured.mkdir(parents=True)
    (structured / "beat-01.mp3").write_bytes(b"voice")
    s5_path.write_text(
        json.dumps(
            [
                {
                    "beat_id": "beat-01",
                    "script": "hello",
                    "pause_after_sec": 0,
                    "scenes": ["SCENE-01"],
                }
            ]
        ),
        encoding="utf-8",
    )
    scenes_path.write_text(json.dumps({"scenes": [{"id": "SCENE-01"}]}), encoding="utf-8")

    result = load_and_validate_s5(s5_path, scenes_path, voice_dir)

    assert result.ok
    assert result.beats[0].voice_file == (structured / "beat-01.mp3").resolve()


def test_s5_loader_falls_back_to_legacy_root_s6_voice_dir(tmp_path: Path):
    s5_path = tmp_path / "Story_S5.json"
    scenes_path = tmp_path / "Story_edited.json"
    voice_dir = tmp_path / "voice"
    legacy = tmp_path / "Story_S6_voice"
    legacy.mkdir(parents=True)
    (legacy / "beat-01.mp3").write_bytes(b"voice")
    s5_path.write_text(
        json.dumps(
            [
                {
                    "beat_id": "beat-01",
                    "script": "hello",
                    "pause_after_sec": 0,
                    "scenes": ["SCENE-01"],
                }
            ]
        ),
        encoding="utf-8",
    )
    scenes_path.write_text(json.dumps({"scenes": [{"id": "SCENE-01"}]}), encoding="utf-8")

    result = load_and_validate_s5(s5_path, scenes_path, voice_dir)

    assert result.ok
    assert result.beats[0].voice_file == (legacy / "beat-01.mp3").resolve()


def test_kdenlive_generated_assets_go_to_cache_kdenlive(tmp_path: Path):
    master = tmp_path / "master_voice.wav"
    master.write_bytes(b"audio")
    timeline = [
        {
            "type": "scene",
            "scene_id": "SCENE-01",
            "visual_type": "Image",
            "visual_source": "sources/missing.jpg",
        }
    ]

    registry = build_registry(
        timeline_items=timeline,
        master_audio_path=master,
        project_root=tmp_path,
        output_dir=tmp_path,
    )

    assert registry.generated_dir == tmp_path / "cache" / "kdenlive"
    assert registry.placeholders
    assert Path(registry.placeholders[0]).is_relative_to(tmp_path / "cache" / "kdenlive")


def test_clean_temp_outputs_keeps_visual_cache_by_default(tmp_path: Path):
    temp = tmp_path / "temp"
    (temp / "timeline_segments").mkdir(parents=True)
    (temp / "timeline_segments" / "seg.mp4").write_bytes(b"seg")
    (temp / "scene-01-karaoke-test").mkdir()
    (temp / "scene-01-karaoke-test" / "debug.ass").write_text("debug", encoding="utf-8")
    (temp / "final_video_only.mp4").write_bytes(b"video")
    (temp / "final_video_only.json").write_text("{}", encoding="utf-8")

    removed = clean_temp_outputs(tmp_path)

    assert removed
    assert (temp / "final_video_only.mp4").exists()
    assert (temp / "final_video_only.json").exists()
    assert not (temp / "timeline_segments").exists()
    assert not (temp / "scene-01-karaoke-test").exists()
