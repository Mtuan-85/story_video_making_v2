"""Batch video gen worker — image-to-video for scenes with visual_type=video_grok.

Pre-conditions:
  - Scene must have visual_type == "video_grok"
  - Scene must have videoPrompt (not None)
  - Scene must have a ready image (image-to-video uses it as reference)

Scenes that don't qualify are skipped with a Vietnamese log line.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.schema import Scene
from engines.grok.engine import GrokVideoEngine
from runtime.estimator import Estimator
from workers._async_thread import AsyncQThread


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _build_video_settings(project: Project, output_path: Path) -> dict[str, Any]:
    s = project.scenes_json.settings
    meta = project.scenes_json.meta
    return {
        "aspect": meta.aspect_ratio,
        "resolution": s.video_resolution,
        "duration": s.video_duration,
        "output_path": output_path,
    }


def is_eligible(project: Project, scene: Scene) -> tuple[bool, str]:
    """Check whether this scene qualifies for Grok video gen.

    Returns (ok, reason). reason is empty on ok=True; otherwise a Vietnamese
    message explaining why we skip.
    """
    if scene.visual_type != "video_grok":
        return False, f"visual_type={scene.visual_type}, không phải video_grok"
    if not scene.videoPrompt:
        return False, "thiếu videoPrompt"
    img = project.get_scene_state(scene.id).get("image", {})
    if img.get("status") != "ready" or not img.get("path"):
        return False, "chưa có ảnh ready để làm I2V"
    return True, ""


def _resolve_image_path(project: Project, scene: Scene) -> Path | None:
    img = project.get_scene_state(scene.id).get("image", {})
    rel = img.get("path")
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = project.paths.root / p
    return p if p.exists() else None


class BatchVideoWorker(AsyncQThread):
    """Generate videos for every eligible scene (image-to-video).

    Signals:
        scene_started(scene_id)
        scene_finished(scene_id, state_dict)
        scene_failed(scene_id, reason)
        scene_skipped(scene_id, reason)
        batch_progress(done, total)
        batch_done(success_count, eligible_total)
    """

    scene_started = pyqtSignal(str)
    scene_finished = pyqtSignal(str, dict)
    scene_failed = pyqtSignal(str, str)
    scene_skipped = pyqtSignal(str, str)
    batch_progress = pyqtSignal(int, int)
    batch_done = pyqtSignal(int, int)

    def __init__(
        self,
        project: Project,
        engine: GrokVideoEngine,
        force: bool = False,
        estimator: Estimator | None = None,
        scene_ids: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.engine = engine
        self.force = force
        self.estimator = estimator
        self.scene_ids = scene_ids

    async def _async_run(self) -> None:
        if self.scene_ids is None:
            scenes_iter = list(self.project.scenes)
        else:
            allowed = set(self.scene_ids)
            scenes_iter = [s for s in self.project.scenes if s.id in allowed]

        eligible: list[Scene] = []
        for scene in scenes_iter:
            ok, reason = is_eligible(self.project, scene)
            if ok:
                eligible.append(scene)
            else:
                self.scene_skipped.emit(scene.id, reason)
                self.emit_log(f"{scene.id}: bỏ qua ({reason})")

        total = len(eligible)
        if total == 0:
            self.emit_log("Không có scene nào đủ điều kiện gen video")
            self.batch_done.emit(0, 0)
            return

        success = 0
        for idx, scene in enumerate(eligible, start=1):
            if self.stop_event.is_set():
                self.emit_log(f"Đã dừng batch video tại {scene.id}")
                break

            state = self.project.get_scene_state(scene.id)
            if not self.force and state["video"]["status"] == "ready":
                self.emit_log(f"[{idx}/{total}] {scene.id}: bỏ qua (đã có video)")
                self.batch_progress.emit(idx, total)
                continue

            ok = await self._gen_one(scene, total, idx)
            if ok:
                success += 1
            self.batch_progress.emit(idx, total)

        self.emit_log(f"Batch video xong: {success}/{total} scene OK")
        self.batch_done.emit(success, total)

    async def _gen_one(self, scene: Scene, total: int, idx: int) -> bool:
        scene_idx = self.project.scene_index(scene.id)
        output_path = self.project.paths.video_path(scene_idx)
        ref_image = _resolve_image_path(self.project, scene)
        if ref_image is None:
            return self._mark_failed(scene, "ref image không tồn tại trên disk")

        self.project.update_scene_state(
            scene.id, "video",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(scene.id)
        self.emit_log(f"[{idx}/{total}] {scene.id}: đang gen video (I2V)...")

        settings = _build_video_settings(self.project, output_path)
        gen_coro = self.engine.gen_video(
            prompt=scene.videoPrompt,
            ref_image=ref_image,
            settings=settings,
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
            "source_type": "grok",
            "last_gen_at": _now_iso(),
            "fail_reason": None,
        }
        self.project.update_scene_state(scene.id, "video", new_state)
        self.project.clear_warnings(scene.id, code="grok_no_video")
        if self.estimator is not None:
            self.estimator.record_actual("gen_video", elapsed)
        self.scene_finished.emit(scene.id, new_state)
        self.emit_log(f"[{idx}/{total}] {scene.id}: ✓ {rel_path} ({elapsed:.1f}s)")
        return True

    def _mark_failed(self, scene: Scene, reason: str) -> bool:
        self.project.update_scene_state(
            scene.id, "video",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(scene.id, "grok_no_video", reason)
        self.scene_failed.emit(scene.id, reason)
        self.emit_log(f"{scene.id}: ❌ video {reason}")
        return False

    def _project_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
