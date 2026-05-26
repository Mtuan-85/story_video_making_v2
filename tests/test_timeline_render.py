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


def test_render_timeline_visuals_reports_segment_progress(monkeypatch, tmp_path: Path):
    from render import timeline_visual

    timeline = {
        "timeline": [
            {
                "type": "scene",
                "scene_id": "SCENE-01",
                "render_in": 0.0,
                "render_out": 1.0,
            },
            {
                "type": "scene",
                "scene_id": "SCENE-02",
                "render_in": 1.0,
                "render_out": 2.0,
            },
        ]
    }
    scenes = {
        "SCENE-01": {"visual_type": "Image", "effect": "zoom_in"},
        "SCENE-02": {"visual_type": "Image", "effect": "zoom_out"},
    }
    visuals = {
        "SCENE-01": tmp_path / "s1.jpg",
        "SCENE-02": tmp_path / "s2.jpg",
    }
    events = []

    def fake_render_visual_segment(**kwargs):
        kwargs["output_path"].write_bytes(b"segment")
        return kwargs["output_path"]

    def fake_assemble(paths, output_path):
        output_path.write_bytes(b"final")
        return output_path

    monkeypatch.setattr(timeline_visual, "render_visual_segment", fake_render_visual_segment)
    monkeypatch.setattr(timeline_visual, "assemble_concat", fake_assemble)

    timeline_visual.render_timeline_visuals(
        timeline,
        scenes,
        visuals,
        tmp_path / "final_video_only.mp4",
        tmp_path / "segments",
        1920,
        1080,
        progress_cb=lambda done, total, segment: events.append((done, total, segment.scene_id)),
    )

    assert events == [(1, 2, "SCENE-01"), (2, 2, "SCENE-02")]


def test_render_timeline_visuals_merges_static_freeze_into_scene_to_continue_motion(
    monkeypatch,
    tmp_path: Path,
):
    from render import timeline_visual

    timeline = {
        "timeline": [
            {
                "type": "scene",
                "scene_id": "SCENE-01",
                "render_in": 0.0,
                "render_out": 2.0,
            },
            {
                "type": "beat_pause",
                "after_scene_id": "SCENE-01",
                "render_in": 2.0,
                "render_out": 3.0,
            },
        ]
    }
    scenes = {"SCENE-01": {"visual_type": "Image", "effect": "zoom_in"}}
    visuals = {"SCENE-01": tmp_path / "s1.jpg"}
    calls = []

    def fake_render_visual_segment(**kwargs):
        calls.append(kwargs)
        kwargs["output_path"].write_bytes(b"segment")
        return kwargs["output_path"]

    def fake_assemble(paths, output_path):
        output_path.write_bytes(b"final")
        return output_path

    monkeypatch.setattr(timeline_visual, "render_visual_segment", fake_render_visual_segment)
    monkeypatch.setattr(timeline_visual, "assemble_concat", fake_assemble)

    timeline_visual.render_timeline_visuals(
        timeline,
        scenes,
        visuals,
        tmp_path / "final_video_only.mp4",
        tmp_path / "segments",
        1920,
        1080,
    )

    assert len(calls) == 1
    assert calls[0]["duration"] == 3.0
    assert calls[0]["effect"] == "zoom_in"
    assert calls[0]["freeze_only"] is False


def test_render_timeline_visuals_keeps_video_freeze_as_separate_tail_segment(
    monkeypatch,
    tmp_path: Path,
):
    from render import timeline_visual

    timeline = {
        "timeline": [
            {
                "type": "scene",
                "scene_id": "SCENE-03",
                "render_in": 0.0,
                "render_out": 2.0,
            },
            {
                "type": "beat_pause",
                "after_scene_id": "SCENE-03",
                "render_in": 2.0,
                "render_out": 3.0,
            },
        ]
    }
    scenes = {"SCENE-03": {"visual_type": "Video", "effect": "no_effect"}}
    visuals = {"SCENE-03": tmp_path / "s3.mp4"}
    calls = []

    def fake_render_visual_segment(**kwargs):
        calls.append(kwargs)
        kwargs["output_path"].write_bytes(b"segment")
        return kwargs["output_path"]

    def fake_assemble(paths, output_path):
        output_path.write_bytes(b"final")
        return output_path

    monkeypatch.setattr(timeline_visual, "render_visual_segment", fake_render_visual_segment)
    monkeypatch.setattr(timeline_visual, "assemble_concat", fake_assemble)

    timeline_visual.render_timeline_visuals(
        timeline,
        scenes,
        visuals,
        tmp_path / "final_video_only.mp4",
        tmp_path / "segments",
        1920,
        1080,
    )

    assert [call["duration"] for call in calls] == [2.0, 1.0]
    assert [call["freeze_only"] for call in calls] == [False, True]


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
    assert "-loop 1" not in cmd_text
    assert "tpad=stop_mode=clone" in cmd_text
    assert "-an" in cmd
    assert "-t 1.250" in cmd_text


def test_build_visual_segment_command_extends_short_video_with_tail_freeze(tmp_path: Path):
    visual = tmp_path / "scene.mp4"
    output = tmp_path / "seg.mp4"

    cmd = build_visual_segment_command(
        visual_path=visual,
        visual_type="Video",
        effect="no_effect",
        duration=10.64,
        output_path=output,
        width=1920,
        height=1080,
        source_duration=8.0,
    )
    cmd_text = " ".join(cmd)

    assert "tpad=stop_mode=clone:stop_duration=2.640" in cmd_text
    assert "-t 10.640" in cmd_text


def test_build_visual_segment_command_freezes_short_video_gap_without_tolerance_skip(tmp_path: Path):
    visual = tmp_path / "scene.mp4"
    output = tmp_path / "gap.mp4"

    cmd = build_visual_segment_command(
        visual_path=visual,
        visual_type="Video",
        effect="no_effect",
        duration=0.162,
        output_path=output,
        width=1920,
        height=1080,
        freeze_only=True,
    )
    cmd_text = " ".join(cmd)

    assert "tpad=stop_mode=clone" in cmd_text
    assert "-t 0.162" in cmd_text
