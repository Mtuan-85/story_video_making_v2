"""Single-scene Ken Burns render worker.

Two modes:
    self  — zoom-pan applied to the scene's own image. Needs a ready image.
    cont  — extract last frame of the previous scene's video, then zoom-pan.
            Needs the previous scene's video to be ready.

Output: `project.paths.video_path(scene_idx)`. State is updated with
`source_type="ken_burns_self"` or `"ken_burns_cont"`.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Literal

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from render.ken_burns import (
    Direction,
    ken_burns_continuation,
    ken_burns_self,
)
from runtime.estimator import Estimator
from workers._async_thread import AsyncQThread

KBMode = Literal["self", "cont"]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve_path_field(project: Project, scene_id: str, key: str) -> Path | None:
    """Return absolute Path for state.scenes[id][key].path, or None if missing."""
    block = project.get_scene_state(scene_id).get(key, {})
    rel = block.get("path")
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = project.paths.root / p
    return p if p.exists() else None


def previous_scene_id(project: Project, scene_id: str) -> str | None:
    """ID of the scene immediately before this one in scenes.json order."""
    prev: str | None = None
    for s in project.scenes:
        if s.id == scene_id:
            return prev
        prev = s.id
    return None


def is_ken_burns_eligible(
    project: Project, scene_id: str, mode: KBMode
) -> tuple[bool, str]:
    if mode == "self":
        img = project.get_scene_state(scene_id).get("image", {})
        if img.get("status") != "ready" or not img.get("path"):
            return False, "chưa có ảnh ready để Ken Burns self"
        return True, ""
    if mode == "cont":
        prev_id = previous_scene_id(project, scene_id)
        if prev_id is None:
            return False, "scene đầu tiên — không thể dùng ken_burns_cont"
        prev_video = project.get_scene_state(prev_id).get("video", {})
        if prev_video.get("status") != "ready" or not prev_video.get("path"):
            return False, f"scene trước ({prev_id}) chưa có video ready"
        return True, ""
    return False, f"mode không hợp lệ: {mode}"


class KenBurnsWorker(AsyncQThread):
    """Render one scene with the Ken Burns zoom-pan effect.

    Signals:
        scene_started(scene_id)
        scene_finished(scene_id, state_dict)
        scene_failed(scene_id, reason)
    """

    scene_started = pyqtSignal(str)
    scene_finished = pyqtSignal(str, dict)
    scene_failed = pyqtSignal(str, str)

    def __init__(
        self,
        project: Project,
        scene_id: str,
        mode: KBMode,
        direction: Direction = "in",
        estimator: Estimator | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.scene_id = scene_id
        self.mode: KBMode = mode
        self.direction: Direction = direction
        self.estimator = estimator

    async def _async_run(self) -> None:
        ok, reason = is_ken_burns_eligible(self.project, self.scene_id, self.mode)
        if not ok:
            self._mark_failed(reason)
            return

        scene = self.project.scene(self.scene_id)
        scene_idx = self.project.scene_index(self.scene_id)
        output_path = self.project.paths.video_path(scene_idx)
        aspect = self.project.scenes_json.meta.aspect_ratio

        self.project.update_scene_state(
            self.scene_id, "video",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(self.scene_id)
        self.emit_log(
            f"{self.scene_id}: đang render Ken Burns "
            f"({self.mode}, {self.direction}, {scene.duration}s, {aspect})..."
        )

        t0 = time.monotonic()
        try:
            if self.mode == "self":
                image_path = _resolve_path_field(self.project, self.scene_id, "image")
                if image_path is None:
                    self._mark_failed("ảnh nguồn không tồn tại trên disk")
                    return
                result_path = await self.run_with_stop(
                    ken_burns_self(
                        image_path=image_path,
                        output_path=output_path,
                        duration_sec=float(scene.duration),
                        aspect_ratio=aspect,
                        direction=self.direction,
                    )
                )
            else:  # cont
                prev_id = previous_scene_id(self.project, self.scene_id)
                assert prev_id is not None  # eligibility already checked
                prev_video = _resolve_path_field(self.project, prev_id, "video")
                if prev_video is None:
                    self._mark_failed(
                        f"video của scene trước ({prev_id}) không tồn tại trên disk"
                    )
                    return
                result_path = await self.run_with_stop(
                    ken_burns_continuation(
                        prev_video_path=prev_video,
                        output_path=output_path,
                        duration_sec=float(scene.duration),
                        aspect_ratio=aspect,
                        work_dir=self.project.paths.temp_dir,
                        direction=self.direction,
                    )
                )
        except Exception as e:
            self._mark_failed(str(e))
            return
        elapsed = time.monotonic() - t0

        if result_path is None:
            self._mark_failed("stopped")
            return

        source_type = "ken_burns_self" if self.mode == "self" else "ken_burns_cont"
        rel_path = self._project_relative(Path(result_path))
        new_state = {
            "status": "ready",
            "path": rel_path,
            "source_type": source_type,
            "last_gen_at": _now_iso(),
            "fail_reason": None,
        }
        self.project.update_scene_state(self.scene_id, "video", new_state)
        self.project.clear_warnings(self.scene_id, code="ken_burns_render_failed")
        if self.estimator is not None:
            self.estimator.record_actual("ken_burns_render", elapsed)
        self.scene_finished.emit(self.scene_id, new_state)
        self.emit_log(f"{self.scene_id}: ✓ ken_burns {rel_path} ({elapsed:.1f}s)")

    def _mark_failed(self, reason: str) -> None:
        self.project.update_scene_state(
            self.scene_id, "video",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(self.scene_id, "ken_burns_render_failed", reason)
        self.scene_failed.emit(self.scene_id, reason)
        self.emit_log(f"{self.scene_id}: ❌ ken_burns {reason}")

    def _project_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
