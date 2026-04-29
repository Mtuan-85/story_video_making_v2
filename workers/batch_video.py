"""Batch animation worker — dispatches by Scene.visual_type.

Per-scene routing:
  - video_grok    → Grok image-to-video (uses connection + retry+kill+relaunch)
  - slideshow  → render/slideshow.render_slideshow (offline)
  - ken_burns_self → render/ken_burns.ken_burns_self (offline)
  - ken_burns_cont → render/ken_burns.ken_burns_continuation (offline)
  - image_grok    → SKIP (still image IS the asset; no animation needed)

Scenes whose pre-conditions aren't met (e.g. video_grok without ref image,
slideshow without source image, ken_burns_cont without prev video) are
skipped with a Vietnamese reason.
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
from engines.grok.browser import GrokConnection
from engines.grok.engine import GrokVideoEngine
from render.ken_burns import ken_burns_continuation, ken_burns_self
from render.slideshow import render_slideshow
from runtime.estimator import Estimator
from workers._async_thread import AsyncQThread
from workers._retry import run_with_retry
from workers.ken_burns_worker import previous_scene_id


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
    """Per-visual_type eligibility for batch animation render.

    image_grok          → not animated (skip silently)
    video_grok          → requires videoPrompt + ready ref image
    slideshow        → requires ready source image
    ken_burns_self      → requires ready source image
    ken_burns_cont      → requires previous scene's video to be ready
    """
    vt = scene.visual_type
    if vt == "image_grok":
        return False, "image_grok — không cần animation"
    img = project.get_scene_state(scene.id).get("image", {})
    img_ready = img.get("status") == "ready" and bool(img.get("path"))

    if vt == "video_grok":
        if not scene.videoPrompt:
            return False, "thiếu videoPrompt"
        if not img_ready:
            return False, "chưa có ảnh ready để làm I2V"
        return True, ""

    if vt == "slideshow":
        if not img_ready:
            return False, "chưa có ảnh ready để render slideshow"
        return True, ""

    if vt == "ken_burns_self":
        if not img_ready:
            return False, "chưa có ảnh ready để Ken Burns self"
        return True, ""

    if vt == "ken_burns_cont":
        prev_id = previous_scene_id(project, scene.id)
        if prev_id is None:
            return False, "scene đầu tiên — không thể dùng ken_burns_cont"
        prev_video = project.get_scene_state(prev_id).get("video", {})
        if prev_video.get("status") != "ready" or not prev_video.get("path"):
            return False, f"scene trước ({prev_id}) chưa có video ready"
        return True, ""

    return False, f"visual_type không hỗ trợ: {vt}"


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
    browser_disconnected = pyqtSignal()
    scene_needs_user_decision = pyqtSignal(str, int)

    def __init__(
        self,
        project: Project,
        engine: GrokVideoEngine,
        force: bool = False,
        estimator: Estimator | None = None,
        scene_ids: list[str] | None = None,
        connection: GrokConnection | None = None,
    ) -> None:
        super().__init__()
        self.project = project
        self.engine = engine
        self.force = force
        self.estimator = estimator
        self.scene_ids = scene_ids
        self.connection = connection
        self._user_decision: str | None = None
        self._decision_event: asyncio.Event | None = None
        self._abort = False

    def set_user_decision(self, decision: str) -> None:
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
            if self.stop_event.is_set() or self._abort:
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
            if self._abort:
                self.emit_log("User đã abort batch")
                break

        self.emit_log(f"Batch video xong: {success}/{total} scene OK")
        self.batch_done.emit(success, total)

    async def _gen_one(self, scene: Scene, total: int, idx: int) -> bool:
        """Dispatcher by visual_type."""
        vt = scene.visual_type
        scene_idx = self.project.scene_index(scene.id)
        output_path = self.project.paths.video_path(scene_idx)
        aspect = self.project.scenes_json.meta.aspect_ratio

        self.project.update_scene_state(
            scene.id, "video",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(scene.id)

        if vt == "video_grok":
            return await self._gen_one_grok(scene, total, idx, output_path)
        if vt == "slideshow":
            return await self._gen_one_slideshow(scene, total, idx, output_path, aspect)
        if vt == "ken_burns_self":
            return await self._gen_one_ken_burns(scene, total, idx, output_path, aspect, mode="self")
        if vt == "ken_burns_cont":
            return await self._gen_one_ken_burns(scene, total, idx, output_path, aspect, mode="cont")
        return self._mark_failed(scene, f"visual_type không hỗ trợ: {vt}", warn_code="grok_no_video")

    async def _gen_one_grok(self, scene: Scene, total: int, idx: int, output_path: Path) -> bool:
        ref_image = _resolve_image_path(self.project, scene)
        if ref_image is None:
            return self._mark_failed(scene, "ref image không tồn tại trên disk", warn_code="grok_no_video")

        self.emit_log(f"[{idx}/{total}] {scene.id}: đang gen video Grok (I2V)...")
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
                    scene_id=scene.id, gen_factory=_factory,
                    connection=self.connection,
                    project_root=self.project.paths.root,
                    refresh_page=_refresh_page, log_cb=self.emit_log,
                    max_attempts=3,
                )
            else:
                outcome = {"ok": True, "result": await _factory(), "attempts": 1}
        except asyncio.CancelledError:
            return self._mark_failed(scene, "user_stopped", warn_code="grok_no_video")
        elapsed = time.monotonic() - t0

        if not outcome.get("ok") and outcome.get("needs_user_decision"):
            self.scene_needs_user_decision.emit(scene.id, outcome.get("attempts", 3))
            decision = await self._wait_for_user_decision()
            self.emit_log(f"User decision for {scene.id}: {decision}")
            if decision == "abort":
                self._abort = True
                return self._mark_failed(scene, f"user_abort (last={outcome.get('last_error')})", warn_code="grok_no_video")
            if decision == "skip":
                return self._mark_failed(scene, f"user_skip (last={outcome.get('last_error')})", warn_code="grok_no_video")
            try:
                outcome = await run_with_retry(
                    scene_id=scene.id, gen_factory=_factory,
                    connection=self.connection,
                    project_root=self.project.paths.root,
                    refresh_page=_refresh_page, log_cb=self.emit_log,
                    max_attempts=3,
                )
            except asyncio.CancelledError:
                return self._mark_failed(scene, "user_stopped", warn_code="grok_no_video")

        if not outcome.get("ok"):
            return self._mark_failed(scene, str(outcome.get("last_error", "unknown")), warn_code="grok_no_video")

        result_path = outcome["result"]
        if result_path is None:
            return self._mark_failed(scene, "stopped", warn_code="grok_no_video")

        return self._mark_ready(scene, total, idx, result_path, source_type="grok",
                                 elapsed=elapsed, action="gen_video",
                                 clear_warn_code="grok_no_video")

    async def _gen_one_slideshow(self, scene: Scene, total: int, idx: int,
                                  output_path: Path, aspect: str) -> bool:
        image_path = _resolve_image_path(self.project, scene)
        if image_path is None:
            return self._mark_failed(scene, "ảnh nguồn không tồn tại trên disk",
                                     warn_code="slideshow_render_failed")
        self.emit_log(f"[{idx}/{total}] {scene.id}: đang render slideshow ({scene.duration}s)...")
        t0 = time.monotonic()
        try:
            result_path = await self.run_with_stop(
                render_slideshow(
                    image_path=image_path, output_path=output_path,
                    duration_sec=float(scene.duration), aspect_ratio=aspect,
                    log_cb=self.emit_log,
                )
            )
        except asyncio.CancelledError:
            return self._mark_failed(scene, "user_stopped", warn_code="slideshow_render_failed")
        except Exception as e:
            return self._mark_failed(scene, str(e), warn_code="slideshow_render_failed")
        elapsed = time.monotonic() - t0
        if result_path is None:
            return self._mark_failed(scene, "stopped", warn_code="slideshow_render_failed")
        return self._mark_ready(scene, total, idx, result_path, source_type="slideshow",
                                 elapsed=elapsed, action="slideshow_render",
                                 clear_warn_code="slideshow_render_failed")

    async def _gen_one_ken_burns(self, scene: Scene, total: int, idx: int,
                                   output_path: Path, aspect: str, mode: str) -> bool:
        self.emit_log(f"[{idx}/{total}] {scene.id}: đang render Ken Burns ({mode}, {scene.duration}s)...")
        t0 = time.monotonic()
        try:
            if mode == "self":
                image_path = _resolve_image_path(self.project, scene)
                if image_path is None:
                    return self._mark_failed(scene, "ảnh nguồn không tồn tại trên disk",
                                             warn_code="ken_burns_render_failed")
                result_path = await self.run_with_stop(
                    ken_burns_self(image_path=image_path, output_path=output_path,
                                   duration_sec=float(scene.duration), aspect_ratio=aspect)
                )
            else:  # cont
                prev_id = previous_scene_id(self.project, scene.id)
                if prev_id is None:
                    return self._mark_failed(scene, "scene đầu tiên — không thể ken_burns_cont",
                                             warn_code="ken_burns_render_failed")
                prev_state = self.project.get_scene_state(prev_id).get("video", {})
                prev_rel = prev_state.get("path")
                if not prev_rel:
                    return self._mark_failed(scene, f"scene trước ({prev_id}) chưa có video",
                                             warn_code="ken_burns_render_failed")
                prev_path = Path(prev_rel)
                if not prev_path.is_absolute():
                    prev_path = self.project.paths.root / prev_path
                if not prev_path.exists():
                    return self._mark_failed(scene, f"video scene trước không có trên disk",
                                             warn_code="ken_burns_render_failed")
                result_path = await self.run_with_stop(
                    ken_burns_continuation(prev_video_path=prev_path, output_path=output_path,
                                            duration_sec=float(scene.duration), aspect_ratio=aspect,
                                            work_dir=self.project.paths.temp_dir)
                )
        except asyncio.CancelledError:
            return self._mark_failed(scene, "user_stopped", warn_code="ken_burns_render_failed")
        except Exception as e:
            return self._mark_failed(scene, str(e), warn_code="ken_burns_render_failed")
        elapsed = time.monotonic() - t0
        if result_path is None:
            return self._mark_failed(scene, "stopped", warn_code="ken_burns_render_failed")
        source_type = f"ken_burns_{mode}"
        return self._mark_ready(scene, total, idx, result_path, source_type=source_type,
                                 elapsed=elapsed, action="ken_burns_render",
                                 clear_warn_code="ken_burns_render_failed")

    def _mark_ready(self, scene: Scene, total: int, idx: int, result_path: Path,
                    source_type: str, elapsed: float, action: str,
                    clear_warn_code: str) -> bool:
        rel_path = self._project_relative(Path(result_path))
        new_state = {
            "status": "ready",
            "path": rel_path,
            "source_type": source_type,
            "last_gen_at": _now_iso(),
            "fail_reason": None,
        }
        self.project.update_scene_state(scene.id, "video", new_state)
        self.project.clear_warnings(scene.id, code=clear_warn_code)
        if self.estimator is not None:
            self.estimator.record_actual(action, elapsed)
        self.scene_finished.emit(scene.id, new_state)
        self.emit_log(f"[{idx}/{total}] {scene.id}: ✓ {rel_path} ({source_type}, {elapsed:.1f}s)")
        return True

    def _mark_failed(self, scene: Scene, reason: str,
                     warn_code: str = "grok_no_video") -> bool:
        self.project.update_scene_state(
            scene.id, "video",
            {"status": "failed", "fail_reason": reason},
        )
        self.project.add_warning(scene.id, warn_code, reason)
        self.scene_failed.emit(scene.id, reason)
        self.emit_log(f"{scene.id}: ❌ {scene.visual_type} {reason}")
        return False

    def _project_relative(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
