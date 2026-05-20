import json

from core.project import Project


def test_project_load_persists_legacy_visual_type_aliases_to_edited_json(tmp_path):
    project_file = tmp_path / "project.json"
    project_file.write_text(
        json.dumps({
            "meta": {
                "project_id": "p",
                "title": "T",
                "aspect_ratio": "16:9",
                "language": "en",
            },
            "scenes": [
                {
                    "id": "1",
                    "visual_type": "image_grok",
                    "effect": "zoom_in",
                    "story_en": "Story",
                    "duration": 8,
                },
                {
                    "id": "2",
                    "visual_type": "video_grok",
                    "effect": "no_effect",
                    "story_en": "Story",
                    "duration": 8,
                },
            ],
        }),
        encoding="utf-8",
    )

    project = Project.load(project_file)

    edited = json.loads(project.paths.scenes_edited.read_text(encoding="utf-8"))
    assert [scene.visual_type for scene in project.scenes] == ["Image", "Video"]
    assert [scene["visual_type"] for scene in edited["scenes"]] == ["Image", "Video"]
