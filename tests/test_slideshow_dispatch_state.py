import json

from core.project import Project
from workers.batch_video import is_eligible


def _project(tmp_path):
    scene_path = tmp_path / "story.json"
    scene_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "meta": {
                    "project_id": "p",
                    "title": "T",
                    "aspect_ratio": "16:9",
                    "language": "en",
                },
                "settings": {"baseStyle": "", "baseNegative": "", "topic": ""},
                "scenes": [
                    {
                        "id": "SCENE-01",
                        "visual_type": "slideshow",
                        "script": "hello",
                        "imagePrompt": "prompt",
                        "duration": 5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return Project.load(scene_path)


def test_batch_video_no_longer_routes_slideshow(tmp_path):
    project = _project(tmp_path)
    project.update_scene_state(
        "SCENE-01",
        "image",
        {"status": "ready", "path": "sources/pic1.jpg"},
    )

    ok, reason = is_eligible(project, project.scene("SCENE-01"))

    assert ok is False
    assert "Batch Edit" in reason


def test_visual_type_change_resets_video_and_edit_state(tmp_path):
    project = _project(tmp_path)
    project.update_scene_state(
        "SCENE-01",
        "video",
        {"status": "ready", "path": "sources/vid1.mp4", "source_type": "slideshow"},
    )
    project.update_scene_state(
        "SCENE-01",
        "edit",
        {"status": "ready", "zones_json": "sources/edit/SCENE-01-zones.json"},
    )

    project.update_scene_field("SCENE-01", "visual_type", "Video")

    state = project.get_scene_state("SCENE-01")
    assert state["video"]["status"] == "pending"
    assert state["video"]["path"] is None
    assert state["video"]["source_type"] is None
    assert state["edit"]["status"] == "pending"
    assert state["edit"]["zones_json"] is None
