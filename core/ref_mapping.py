"""Project-level reference image mapping for scene-level image generation."""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from core.schema import Scene

MAX_REFS_PER_SCENE = 5


class CharacterRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    path: str = ""


class RefMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    use_refs_for_image: bool = True
    include_style_ref_with_character: bool = True
    style_ref: CharacterRef = Field(default_factory=CharacterRef)
    characters: dict[str, CharacterRef] = Field(default_factory=dict)


class RefMappingValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    missing: list[str] = Field(default_factory=list)


def build_default_ref_mapping(character_names: list[str]) -> RefMapping:
    return RefMapping(
        style_ref=CharacterRef(enabled=True, path=""),
        characters={name: CharacterRef(enabled=True, path="") for name in sorted(character_names)},
    )


def reconcile_ref_mapping(mapping: RefMapping, character_names: list[str]) -> RefMapping:
    data = mapping.model_dump()
    chars = dict(data.get("characters") or {})
    for name in sorted(character_names):
        chars.setdefault(name, CharacterRef(enabled=True, path="").model_dump())
    for stale in set(chars) - set(character_names):
        chars.pop(stale, None)
    data["characters"] = chars
    return RefMapping.model_validate(data)


def load_or_create_ref_mapping(path: Path, character_names: list[str]) -> RefMapping:
    path = Path(path)
    if path.exists():
        mapping = RefMapping.model_validate_json(path.read_text(encoding="utf-8"))
        mapping = reconcile_ref_mapping(mapping, character_names)
    else:
        mapping = build_default_ref_mapping(character_names)
    save_ref_mapping(path, mapping)
    return mapping


def save_ref_mapping(path: Path, mapping: RefMapping) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(mapping.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _resolve_project_path(project_root: Path, raw_path: str) -> Path | None:
    if not raw_path:
        return None
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path(project_root) / path
    return path if path.exists() else None


def validate_ref_mapping(
    mapping: RefMapping,
    project_root: Path,
    character_names: list[str],
) -> RefMappingValidation:
    if not mapping.use_refs_for_image:
        return RefMappingValidation(ok=True, missing=[])

    missing: list[str] = []
    if mapping.style_ref.enabled and _resolve_project_path(project_root, mapping.style_ref.path) is None:
        missing.append("Style ref")

    reconciled = reconcile_ref_mapping(mapping, character_names)
    for name in sorted(character_names):
        ref = reconciled.characters.get(name)
        if ref is not None and ref.enabled and _resolve_project_path(project_root, ref.path) is None:
            missing.append(name)

    return RefMappingValidation(ok=not missing, missing=missing)


def resolve_refs_for_scene(mapping: RefMapping, project_root: Path, scene: Scene) -> list[Path]:
    if not mapping.use_refs_for_image:
        return []

    refs: list[Path] = []
    scene_characters = list(scene.characters_in_scene or [])
    if scene_characters:
        for name in scene_characters:
            ref = mapping.characters.get(name)
            if ref is None or not ref.enabled:
                continue
            resolved = _resolve_project_path(project_root, ref.path)
            if resolved is not None:
                refs.append(resolved)
        if mapping.include_style_ref_with_character and mapping.style_ref.enabled:
            style = _resolve_project_path(project_root, mapping.style_ref.path)
            if style is not None:
                refs.append(style)
    elif mapping.style_ref.enabled:
        style = _resolve_project_path(project_root, mapping.style_ref.path)
        if style is not None:
            refs.append(style)

    deduped: list[Path] = []
    seen: set[str] = set()
    for ref in refs:
        key = str(ref.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ref)
    return deduped[:MAX_REFS_PER_SCENE]
