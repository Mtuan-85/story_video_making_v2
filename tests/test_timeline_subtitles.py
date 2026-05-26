import json
from pathlib import Path

from voice.beat_timeline import BeatTiming
from voice.timeline_builder import process_beat
from voice.timeline_to_mapping import timeline_to_voice_mapping


def _beat() -> BeatTiming:
    return BeatTiming(
        beat_id="BEAT-01",
        beat_index=1,
        voice_file=Path("voice/beat_01.mp3"),
        script="Xin chao ban",
        pause_after_sec=0.0,
        scene_ids=["SCENE-01"],
        beat_role=None,
        emotion=None,
        measured_duration=1.2,
        voice_in=0.0,
        voice_out=1.2,
        pause_in=1.2,
        pause_out=1.2,
    )


def test_process_beat_populates_karaoke_subtitle_phrases_for_voiced_scene():
    scene = {
        "id": "SCENE-01",
        "script": "Xin chao ban",
        "visual_type": "image",
        "duration": 3,
    }
    beat_words = [
        {"word": "Xin", "start": 0.0, "end": 0.25},
        {"word": "chao", "start": 0.3, "end": 0.55},
        {"word": "ban", "start": 0.65, "end": 0.95},
    ]

    items, warnings = process_beat(_beat(), [scene], beat_words)

    assert warnings == []
    assert items[0]["subtitle_phrases"] == [
        {
            "text": "Xin chao ban",
            "start": 0.0,
            "end": 0.95,
            "words": [
                {"word": "Xin", "start": 0.0, "end": 0.25},
                {"word": "chao", "start": 0.3, "end": 0.55},
                {"word": "ban", "start": 0.65, "end": 0.95},
            ],
        }
    ]


def test_timeline_to_voice_mapping_preserves_subtitle_phrases():
    phrase = {
        "text": "Xin chao ban",
        "start": 0.0,
        "end": 0.95,
        "words": [
            {"word": "Xin", "start": 0.0, "end": 0.25},
            {"word": "chao", "start": 0.3, "end": 0.55},
            {"word": "ban", "start": 0.65, "end": 0.95},
        ],
    }
    timeline_path = Path("tests/.tmp_voice_matching_timeline.json")
    try:
        timeline_path.write_text(
            json.dumps(
                {
                    "audio_master": "master_voice.wav",
                    "total_duration": 1.2,
                    "beats": [],
                    "timeline": [
                        {
                            "type": "scene",
                            "scene_id": "SCENE-01",
                            "scene_type": "voiced",
                            "voice_in": 0.0,
                            "voice_out": 1.2,
                            "design_duration": 3,
                            "match_method": "single_scene_beat",
                            "match_score": 1.0,
                            "subtitle_phrases": [phrase],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        mapping = timeline_to_voice_mapping(timeline_path)

        assert mapping.to_render_dict()["scenes"][0]["subtitle_phrases"] == [phrase]
    finally:
        timeline_path.unlink(missing_ok=True)
