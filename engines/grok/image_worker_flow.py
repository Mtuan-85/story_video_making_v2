from __future__ import annotations

import json
import time
from pathlib import Path

from core.ref_mapping import RefMapping, resolve_refs_for_scene
from core.project import Project
from core.paths import ProjectPaths
from core.schema import Scene, ScenesJson
from engines.grok.cdp_worker import connect_worker_cdp
from engines.grok.engine import GrokImageEngine
from engines.grok.image_ref_engine import GrokImageRefEngine
from workers.batch_image import _build_image_settings
from workers.task_contract import GenerateTask, event_line


def _print_event(event_type: str, **payload: object) -> None:
    print(event_line(event_type, **payload), flush=True)


def _project_relative(project: Project, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project.paths.root.resolve())).replace("\\", "/")
    except ValueError:
        return str(path.resolve())


def _project_path(project_root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return project_root / path


def _load_project_readonly(scenes_file: Path) -> Project:
    paths = ProjectPaths(scenes_file)
    source = paths.scenes_edited if paths.scenes_edited.exists() else paths.scenes_original
    with source.open(encoding="utf-8") as f:
        scenes_json = ScenesJson.model_validate(json.load(f))
    return Project(paths=paths, scenes_json=scenes_json, state={})


def _load_task_ref_mapping(task: GenerateTask, scenes_json: ScenesJson) -> RefMapping | None:
    raw_path = task.options.ref_mapping_path
    if not raw_path:
        return None
    mapping_path = _project_path(Path(task.project_root), raw_path)
    if not mapping_path.exists():
        return None
    mapping = RefMapping.model_validate_json(mapping_path.read_text(encoding="utf-8"))
    if not mapping.use_refs_for_image:
        return None
    return mapping


def _refs_for_scene(mapping: RefMapping | None, project_root: Path, scene: Scene) -> list[Path]:
    if mapping is None:
        return []
    return resolve_refs_for_scene(mapping, project_root, scene)


async def run_grok_image_task(task: GenerateTask) -> tuple[int, int]:
    project_root = Path(task.project_root)
    project = _load_project_readonly(_project_path(project_root, task.project_file))
    session = await connect_worker_cdp(task.cdp.url, task.cdp.base_url)
    try:
        image_engine = GrokImageEngine(session.page)
        ref_mapping = _load_task_ref_mapping(task, project.scenes_json)
        legacy_ref_paths = [_project_path(project_root, p) for p in task.options.image_refs]
        legacy_use_refs = bool(task.options.use_refs_for_image and legacy_ref_paths)
        ref_engine = GrokImageRefEngine(session.page) if (ref_mapping or legacy_use_refs) else None

        success = 0
        total = len(task.scene_ids)

        for scene_id in task.scene_ids:
            _print_event("scene_started", scene_id=scene_id, asset="image")
            started_at = time.monotonic()

            try:
                scene = project.scene(scene_id)
                scene_idx = project.scene_index(scene_id)
                output_path = project.paths.image_path(scene_idx)
                settings = _build_image_settings(project, scene, output_path)
                settings["pick_mode"] = task.options.pick_mode
                settings["fast_mode"] = task.options.fast_mode
                prompt = settings.pop("prompt")

                ref_paths = _refs_for_scene(ref_mapping, project_root, scene)
                if not ref_paths and legacy_use_refs:
                    ref_paths = legacy_ref_paths

                if ref_engine is not None and ref_paths:
                    result = await ref_engine.gen_image_with_refs(
                        scene_id=scene_id,
                        prompt=prompt,
                        ref_paths=ref_paths,
                        output_path=Path(output_path),
                        aspect=project.scenes_json.meta.aspect_ratio,
                        fast_mode=task.options.fast_mode,
                    )
                    if not result.get("ok"):
                        raise RuntimeError(str(result.get("reason", "unknown")))
                    result_path = Path(result["path"])
                else:
                    result_path = await image_engine.gen_image(
                        prompt=prompt,
                        settings=dict(settings),
                        ref_image=None,
                    )

                rel_path = _project_relative(project, Path(result_path))
                success += 1
                _print_event(
                    "scene_done",
                    scene_id=scene_id,
                    asset="image",
                    path=rel_path,
                    duration_sec=round(time.monotonic() - started_at, 3),
                )
            except Exception as exc:
                reason = str(exc)
                _print_event(
                    "scene_failed",
                    scene_id=scene_id,
                    asset="image",
                    reason=reason,
                )

        return success, total
    finally:
        await session.close()
