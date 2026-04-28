"""Batch image gen worker — iterates all scenes, calls GrokImageEngine.

Reads/writes Project state per scene. Emits per-scene start/done/fail signals
so SceneRow widgets can swap status icons in the main thread.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.schema import Scene
from engines.grok.engine import GrokImageEngine
from runtime.estimator import Estimator
from workers._async_thread import AsyncQThread


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _build_image_settings(project: Project, scene: Scene, output_path: Path) -> dict[str, Any]:
    s = project.scenes_json.settings
    meta = project.scenes_json.meta
    full_prompt = f"{scene.imagePrompt}\n\nStyle: {s.baseStyle}\n\nNegative: {s.baseNegative}"
    return {
        "prompt": full_prompt,
        "aspect": meta.aspect_ratio,
        "quality": s.image_quality,
        "output_path": output_path,
        "topic": s.topic,
        "style": s.baseStyle,
        "debug_dir": project.paths.temp_dir / "candidates",
    }


class BatchImageWorker(AsyncQThread):
    """Generate images for every scene whose image is not already 'ready'.

    Signals:
        scene_started(scene_id)
        scene_finished(scene_id, state_dict)
        scene_failed(scene_id, reason)
        batch_progress(done, total)
        batch_done(success_count, total)
    """

    scene_started = pyqtSignal(str)
    scene_finished = pyqtSignal(str, dict)
    scene_failed = pyqtSignal(str, str)
    batch_progress = pyqtSignal(int, int)
    batch_done = pyqtSignal(int, int)

    def __init__(
        self,
        project: Project,
        engine: GrokImageEngine,
        force: bool = False,
        pick_mode: str = "auto",
        estimator: Estimator | None = None,
        scene_ids: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.engine = engine
        self.force = force
        self.pick_mode = pick_mode
        self.estimator = estimator
        self.scene_ids = scene_ids

    async def _async_run(self) -> None:
        if self.scene_ids is None:
            scenes = list(self.project.scenes)
        else:
            allowed = set(self.scene_ids)
            scenes = [s for s in self.project.scenes if s.id in allowed]
        total = len(scenes)
        success = 0

        for idx, scene in enumerate(scenes, start=1):
            if self.stop_event.is_set():
                self.emit_log(f"Đã dừng batch image tại scene {scene.id}")
                break

            state = self.project.get_scene_state(scene.id)
            if not self.force and state["image"]["status"] == "ready":
                self.emit_log(f"[{idx}/{total}] {scene.id}: bỏ qua (đã có ảnh)")
                self.batch_progress.emit(idx, total)
                continue

            ok = await self._gen_one(scene, total, idx)
            if ok:
                success += 1
            self.batch_progress.emit(idx, total)

        self.emit_log(f"Batch image xong: {success}/{total} scene OK")
        self.batch_done.emit(success, total)

    async def _gen_one(self, scene: Scene, total: int, idx: int) -> bool:
        scene_idx_in_project = self.project.scene_index(scene.id)
        output_path = self.project.paths.image_path(scene_idx_in_project)

        self.project.update_scene_state(
            scene.id, "image",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(scene.id)
        self.emit_log(f"[{idx}/{total}] {scene.id}: đang gen ảnh...")

        settings = _build_image_settings(self.project, scene, output_path)
        settings["pick_mode"] = self.pick_mode

        gen_coro = self.engine.gen_image(
            prompt=settings.pop("prompt"),
            settings=settings,
            ref_image=None,
        )
        t0 = time.monotonic()
        try:
            result_path = await self.run_with_stop(gen_coro)
        except Exception as e:
            return self._mark_failed(scene, str(e))
        elapsed = time.monotonic() - t0

        if result_path is None:
            return self._mark_failed(scene, "stopped")

        rel_path = self._project_relative(Path(result_path))
        new_state = {
            "status": "ready",
            "path": rel_path,
            "last_gen_at": _now_iso(),
            "fail_reason": None,
        }
        self.project.update_scene_state(scene.id, "image", new_state)
        self.project.clear_warnings(scene.id, code="grok_no_image")
        if self.estimator is not None:
            self.estimator.record_actual("gen_image", elapsed)
        self.scene_finished.emit(scene.id, new_state)
        self.emit_log(f"[{idx}/{total}] {scene.id}: ✓ {rel_path} ({elapsed:.1f}s)")
        return True

    def _mark_failed(self, scene: Scene, reason: str) -> bool:
        self.project.update_scene_state(
            scene.id, "image",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(scene.id, "grok_no_image", reason)
        self.scene_failed.emit(scene.id, reason)
        self.emit_log(f"{scene.id}: ❌ {reason}")
        return False

    def _project_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
