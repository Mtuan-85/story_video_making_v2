from pathlib import Path

from core.ref_mapping import CharacterRef, RefMapping, save_ref_mapping
from core.schema import Meta, Scene, ScenesJson
from engines.grok.image_worker_flow import _load_task_ref_mapping, _project_path, _refs_for_scene
from workers.task_contract import GenerateTask


def test_project_path_resolves_relative_paths_against_project_root():
    root = Path("D:/project/root")

    assert _project_path(root, "project.json") == root / "project.json"
    assert _project_path(root, "refs/ref1.png") == root / "refs/ref1.png"


def test_project_path_preserves_absolute_paths():
    root = Path("D:/project/root")
    absolute = Path("C:/assets/ref1.png")

    assert _project_path(root, str(absolute)) == absolute


def test_refs_for_scene_resolves_mapping_by_scene_characters(tmp_path):
    refs_dir = tmp_path / "refs"
    refs_dir.mkdir()
    style = refs_dir / "style.png"
    naomi = refs_dir / "naomi.png"
    style.write_bytes(b"x")
    naomi.write_bytes(b"x")
    mapping_path = tmp_path / "story_ref_mapping.json"
    save_ref_mapping(
        mapping_path,
        RefMapping(
            style_ref=CharacterRef(enabled=True, path="refs/style.png"),
            include_style_ref_with_character=True,
            characters={"Naomi": CharacterRef(enabled=True, path="refs/naomi.png")},
        ),
    )
    task = GenerateTask(
        task_id="t1",
        project_file=str(tmp_path / "story.json"),
        project_root=str(tmp_path),
        task_type="batch_image",
        scene_ids=["SCENE-01"],
        options={"ref_mapping_path": str(mapping_path)},
    )
    scenes_json = ScenesJson(
        meta=Meta(
            project_id="p1",
            title="Story",
            aspect_ratio="16:9",
            language="en",
            baseStyle="Style",
            baseNegative="Negative",
        ),
        character={"Naomi": "Main character"},
        scenes=[
            Scene(
                id="SCENE-01",
                visual_type="Image",
                duration=5,
                characters_in_scene=["Naomi"],
            ),
            Scene(id="SCENE-02", visual_type="Image", duration=5),
        ],
    )

    mapping = _load_task_ref_mapping(task, scenes_json)

    assert _refs_for_scene(mapping, tmp_path, scenes_json.scenes[0]) == [naomi, style]
    assert _refs_for_scene(mapping, tmp_path, scenes_json.scenes[1]) == [style]
