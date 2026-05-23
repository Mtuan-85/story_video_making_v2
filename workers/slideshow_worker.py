"""Single-scene slideshow render worker.

v3 architecture: FRESH QThread per call (not asyncio.to_thread).

Why QThread instead of qasync.AsyncQThread:
  - qasync's `asyncio.to_thread` uses a shared ThreadPoolExecutor whose
    worker threads accumulate state across many renders (BLAS allocator,
    OpenCV TBB pool, Python module caches). After ~20+ slideshow renders
    we observed heap corruption (Windows 0xc0000374) in cv2.morphologyEx.
  - QThread is spawned fresh per worker, terminates after run() returns,
    so BLAS / cv2 / asyncio state is fully cleaned up between renders.
  - Mirrors zone_show_automation's pattern (proven stable).

Two modes:
  - First-time gen (rerender_only=False): full pipeline with Claude
  - Re-render (rerender_only=True): skip Claude, load saved zones JSON

State writes (atomic per call):
  - video.status / video.path / video.source_type='slideshow'
  - edit.status / edit.zones_json / edit.thumb_path

Files:
  - Final MP4 → sources/vidN.mp4 (overwrite OK)
  - Zones JSON → sources/edit/{scene_id}-zones.json (persistent)
  - Thumb → sources/edit/{scene_id}-thumb.png (persistent)
  - Cache → sources/edit/.cache/{scene_id}/ (ephemeral, deleted on success)

Cancellation NOT supported. Full pipeline runs to completion once started
(user-confirmed earlier: "full luồng cho đến khi render xong").
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

from loguru import logger as log
from PyQt6.QtCore import QThread, pyqtSignal

from core.project import Project
from core.thumbnail import regenerate_thumbnail
from runtime.estimator import Estimator


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
    """slideshow needs a ready source image."""
    img = project.get_scene_state(scene_id).get("image", {})
    if img.get("status") != "ready" or not img.get("path"):
        return False, "chưa có ảnh ready để render slideshow"
    return True, ""


class SlideshowWorker(QThread):
    """Fresh QThread per slideshow render.

    Signals (Qt::QueuedConnection — thread-safe):
        scene_started(scene_id)
        scene_finished(scene_id, state_dict)
        scene_failed(scene_id, reason)
        log_message(msg)
        finished()  ← native QThread, fires after run() returns
    """

    scene_started = pyqtSignal(str)
    scene_finished = pyqtSignal(str, dict)
    scene_failed = pyqtSignal(str, str)
    log_message = pyqtSignal(str)

    def __init__(
        self,
        project: Project,
        scene_id: str,
        hint: str = "",
        bg_method: str = "auto",
        estimator: Estimator | None = None,
        rerender_only: bool = False,
    ) -> None:
        super().__init__()
        self.project = project
        self.scene_id = scene_id
        self.hint = hint
        self.bg_method = bg_method
        self.estimator = estimator
        self.rerender_only = rerender_only
        self._stop_requested = False

    # --- Public API ---------------------------------------------------------

    def request_stop(self) -> None:
        """Best-effort stop flag. Slideshow pipeline does NOT check mid-way
        (user-confirmed full-flow design). Flag is kept for Stop-All button
        compatibility; effective only at thread cleanup boundaries.
        """
        self._stop_requested = True

    def emit_log(self, msg: str) -> None:
        """Thread-safe log: writes to loguru + emits Qt signal to UI."""
        log.info(msg)
        self.log_message.emit(msg)

    # --- QThread entry ------------------------------------------------------

    def run(self) -> None:
        """Sync entry — runs on a fresh OS thread, terminates on return."""
        try:
            self._run()
        except Exception as e:
            log.exception(f"SlideshowWorker crashed for {self.scene_id}")
            self._mark_failed(f"Worker crashed: {e}")

    def _run(self) -> None:
        scene = self.project.scene(self.scene_id)
        scene_idx = self.project.scene_index(self.scene_id)
        output_path = self.project.paths.video_path(scene_idx)

        # Project-local edit dir + persistent artefacts
        edit_dir = self.project.paths.edit_dir
        edit_dir.mkdir(parents=True, exist_ok=True)
        zones_json_path = self.project.paths.edit_zones_json(self.scene_id)
        thumb_path = self.project.paths.edit_thumb(self.scene_id)
        cache_dir = self.project.paths.edit_cache_dir(self.scene_id)

        aspect = self.project.scenes_json.meta.aspect_ratio

        # Mark BOTH video + edit as generating
        self.project.update_scene_state(
            self.scene_id, "video",
            {"status": "generating", "fail_reason": None},
        )
        self.project.update_scene_state(
            self.scene_id, "edit",
            {"status": "generating", "fail_reason": None},
        )
        self.scene_started.emit(self.scene_id)

        if self.rerender_only:
            self._run_rerender(output_path, zones_json_path, thumb_path, cache_dir)
        else:
            self._run_full(
                scene, aspect, output_path,
                zones_json_path, thumb_path, cache_dir,
            )

    # --- Modes --------------------------------------------------------------

    def _run_full(
        self,
        scene,
        aspect: str,
        output_path: Path,
        zones_json_path: Path,
        thumb_path: Path,
        cache_dir: Path,
    ) -> None:
        """Full pipeline: image → BG detect → Claude → refine → render."""
        ok, reason = is_slideshow_eligible(self.project, self.scene_id)
        if not ok:
            self._mark_failed(reason)
            return

        image_path = _resolve_image_path(self.project, self.scene_id)
        if image_path is None:
            self._mark_failed("ảnh nguồn không tồn tại trên disk")
            return

        self.emit_log(
            f"{self.scene_id}: render slideshow (full, {scene.duration}s, {aspect})..."
        )

        # Import inside run() so the slideshow modules load in THIS thread.
        # Keeps cv2/PIL/numpy state isolated per-worker.
        from slideshow import render_slideshow_v2

        t0 = time.monotonic()
        try:
            result_path = render_slideshow_v2(
                image_path=image_path,
                output_path=output_path,
                duration_sec=float(scene.duration),
                aspect_ratio=aspect,
                hint=self.hint,
                bg_method=self.bg_method,
                log_cb=self.emit_log,
                zones_json_path=zones_json_path,
                thumb_path=thumb_path,
                cache_dir=cache_dir,
            )
        except Exception as e:
            self._mark_failed(str(e))
            return

        elapsed = time.monotonic() - t0
        self._mark_success(result_path, zones_json_path, thumb_path, elapsed)

    def _run_rerender(
        self,
        output_path: Path,
        zones_json_path: Path,
        thumb_path: Path,
        cache_dir: Path,
    ) -> None:
        """Re-render from saved zones JSON (skip Claude)."""
        if not zones_json_path.exists():
            self._mark_failed(
                f"Zones JSON không tồn tại: {zones_json_path.name}. "
                f"Chạy Edit lần đầu trước."
            )
            return

        self.emit_log(f"{self.scene_id}: re-render (skip Claude)...")

        from slideshow import rerender_slideshow_v2

        t0 = time.monotonic()
        try:
            result_path = rerender_slideshow_v2(
                zones_json_path=zones_json_path,
                output_path=output_path,
                log_cb=self.emit_log,
                thumb_path=thumb_path,
                cache_dir=cache_dir,
            )
        except Exception as e:
            self._mark_failed(str(e))
            return

        elapsed = time.monotonic() - t0
        self._mark_success(result_path, zones_json_path, thumb_path, elapsed)

    # --- Result handling ----------------------------------------------------

    def _mark_success(
        self,
        result_path: Path,
        zones_json_path: Path,
        thumb_path: Path,
        elapsed: float,
    ) -> None:
        rel_video = self._project_relative(Path(result_path))
        rel_zones = self._project_relative(zones_json_path)
        rel_thumb = self._project_relative(thumb_path)
        now = _now_iso()

        video_state = {
            "status": "ready",
            "path": rel_video,
            "source_type": "slideshow",
            "last_gen_at": now,
            "fail_reason": None,
        }
        self.project.update_scene_state(self.scene_id, "video", video_state)

        edit_state = {
            "status": "ready",
            "zones_json": rel_zones,
            "thumb_path": rel_thumb if thumb_path.exists() else None,
            "last_render_at": now,
            "fail_reason": None,
        }
        self.project.update_scene_state(self.scene_id, "edit", edit_state)

        self.project.clear_warnings(self.scene_id, code="slideshow_render_failed")
        self.project.clear_warnings(self.scene_id, code="slideshow_no_objects")

        try:
            regenerate_thumbnail(
                project_root=self.project.paths.root,
                scene_id=self.scene_id,
                visual_path=Path(result_path),
                visual_kind="video",
            )
        except Exception as e:
            self.emit_log(f"WARN: thumbnail refresh failed: {e}")

        if self.estimator is not None:
            self.estimator.record_actual("slideshow_render", elapsed)

        self.scene_finished.emit(self.scene_id, video_state)
        self.emit_log(f"{self.scene_id}: ✓ slideshow {rel_video} ({elapsed:.1f}s)")

    def _mark_failed(self, reason: str) -> None:
        if self.rerender_only:
            # Only edit failed; video state untouched
            self.project.update_scene_state(
                self.scene_id, "edit",
                {"status": "failed", "fail_reason": reason},
            )
        else:
            # Full pipeline failed; both video + edit fail
            self.project.update_scene_state(
                self.scene_id, "video",
                {"status": "failed", "fail_reason": reason},
            )
            self.project.update_scene_state(
                self.scene_id, "edit",
                {"status": "failed", "fail_reason": reason},
            )
        self.project.add_warning(self.scene_id, "slideshow_render_failed", reason)
        self.scene_failed.emit(self.scene_id, reason)
        self.emit_log(f"{self.scene_id}: ❌ slideshow {reason}")

    def _project_relative(self, path: Path) -> str:
        try:
            return str(Path(path).resolve().relative_to(self.project.paths.root)).replace("\\", "/")
        except ValueError:
            return str(path)
