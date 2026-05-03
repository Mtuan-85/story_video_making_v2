"""Batch image gen worker — iterates all scenes, calls GrokImageEngine.

Reads/writes Project state per scene. Emits per-scene start/done/fail signals
so SceneRow widgets can swap status icons in the main thread.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtSignal

from core.project import Project
from core.schema import Scene
from core.thumbnail import regenerate_thumbnail
from engines.grok.browser import GrokConnection
from engines.grok.engine import GrokImageEngine
from engines.grok.image_ref_engine import GrokImageRefEngine
from runtime.estimator import Estimator
from workers._async_thread import AsyncQThread
from workers._retry import run_with_retry


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


_PAGE_CLOSED_MARKERS = (
    "target page, context or browser has been closed",
    "target page has been closed",
    "browser has been closed",
    "context closed",
    "frame was detached",
)


def _is_page_closed_err(msg: str) -> bool:
    s = (msg or "").lower()
    return any(m in s for m in _PAGE_CLOSED_MARKERS)


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
    browser_disconnected = pyqtSignal()
    scene_needs_user_decision = pyqtSignal(str, int)  # scene_id, attempts

    def __init__(
        self,
        project: Project,
        engine: GrokImageEngine,
        force: bool = False,
        pick_mode: str = "auto",
        estimator: Estimator | None = None,
        scene_ids: list[str] | None = None,
        connection: GrokConnection | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.engine = engine
        self.force = force
        self.pick_mode = pick_mode
        self.estimator = estimator
        self.scene_ids = scene_ids
        self.connection = connection
        self._user_decision: str | None = None
        self._decision_event: asyncio.Event | None = None
        self._abort = False

    def set_user_decision(self, decision: str) -> None:
        """Called from MainWindow after the user closes the decision popup."""
        self._user_decision = decision
        if self._decision_event is not None:
            self._decision_event.set()

    async def _wait_for_user_decision(self) -> str:
        if self._decision_event is None:
            self._decision_event = asyncio.Event()
        self._decision_event.clear()
        self._user_decision = None
        await self._decision_event.wait()
        return self._user_decision or "skip"

    async def _async_run(self) -> None:
        if self.scene_ids is None:
            scenes = list(self.project.scenes)
        else:
            allowed = set(self.scene_ids)
            scenes = [s for s in self.project.scenes if s.id in allowed]
        total = len(scenes)
        success = 0

        for idx, scene in enumerate(scenes, start=1):
            if self.stop_event.is_set() or self._abort:
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
            if self._abort:
                self.emit_log("User đã abort batch")
                break

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
        prompt = settings.pop("prompt")

        use_refs = self.project.get_use_refs_for_image()
        refs = self.project.get_image_refs() if use_refs else []
        if use_refs and not refs:
            self.emit_log(
                f"{scene.id}: Use refs enabled nhưng list trống — fallback text-to-image"
            )
            use_refs = False

        def _refresh_page() -> None:
            if self.connection is not None and self.connection.page is not None:
                self.engine.page = self.connection.page

        if use_refs:
            ref_engine = GrokImageRefEngine(self.engine.page)
            ref_engine.set_stop_event(self.stop_event)
            aspect = self.project.scenes_json.meta.aspect_ratio

            async def _factory():
                if self.connection is not None and self.connection.page is not None:
                    ref_engine.page = self.connection.page
                result = await ref_engine.gen_image_with_refs(
                    scene_id=scene.id,
                    prompt=prompt,
                    ref_paths=refs,
                    output_path=Path(output_path),
                    aspect=aspect,
                )
                if not result.get("ok"):
                    raise RuntimeError(
                        f"image_ref_engine fail: {result.get('reason')}"
                    )
                return Path(result["path"])
        else:
            async def _factory():
                return await self.engine.gen_image(
                    prompt=prompt, settings=dict(settings), ref_image=None,
                )

        t0 = time.monotonic()
        try:
            if self.connection is not None:
                outcome = await run_with_retry(
                    scene_id=scene.id, gen_factory=_factory,
                    connection=self.connection,
                    project_root=self.project.paths.root,
                    refresh_page=_refresh_page, log_cb=self.emit_log,
                    max_attempts=3,
                )
            else:
                # No connection ref — fall back to single-shot.
                outcome = {"ok": True, "result": await _factory(), "attempts": 1}
        except asyncio.CancelledError:
            return self._mark_failed(scene, "user_stopped")
        elapsed = time.monotonic() - t0

        if not outcome.get("ok") and outcome.get("needs_user_decision"):
            self.scene_needs_user_decision.emit(scene.id, outcome.get("attempts", 3))
            decision = await self._wait_for_user_decision()
            self.emit_log(f"User decision for {scene.id}: {decision}")
            if decision == "abort":
                self._abort = True
                return self._mark_failed(scene, f"user_abort (last={outcome.get('last_error')})")
            if decision == "skip":
                return self._mark_failed(scene, f"user_skip (last={outcome.get('last_error')})")
            # retry → one more full pass
            try:
                outcome = await run_with_retry(
                    scene_id=scene.id, gen_factory=_factory,
                    connection=self.connection,
                    project_root=self.project.paths.root,
                    refresh_page=_refresh_page, log_cb=self.emit_log,
                    max_attempts=3,
                )
            except asyncio.CancelledError:
                return self._mark_failed(scene, "user_stopped")

        if not outcome.get("ok"):
            return self._mark_failed(scene, str(outcome.get("last_error", "unknown")))

        result_path = outcome["result"]
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
        regenerate_thumbnail(
            project_root=self.project.paths.root,
            scene_id=scene.id,
            visual_path=Path(result_path),
            visual_kind="image",
        )
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
