"""Single-scene image re-gen worker.

Used when the user clicks "Re-gen" on one row. Same engine call as batch,
narrower scope, separate signal namespace so the UI knows it's a single op.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.thumbnail import regenerate_thumbnail
from engines.grok.browser import GrokConnection
from engines.grok.engine import GrokImageEngine
from workers._async_thread import AsyncQThread
from workers._retry import run_with_retry
from workers.batch_image import _build_image_settings, _now_iso


class SingleImageWorker(AsyncQThread):
    """Re-generate the image for one scene (overwrites existing file).

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
        engine: GrokImageEngine,
        scene_id: str,
        pick_mode: str = "auto",
        connection: GrokConnection | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.engine = engine
        self.scene_id = scene_id
        self.pick_mode = pick_mode
        self.connection = connection

    async def _async_run(self) -> None:
        scene = self.project.scene(self.scene_id)
        scene_idx = self.project.scene_index(self.scene_id)
        output_path = self.project.paths.image_path(scene_idx)

        self.project.update_scene_state(
            self.scene_id, "image",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(self.scene_id)
        self.emit_log(f"{self.scene_id}: đang re-gen ảnh...")

        settings = _build_image_settings(self.project, scene, output_path)
        settings["pick_mode"] = self.pick_mode
        prompt = settings.pop("prompt")

        def _refresh_page() -> None:
            if self.connection is not None and self.connection.page is not None:
                self.engine.page = self.connection.page

        async def _factory():
            return await self.engine.gen_image(
                prompt=prompt, settings=dict(settings), ref_image=None,
            )

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

        if result_path is None:
            self._mark_failed("stopped")
            return

        rel_path = self._project_relative(Path(result_path))
        new_state = {
            "status": "ready",
            "path": rel_path,
            "last_gen_at": _now_iso(),
            "fail_reason": None,
        }
        self.project.update_scene_state(self.scene_id, "image", new_state)
        self.project.clear_warnings(self.scene_id, code="grok_no_image")
        regenerate_thumbnail(
            project_root=self.project.paths.root,
            scene_id=self.scene_id,
            visual_path=Path(result_path),
            visual_kind="image",
        )
        self.scene_finished.emit(self.scene_id, new_state)
        self.emit_log(f"{self.scene_id}: ✓ {rel_path}")

    def _mark_failed(self, reason: str) -> None:
        self.project.update_scene_state(
            self.scene_id, "image",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(self.scene_id, "grok_no_image", reason)
        self.scene_failed.emit(self.scene_id, reason)
        self.emit_log(f"{self.scene_id}: ❌ {reason}")

    def _project_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
