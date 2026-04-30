"""Single-scene image-to-video re-gen worker."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.thumbnail import regenerate_thumbnail
from engines.grok.browser import GrokConnection
from engines.grok.engine import GrokVideoEngine
from runtime.estimator import Estimator
from workers._async_thread import AsyncQThread
from workers._retry import run_with_retry
from workers.batch_video import (
    _build_video_settings,
    _now_iso,
    _resolve_image_path,
    is_eligible,
)


class SingleVideoWorker(AsyncQThread):
    """Re-generate the video for one scene (image-to-video).

    Pre-validates eligibility (visual_type, videoPrompt, ready image) and emits
    scene_failed if anything's missing — UI can use the reason directly.

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
        engine: GrokVideoEngine,
        scene_id: str,
        estimator: Estimator | None = None,
        connection: GrokConnection | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.engine = engine
        self.scene_id = scene_id
        self.estimator = estimator
        self.connection = connection

    async def _async_run(self) -> None:
        scene = self.project.scene(self.scene_id)
        ok, reason = is_eligible(self.project, scene)
        if not ok:
            self._mark_failed(reason)
            return

        scene_idx = self.project.scene_index(self.scene_id)
        output_path = self.project.paths.video_path(scene_idx)
        ref_image = _resolve_image_path(self.project, scene)
        if ref_image is None:
            self._mark_failed("ref image không tồn tại trên disk")
            return

        self.project.update_scene_state(
            self.scene_id, "video",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(self.scene_id)
        self.emit_log(f"{self.scene_id}: đang re-gen video (I2V)...")

        settings = _build_video_settings(self.project, output_path)

        def _refresh_page() -> None:
            if self.connection is not None and self.connection.page is not None:
                self.engine.page = self.connection.page

        async def _factory():
            return await self.engine.gen_video(
                prompt=scene.videoPrompt, ref_image=ref_image, settings=dict(settings),
            )

        t0 = time.monotonic()
        try:
            if self.connection is not None:
                outcome = await run_with_retry(
                    scene_id=self.scene_id, gen_factory=_factory,
                    connection=self.connection,
                    project_root=self.project.paths.root,
                    refresh_page=_refresh_page, log_cb=self.emit_log,
                    max_attempts=3,
                )
            else:
                outcome = {"ok": True, "result": await _factory(), "attempts": 1}
        except asyncio.CancelledError:
            self._mark_failed("user_stopped")
            return

        if not outcome.get("ok"):
            self._mark_failed(str(outcome.get("last_error", "unknown")))
            return
        result_path = outcome["result"]
        elapsed = time.monotonic() - t0

        if result_path is None:
            self._mark_failed("stopped")
            return

        rel_path = self._project_relative(Path(result_path))
        new_state = {
            "status": "ready",
            "path": rel_path,
            "source_type": "grok",
            "last_gen_at": _now_iso(),
            "fail_reason": None,
        }
        self.project.update_scene_state(self.scene_id, "video", new_state)
        self.project.clear_warnings(self.scene_id, code="grok_no_video")
        regenerate_thumbnail(
            project_root=self.project.paths.root,
            scene_id=self.scene_id,
            visual_path=Path(result_path),
            visual_kind="video",
        )
        if self.estimator is not None:
            self.estimator.record_actual("gen_video", elapsed)
        self.scene_finished.emit(self.scene_id, new_state)
        self.emit_log(f"{self.scene_id}: ✓ {rel_path} ({elapsed:.1f}s)")

    def _mark_failed(self, reason: str) -> None:
        self.project.update_scene_state(
            self.scene_id, "video",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(self.scene_id, "grok_no_video", reason)
        self.scene_failed.emit(self.scene_id, reason)
        self.emit_log(f"{self.scene_id}: ❌ video {reason}")

    def _project_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
