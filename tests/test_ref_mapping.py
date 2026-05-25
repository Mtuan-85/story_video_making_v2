from pathlib import Path

from core.ref_mapping import (
    CharacterRef,
    RefMapping,
    RefMappingValidation,
    build_default_ref_mapping,
    resolve_refs_for_scene,
    validate_ref_mapping,
)
from core.schema import Scene


def test_default_ref_mapping_creates_style_and_character_rows():
    mapping = build_default_ref_mapping(["Naomi", "Jinro"])

    assert mapping.use_refs_for_image is True
    assert mapping.include_style_ref_with_character is True
    assert mapping.style_ref.enabled is True
    assert mapping.style_ref.path == ""
    assert sorted(mapping.characters) == ["Jinro", "Naomi"]
    assert mapping.characters["Naomi"].enabled is True
    assert mapping.characters["Naomi"].path == ""


def test_validate_ref_mapping_requires_enabled_paths_only(tmp_path: Path):
    naomi = tmp_path / "refs" / "naomi.png"
    naomi.parent.mkdir()
    naomi.write_bytes(b"x")
    mapping = RefMapping(
        style_ref=CharacterRef(enabled=True, path=""),
        characters={
            "Naomi": CharacterRef(enabled=True, path="refs/naomi.png"),
            "Jinro": CharacterRef(enabled=False, path=""),
        },
    )

    report = validate_ref_mapping(mapping, tmp_path, ["Naomi", "Jinro"])

    assert report == RefMappingValidation(ok=False, missing=["Style ref"])


def test_resolve_refs_for_character_scene_adds_character_then_style(tmp_path: Path):
    style = tmp_path / "refs" / "style.png"
    naomi = tmp_path / "refs" / "naomi.png"
    style.parent.mkdir()
    style.write_bytes(b"x")
    naomi.write_bytes(b"x")
    mapping = RefMapping(
        style_ref=CharacterRef(enabled=True, path="refs/style.png"),
        include_style_ref_with_character=True,
        characters={"Naomi": CharacterRef(enabled=True, path="refs/naomi.png")},
    )
    scene = Scene(
        id="SCENE-01",
        visual_type="Image",
        duration=5,
        characters_in_scene=["Naomi"],
    )

    refs = resolve_refs_for_scene(mapping, tmp_path, scene)

    assert refs == [naomi, style]


def test_resolve_refs_for_character_scene_can_skip_style(tmp_path: Path):
    style = tmp_path / "refs" / "style.png"
    naomi = tmp_path / "refs" / "naomi.png"
    style.parent.mkdir()
    style.write_bytes(b"x")
    naomi.write_bytes(b"x")
    mapping = RefMapping(
        style_ref=CharacterRef(enabled=True, path="refs/style.png"),
        include_style_ref_with_character=False,
        characters={"Naomi": CharacterRef(enabled=True, path="refs/naomi.png")},
    )
    scene = Scene(
        id="SCENE-01",
        visual_type="Image",
        duration=5,
        characters_in_scene=["Naomi"],
    )

    refs = resolve_refs_for_scene(mapping, tmp_path, scene)

    assert refs == [naomi]


def test_resolve_refs_for_scene_without_characters_uses_style(tmp_path: Path):
    style = tmp_path / "refs" / "style.png"
    style.parent.mkdir()
    style.write_bytes(b"x")
    mapping = RefMapping(style_ref=CharacterRef(enabled=True, path="refs/style.png"))
    scene = Scene(id="SCENE-01", visual_type="Image", duration=5)

    refs = resolve_refs_for_scene(mapping, tmp_path, scene)

    assert refs == [style]


def test_resolve_refs_returns_empty_when_refs_disabled(tmp_path: Path):
    style = tmp_path / "refs" / "style.png"
    style.parent.mkdir()
    style.write_bytes(b"x")
    mapping = RefMapping(
        use_refs_for_image=False,
        style_ref=CharacterRef(enabled=True, path="refs/style.png"),
    )
    scene = Scene(id="SCENE-01", visual_type="Image", duration=5)

    refs = resolve_refs_for_scene(mapping, tmp_path, scene)

    assert refs == []
