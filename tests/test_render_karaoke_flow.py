import json
import time
from pathlib import Path
from types import SimpleNamespace

from core.voice_mapping import VoiceMapping
from workers.render_worker import (
    build_visual_cache_signature,
    count_subtitle_phrases,
    load_latest_voice_mapping,
    resolve_render_master_audio,
    save_visual_cache_metadata,
    sync_mapping_pauses_from_timeline,
    synthesize_missing_subtitle_phrases,
    visual_cache_is_reusable,
)
from workers.two_level_match_worker import (
    save_voice_mapping_from_timeline,
    save_whisper_words_for_source,
)


def _timeline_with_phrase(path: Path) -> Path:
    path.write_text(
        json.dumps(
            {
                "audio_master": "voice/master_voice.wav",
                "total_duration": 1.0,
                "beats": [],
                "timeline": [
                    {
                        "type": "scene",
                        "scene_id": "SCENE-01",
                        "scene_type": "voiced",
                        "voice_in": 0.0,
                        "voice_out": 1.0,
                        "design_duration": 1.0,
                        "match_method": "single_scene_beat",
                        "match_score": 1.0,
                        "subtitle_phrases": [
                            {
                                "text": "Xin chao",
                                "start": 0.0,
                                "end": 1.0,
                                "words": [
                                    {"word": "Xin", "start": 0.0, "end": 0.4},
                                    {"word": "chao", "start": 0.4, "end": 1.0},
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_process_voice_saves_voice_mapping_with_karaoke_phrases(tmp_path: Path):
    timeline_path = _timeline_with_phrase(tmp_path / "voice_matching_timeline.json")
    saved = {}
    project = SimpleNamespace(
        save_voice_mapping=lambda mapping: saved.setdefault("mapping", mapping)
    )

    mapping = save_voice_mapping_from_timeline(project, timeline_path)

    assert saved["mapping"] is mapping
    assert count_subtitle_phrases(mapping) == 1
    assert mapping.to_render_dict()["scenes"][0]["subtitle_phrases"][0]["words"][0]["word"] == "Xin"


def test_render_loads_latest_voice_mapping_from_disk_over_stale_mapping(tmp_path: Path):
    stale = VoiceMapping.model_validate(
        {
            "version": "4.0",
            "scenes": [
                {
                    "id": "SCENE-01",
                    "duration_original": 1,
                    "duration_adjusted": 1,
                    "subtitle_phrases": [],
                }
            ],
        }
    )
    disk_mapping = VoiceMapping.model_validate(
        {
            "version": "4.0",
            "scenes": [
                {
                    "id": "SCENE-01",
                    "voice_in": 0.0,
                    "voice_out": 1.0,
                    "duration_original": 1,
                    "duration_adjusted": 1,
                    "subtitle_phrases": [
                        {
                            "text": "Xin",
                            "start": 0.0,
                            "end": 0.5,
                            "words": [{"word": "Xin", "start": 0.0, "end": 0.5}],
                        }
                    ],
                }
            ],
        }
    )
    mapping_path = tmp_path / "voice_mapping.json"
    mapping_path.write_text(disk_mapping.model_dump_json(), encoding="utf-8")
    project = SimpleNamespace(paths=SimpleNamespace(voice_mapping_json=mapping_path))

    loaded = load_latest_voice_mapping(project, stale)

    assert count_subtitle_phrases(loaded) == 1


def test_render_resolves_active_master_voice_from_project_state(tmp_path: Path):
    raw = tmp_path / "voice" / "raw" / "master_voice.wav"
    enhanced = tmp_path / "voice" / "enhance" / "master_voice.wav"
    enhanced.parent.mkdir(parents=True)
    enhanced.write_bytes(b"enhanced")
    project = SimpleNamespace(
        paths=SimpleNamespace(master_voice_wav=raw),
        active_master_voice_path=enhanced,
    )

    assert resolve_render_master_audio(project) == enhanced


def test_render_falls_back_to_legacy_master_voice_property(tmp_path: Path):
    legacy = tmp_path / "voice" / "master_voice.wav"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"legacy")
    project = SimpleNamespace(paths=SimpleNamespace(master_voice_wav=legacy))

    assert resolve_render_master_audio(project) == legacy


def test_process_voice_persists_raw_whisper_words_and_marks_raw_active(tmp_path: Path):
    master = tmp_path / "voice" / "raw" / "master_voice.wav"
    words_path = tmp_path / "voice" / "raw" / "whisper_words.json"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"audio")
    calls = []
    project = SimpleNamespace(
        paths=SimpleNamespace(
            root=tmp_path,
            master_voice_raw_wav=master,
            whisper_words_raw_json=words_path,
        ),
        set_active_whisper_source=lambda source: calls.append(source),
    )
    words = [{"word": "Hello", "start": 0.0, "end": 0.3}]

    save_whisper_words_for_source(project, "raw", master, words)

    data = json.loads(words_path.read_text(encoding="utf-8"))
    assert data["source"] == "voice/raw/master_voice.wav"
    assert data["words"] == words
    assert calls == ["raw"]


def test_whisper_helper_persists_enhance_words_and_marks_enhance_active(tmp_path: Path):
    master = tmp_path / "voice" / "enhance" / "master_voice.wav"
    words_path = tmp_path / "voice" / "enhance" / "whisper_words.json"
    master.parent.mkdir(parents=True)
    master.write_bytes(b"audio")
    calls = []
    project = SimpleNamespace(
        paths=SimpleNamespace(
            root=tmp_path,
            master_voice_raw_wav=tmp_path / "voice" / "raw" / "master_voice.wav",
            whisper_words_raw_json=tmp_path / "voice" / "raw" / "whisper_words.json",
            master_voice_enhanced_wav=master,
            whisper_words_enhanced_json=words_path,
        ),
        set_active_whisper_source=lambda source: calls.append(source),
    )
    words = [{"word": "Better", "start": 0.0, "end": 0.4}]

    save_whisper_words_for_source(project, "enhance", master, words)

    data = json.loads(words_path.read_text(encoding="utf-8"))
    assert data["source"] == "voice/enhance/master_voice.wav"
    assert data["words"] == words
    assert calls == ["enhance"]


def test_visual_cache_reusable_until_timeline_or_sources_change(tmp_path: Path):
    cache = tmp_path / "final_video_only.mp4"
    timeline = tmp_path / "voice_matching_timeline.json"
    scenes_json = tmp_path / "scenes_edited.json"
    source = tmp_path / "scene.mp4"
    for path in (timeline, scenes_json, source, cache):
        path.write_bytes(b"x")
        time.sleep(0.01)
    cache.write_bytes(b"cached")

    assert visual_cache_is_reusable(cache, timeline, scenes_json, {"SCENE-01": source})

    time.sleep(0.01)
    timeline.write_bytes(b"changed")

    assert not visual_cache_is_reusable(cache, timeline, scenes_json, {"SCENE-01": source})


def test_visual_cache_uses_manifest_not_scenes_json_mtime(tmp_path: Path):
    cache = tmp_path / "final_video_only.mp4"
    timeline = tmp_path / "voice_matching_timeline.json"
    scenes_json = tmp_path / "scenes_edited.json"
    source = tmp_path / "scene.mp4"
    for path in (timeline, scenes_json, source, cache):
        path.write_bytes(b"x")
    scenes_by_id = {"SCENE-01": {"visual_type": "Image", "effect": "zoom_in"}}
    visual_paths = {"SCENE-01": source}
    signature = build_visual_cache_signature(timeline, scenes_by_id, visual_paths)
    save_visual_cache_metadata(cache.with_suffix(".json"), signature)

    time.sleep(0.01)
    scenes_json.write_bytes(b"touched but visual fields unchanged")

    assert visual_cache_is_reusable(cache, timeline, scenes_json, visual_paths, scenes_by_id)


def test_render_can_synthesize_karaoke_phrases_when_old_mapping_has_none():
    mapping = VoiceMapping.model_validate(
        {
            "version": "4.0",
            "scenes": [
                {
                    "id": "SCENE-01",
                    "voice_in": 10.0,
                    "voice_out": 12.0,
                    "duration_original": 2,
                    "duration_adjusted": 2,
                    "subtitle_phrases": [],
                }
            ],
        }
    )
    scenes_by_id = {
        "SCENE-01": {
            "id": "SCENE-01",
            "script": "Xin chao ban",
        }
    }

    filled = synthesize_missing_subtitle_phrases(mapping, scenes_by_id)

    assert filled == 1
    rendered = mapping.to_render_dict()["scenes"][0]["subtitle_phrases"]
    assert rendered[0]["text"] == "Xin chao ban"
    assert rendered[0]["words"] == [
        {"word": "Xin", "start": 10.0, "end": 10.667},
        {"word": "chao", "start": 10.667, "end": 11.333},
        {"word": "ban", "start": 11.333, "end": 12.0},
    ]


def test_render_syncs_subtitle_scene_gaps_from_timeline_before_ass_generation():
    mapping = VoiceMapping.model_validate(
        {
            "version": "4.0",
            "scenes": [
                {
                    "id": "SCENE-01",
                    "voice_in": 0.0,
                    "voice_out": 6.26,
                    "duration_original": 6,
                    "duration_adjusted": 6.26,
                    "render_duration": 6.26,
                    "freeze_pause_after": 0.0,
                },
                {
                    "id": "SCENE-02",
                    "voice_in": 6.78,
                    "voice_out": 14.24,
                    "duration_original": 8,
                    "duration_adjusted": 7.46,
                    "render_duration": 7.46,
                    "freeze_pause_after": 0.0,
                },
            ],
        }
    )
    timeline = {
        "timeline": [
            {
                "type": "scene",
                "scene_id": "SCENE-01",
                "render_in": 0.0,
                "render_out": 6.26,
            },
            {
                "type": "scene",
                "scene_id": "SCENE-02",
                "render_in": 6.78,
                "render_out": 14.24,
            },
        ]
    }

    sync_mapping_pauses_from_timeline(mapping, timeline)

    assert mapping.scenes[0].freeze_pause_after == 0.52
    assert mapping.scenes[1].freeze_pause_after == 0.0
