"""Single-scene slideshow_v4 render worker.

Wraps `render/slideshow.py` so the heavy synchronous pipeline (rembg → Claude
animation director → ffmpeg filter_complex) runs off the UI thread on its own
asyncio loop.

Pre-conditions:
  - Scene must have a ready image (slideshow_v4 needs a source bitmap).

Output written to `project.paths.video_path(scene_idx)`. State is updated
with `source_type="slideshow"`.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from render.slideshow import render_slideshow
from runtime.estimator import Estimator
from workers._async_thread import AsyncQThread


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _resolve_image_path(project: Project, scene_id: str) -> Path | None:
    img = project.get_scene_state(scene_id).get("image", {})
    rel = img.get("path")
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = project.paths.root / p
    return p if p.exists() else None


def is_slideshow_eligible(project: Project, scene_id: str) -> tuple[bool, str]:
    """slideshow_v4 needs a ready source image to derive objects from."""
    img = project.get_scene_state(scene_id).get("image", {})
    if img.get("status") != "ready" or not img.get("path"):
        return False, "chưa có ảnh ready để render slideshow"
    return True, ""


class SlideshowWorker(AsyncQThread):
    """Render one scene as a slideshow_v4 video.

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
        hint: str = "",
        bg_method: str = "auto",
        estimator: Estimator | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.scene_id = scene_id
        self.hint = hint
        self.bg_method = bg_method
        self.estimator = estimator

    async def _async_run(self) -> None:
        ok, reason = is_slideshow_eligible(self.project, self.scene_id)
        if not ok:
            self._mark_failed(reason)
            return

        scene = self.project.scene(self.scene_id)
        scene_idx = self.project.scene_index(self.scene_id)
        output_path = self.project.paths.video_path(scene_idx)
        image_path = _resolve_image_path(self.project, self.scene_id)
        if image_path is None:
            self._mark_failed("ảnh nguồn không tồn tại trên disk")
            return

        aspect = self.project.scenes_json.meta.aspect_ratio

        self.project.update_scene_state(
            self.scene_id, "video",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(self.scene_id)
        self.emit_log(f"{self.scene_id}: đang render slideshow ({scene.duration}s, {aspect})...")

        t0 = time.monotonic()
        try:
            result_path = await self.run_with_stop(
                render_slideshow(
                    image_path=image_path,
                    output_path=output_path,
                    duration_sec=float(scene.duration),
                    aspect_ratio=aspect,
                    hint=self.hint,
                    bg_method=self.bg_method,
                    log_cb=self.emit_log,
                )
            )
        except Exception as e:
            self._mark_failed(str(e))
            return
        elapsed = time.monotonic() - t0

        if result_path is None:
            self._mark_failed("stopped")
            return

        rel_path = self._project_relative(Path(result_path))
        new_state = {
            "status": "ready",
            "path": rel_path,
            "source_type": "slideshow",
            "last_gen_at": _now_iso(),
            "fail_reason": None,
        }
        self.project.update_scene_state(self.scene_id, "video", new_state)
        self.project.clear_warnings(self.scene_id, code="slideshow_render_failed")
        self.project.clear_warnings(self.scene_id, code="slideshow_no_objects")
        if self.estimator is not None:
            self.estimator.record_actual("slideshow_render", elapsed)
        self.scene_finished.emit(self.scene_id, new_state)
        self.emit_log(f"{self.scene_id}: ✓ slideshow {rel_path} ({elapsed:.1f}s)")

    def _mark_failed(self, reason: str) -> None:
        self.project.update_scene_state(
            self.scene_id, "video",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(self.scene_id, "slideshow_render_failed", reason)
        self.scene_failed.emit(self.scene_id, reason)
        self.emit_log(f"{self.scene_id}: ❌ slideshow {reason}")

    def _project_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
