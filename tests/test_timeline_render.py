from pathlib import Path

from render.timeline_visual import (
    TimelineVisualSegment,
    build_timeline_visual_segments,
    build_visual_segment_command,
)


def test_build_timeline_visual_segments_inserts_natural_gap_and_beat_pause():
    timeline = {
        "timeline": [
            {
                "type": "scene",
                "scene_id": "SCENE-01",
                "render_in": 0.0,
                "render_out": 2.0,
            },
            {
                "type": "scene",
                "scene_id": "SCENE-02",
                "render_in": 2.5,
                "render_out": 5.0,
            },
            {
                "type": "beat_pause",
                "after_scene_id": "SCENE-02",
                "render_in": 5.0,
                "render_out": 6.0,
            },
        ]
    }

    segments = build_timeline_visual_segments(timeline)

    assert segments == [
        TimelineVisualSegment("scene", "SCENE-01", 2.0),
        TimelineVisualSegment("freeze_gap", "SCENE-01", 0.5),
        TimelineVisualSegment("scene", "SCENE-02", 2.5),
        TimelineVisualSegment("beat_pause", "SCENE-02", 1.0),
    ]


def test_build_visual_segment_command_outputs_video_only_for_image(tmp_path: Path):
    visual = tmp_path / "pic1.jpg"
    output = tmp_path / "seg.mp4"

    cmd = build_visual_segment_command(
        visual_path=visual,
        visual_type="Image",
        effect="zoom_in",
        duration=3.0,
        output_path=output,
        width=1920,
        height=1080,
    )
    cmd_text = " ".join(cmd)

    assert "-loop 1" in cmd_text
    assert "-an" in cmd
    assert "-t 3.000" in cmd_text
    assert str(output) == cmd[-1]


def test_build_visual_segment_command_freezes_video_tail(tmp_path: Path):
    visual = tmp_path / "scene.mp4"
    output = tmp_path / "pause.mp4"

    cmd = build_visual_segment_command(
        visual_path=visual,
        visual_type="Video",
        effect="no_effect",
        duration=1.25,
        output_path=output,
        width=1920,
        height=1080,
        freeze_only=True,
    )
    cmd_text = " ".join(cmd)

    assert "-sseof -0.1" in cmd_text
    assert "-loop 1" in cmd_text
    assert "-an" in cmd
    assert "-t 1.250" in cmd_text
