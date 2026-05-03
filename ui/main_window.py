"""MainWindow — wires connection panel, project loader, scene list, log panel.

UI labels Vietnamese; control flow English. Worker signals update SceneRow
state in the main thread.
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger as log
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.project import Project
from engines.grok import GrokImageEngine, GrokVideoEngine
from runtime.estimator import Estimator
from ui.connection_panel import ConnectionPanel
from ui.refs_panel import RefImagesPanel
from ui.dialogs.preview_dialog import PreviewDialog
from ui.dialogs.preview_image import PreviewImageDialog
from ui.dialogs.preview_video import PreviewVideoDialog
from ui.dialogs.voice_align_review import VoiceAlignReviewDialog
from ui.scene_list import SceneList
from workers._async_thread import AsyncQThread
from workers.export_worker import ExportKdenliveWorker
from workers.render_worker import RenderWorker
from workers.voice_align_worker import VoiceAlignWorker
from workers.batch_image import BatchImageWorker
from workers.batch_video import BatchVideoWorker, is_eligible as is_video_eligible
from workers.single_image import SingleImageWorker
from workers.single_video import SingleVideoWorker
from workers.slideshow_worker import SlideshowWorker, is_slideshow_eligible


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Story Video Maker")
        self.resize(1400, 850)

        self.project: Project | None = None
        self.image_engine: GrokImageEngine | None = None
        self.video_engine: GrokVideoEngine | None = None
        self.estimator = Estimator()
        self._batch_worker: BatchImageWorker | None = None
        self._batch_video_worker: BatchVideoWorker | None = None
        self._single_workers: dict[str, SingleImageWorker] = {}
        self._single_video_workers: dict[str, AsyncQThread] = {}
        self._voice_align_worker: VoiceAlignWorker | None = None
        self._render_worker: RenderWorker | None = None
        self._export_worker: ExportKdenliveWorker | None = None
        self._active_workers: list = []

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # Worker registry (for Stop All)
    # ------------------------------------------------------------------

    def _register_worker(self, worker) -> None:
        if worker is None or worker in self._active_workers:
            return
        self._active_workers.append(worker)
        if hasattr(worker, "finished"):
            worker.finished.connect(lambda w=worker: self._unregister_worker(w))

    def _unregister_worker(self, worker) -> None:
        if worker in self._active_workers:
            self._active_workers.remove(worker)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)

        # Connection panel
        self.connection_panel = ConnectionPanel()
        outer.addWidget(self.connection_panel)

        # Project header (full-width — RefImagesPanel now lives next to Log)
        self.project_box = QGroupBox("Dự án")
        proj_layout = QHBoxLayout(self.project_box)
        self.btn_load = QPushButton("📂 Mở scenes.json")
        self.btn_load.clicked.connect(self._load_project)
        proj_layout.addWidget(self.btn_load)

        self.project_label = QLabel("(Chưa load dự án)")
        self.project_label.setStyleSheet("color:#666")
        proj_layout.addWidget(self.project_label, 1)
        outer.addWidget(self.project_box)

        # Scene list + actions
        self.scene_box = QGroupBox("Scenes")
        scene_layout = QVBoxLayout(self.scene_box)

        action_row = QHBoxLayout()
        self.btn_batch_image = QPushButton("➕ Batch ảnh")
        self.btn_batch_image.clicked.connect(self._start_batch_image)
        self.btn_batch_image.setEnabled(False)
        action_row.addWidget(self.btn_batch_image)

        self.btn_batch_video = QPushButton("🎞 Batch animation")
        self.btn_batch_video.clicked.connect(self._start_batch_video)
        self.btn_batch_video.setEnabled(False)
        action_row.addWidget(self.btn_batch_video)

        self.btn_stop = QPushButton("■ Dừng")
        self.btn_stop.clicked.connect(self._stop_batch)
        self.btn_stop.setEnabled(False)
        action_row.addWidget(self.btn_stop)

        self.btn_stop_all = QPushButton("🛑 Stop All")
        self.btn_stop_all.setToolTip("Dừng tất cả workers đang chạy")
        self.btn_stop_all.setStyleSheet(
            "QPushButton { background-color: #c62828; color: white; font-weight: bold; }"
            "QPushButton:hover { background-color: #b71c1c; }"
        )
        self.btn_stop_all.clicked.connect(self._on_stop_all)
        action_row.addWidget(self.btn_stop_all)

        action_row.addSpacing(12)
        self.btn_process_voice = QPushButton("🎤 Process voice")
        self.btn_process_voice.setToolTip("Auto-align voice files in voice/ → scenes (Plan D)")
        self.btn_process_voice.clicked.connect(self._on_process_voice)
        self.btn_process_voice.setEnabled(False)
        action_row.addWidget(self.btn_process_voice)

        self.btn_reset_design = QPushButton("🔄 Reset to design")
        self.btn_reset_design.setToolTip(
            "Restore scenes from scenes.json (lose all edits in scenes_edited.json)"
        )
        self.btn_reset_design.clicked.connect(self._on_reset_to_design)
        self.btn_reset_design.setEnabled(False)
        action_row.addWidget(self.btn_reset_design)

        self.btn_render = QPushButton("🎬 Render final")
        self.btn_render.clicked.connect(self._start_render)
        self.btn_render.setEnabled(False)
        action_row.addWidget(self.btn_render)

        self.btn_export_kdenlive = QPushButton("📤 Export Kdenlive XML")
        self.btn_export_kdenlive.clicked.connect(self._on_export_kdenlive)
        self.btn_export_kdenlive.setEnabled(False)
        action_row.addWidget(self.btn_export_kdenlive)

        action_row.addSpacing(12)
        self.selection_label = QLabel("Đã chọn: 0/0")
        self.selection_label.setStyleSheet("color:#666")
        action_row.addWidget(self.selection_label)

        action_row.addStretch()
        self.progress_label = QLabel("0/0")
        action_row.addWidget(self.progress_label)
        scene_layout.addLayout(action_row)

        self.scene_list = SceneList()
        scene_layout.addWidget(self.scene_list, 1)
        outer.addWidget(self.scene_box, 1)

        # Log + Reference Images side-by-side
        log_row = QHBoxLayout()

        log_box = QGroupBox("Log")
        log_layout = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        log_layout.addWidget(self.log_view)

        log_btns = QHBoxLayout()
        btn_clear_log = QPushButton("🗑 Xóa log")
        btn_clear_log.clicked.connect(self.log_view.clear)
        log_btns.addStretch()
        log_btns.addWidget(btn_clear_log)
        log_layout.addLayout(log_btns)

        log_row.addWidget(log_box, 7)

        self.refs_panel = RefImagesPanel()
        self.refs_panel.refs_changed.connect(self._on_refs_changed)
        log_row.addWidget(self.refs_panel, 3)

        outer.addLayout(log_row)

        # Loguru sink → log panel
        log.add(self._sink, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    def _wire_signals(self) -> None:
        self.connection_panel.log_message.connect(self._append_log)
        self.connection_panel.page_ready.connect(self._on_page_ready)
        self.connection_panel.disconnected.connect(self._on_disconnected)

        self.scene_list.preview_image_clicked.connect(self._show_preview_image)
        self.scene_list.preview_video_clicked.connect(self._show_preview_video)
        self.scene_list.edit_clicked.connect(self._show_preview_dialog)
        self.scene_list.visual_type_changed.connect(self._on_visual_type_changed)
        self.scene_list.effect_changed.connect(self._on_effect_changed)
        self.scene_list.batch_selection_changed.connect(self._on_batch_selection_changed)

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _sink(self, message) -> None:
        try:
            text = message.record["message"]
            self.log_view.append(f"{message.record['time'].strftime('%H:%M:%S')}  {text}")
        except Exception:
            pass

    def _append_log(self, msg: str) -> None:
        self.log_view.append(msg)

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def _load_project(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Chọn scenes.json", "", "JSON Files (*.json)"
        )
        if not path_str:
            return
        scenes_path = Path(path_str)
        try:
            self.project = Project.load(scenes_path.parent)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi load dự án", str(e))
            self._append_log(f"❌ Load dự án fail: {e}")
            return

        meta = self.project.scenes_json.meta
        self.project_label.setText(
            f"<b>{meta.title}</b> — {meta.aspect_ratio} / {meta.language} — "
            f"{len(self.project.scenes)} scenes — <span style='color:#666'>{self.project.paths.root}</span>"
        )
        self.scene_list.bind_project(self.project)  # emits batch_selection_changed
        self.btn_process_voice.setEnabled(True)
        self.btn_reset_design.setEnabled(True)
        self.btn_render.setEnabled(self.project.voice_mapping is not None)
        self.btn_export_kdenlive.setEnabled(True)

        self.refs_panel.set_state(
            paths=[str(p) for p in self.project.get_image_refs()],
            use_refs=self.project.get_use_refs_for_image(),
        )
        self.refs_panel.setEnabled(True)

        self._append_log(f"✓ Đã load dự án: {meta.title}")

    def _on_refs_changed(self, paths: list, use_refs: bool) -> None:
        if self.project is None:
            return
        self.project.set_image_refs([str(p) for p in paths])
        self.project.set_use_refs_for_image(bool(use_refs))

    # ------------------------------------------------------------------
    # Connection callbacks
    # ------------------------------------------------------------------

    def _on_page_ready(self, page) -> None:
        self.image_engine = GrokImageEngine(page)
        self.video_engine = GrokVideoEngine(page)
        self._append_log("✓ Engine sẵn sàng (image + video)")
        self._refresh_batch_buttons()

    def _on_disconnected(self) -> None:
        self.image_engine = None
        self.video_engine = None
        self._refresh_batch_buttons()

    def _on_browser_disconnected(self) -> None:
        """Worker phát hiện page Grok đã closed → reset engine refs.

        User phải click 🔌 Kết nối lại trên ConnectionPanel để select tab mới.
        """
        if self.image_engine is None and self.video_engine is None:
            return
        self.image_engine = None
        self.video_engine = None
        self._refresh_batch_buttons()
        self._append_log(
            "ℹ Engine đã reset. Click 🔌 trên ConnectionPanel để chọn lại tab Grok."
        )

    def _refresh_batch_buttons(self) -> None:
        self._on_batch_selection_changed(
            len(self.scene_list.selected_scene_ids()), len(self.scene_list.rows)
        )

    # ------------------------------------------------------------------
    # Batch image
    # ------------------------------------------------------------------

    def _start_batch_image(self) -> None:
        if self.project is None or self.image_engine is None:
            return

        # Count scenes that actually need work (filter by batch selection)
        selected_ids = set(self.scene_list.selected_scene_ids())
        pending = [
            s for s in self.project.scenes
            if s.id in selected_ids
            and self.project.get_scene_state(s.id)["image"]["status"] != "ready"
        ]
        if not pending:
            QMessageBox.information(
                self, "Không có gì để làm",
                "Các scene đã chọn đều có ảnh rồi (hoặc chưa chọn scene nào). "
                "Dùng nút 🔄 từng scene để re-gen.",
            )
            return

        info = self.estimator.estimate_batch("gen_image", n=len(pending))
        confirm = QMessageBox.question(
            self,
            "Xác nhận batch ảnh",
            f"Sắp gen {len(pending)} ảnh.\n\n"
            f"Ước tính: {info['formatted_avg']}\n{info['formatted_p90']}\n\n"
            f"Bắt đầu?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._batch_worker = BatchImageWorker(
            self.project, self.image_engine, estimator=self.estimator,
            scene_ids=list(selected_ids),
            connection=self.connection_panel.connection,
        )
        self._batch_worker.scene_started.connect(self._on_scene_started)
        self._batch_worker.scene_finished.connect(self._on_scene_finished)
        self._batch_worker.scene_failed.connect(self._on_scene_failed)
        self._batch_worker.batch_progress.connect(self._on_progress)
        self._batch_worker.batch_done.connect(self._on_batch_done)
        self._batch_worker.log_message.connect(self._append_log)
        self._batch_worker.browser_disconnected.connect(self._on_browser_disconnected)
        self._batch_worker.scene_needs_user_decision.connect(
            lambda sid, n: self._ask_user_decision(self._batch_worker, sid, n)
        )
        self._batch_worker.finished.connect(self._batch_worker.deleteLater)
        self.btn_batch_image.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._append_log("▶ Bắt đầu batch ảnh...")
        self._batch_worker.start()
        self._register_worker(self._batch_worker)

    def _stop_batch(self) -> None:
        if self._batch_worker is not None:
            self._batch_worker.request_stop()
            self._append_log("⏸ Đang dừng batch ảnh...")
        if self._batch_video_worker is not None:
            self._batch_video_worker.request_stop()
            self._append_log("⏸ Đang dừng batch video...")
        if self._render_worker is not None and self._render_worker.isRunning():
            self._render_worker.request_stop()
            self._append_log("⏸ Đang dừng render...")

    def _on_stop_all(self) -> None:
        active = [w for w in self._active_workers if self._is_worker_running(w)]
        if not active:
            QMessageBox.information(
                self, "Stop All", "Không có worker nào đang chạy."
            )
            return

        n = len(active)
        reply = QMessageBox.question(
            self,
            "Stop All?",
            f"Dừng tất cả {n} worker đang chạy?\n\n"
            "Lưu ý: Một số tác vụ có thể đã hoàn thành 1 phần (vd download dở dang).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        log.info(f"Stop All: stopping {n} workers")
        for worker in list(active):
            try:
                if hasattr(worker, "request_stop"):
                    worker.request_stop()
                elif hasattr(worker, "stop"):
                    worker.stop()
                log.info(f"Sent stop to: {worker.__class__.__name__}")
            except Exception as e:
                log.error(f"Failed to stop {worker.__class__.__name__}: {e}")
        self._append_log(f"🛑 Stop All: signaled {n} worker(s) to stop")

    @staticmethod
    def _is_worker_running(worker) -> bool:
        try:
            if hasattr(worker, "isRunning"):
                return bool(worker.isRunning())
        except Exception:
            return False
        return True

    def _on_scene_started(self, scene_id: str) -> None:
        self.scene_list.refresh_row(scene_id)

    def _on_scene_finished(self, scene_id: str, _state: dict) -> None:
        self.scene_list.refresh_row(scene_id)

    def _on_scene_failed(self, scene_id: str, _reason: str) -> None:
        self.scene_list.refresh_row(scene_id)

    def _on_progress(self, done: int, total: int) -> None:
        self.progress_label.setText(f"{done}/{total}")

    def _on_batch_done(self, success: int, total: int) -> None:
        self.btn_stop.setEnabled(False)
        self._refresh_batch_buttons()
        self._append_log(f"✓ Batch ảnh xong: {success}/{total}")

    # ------------------------------------------------------------------
    # Batch video
    # ------------------------------------------------------------------

    def _start_batch_video(self) -> None:
        if self.project is None or self.video_engine is None:
            return

        selected_ids = set(self.scene_list.selected_scene_ids())
        eligible = []
        skipped = []
        already_ready = []
        no_prompt_warn: list[str] = []
        for s in self.project.scenes:
            if s.id not in selected_ids:
                continue
            ok, reason = is_video_eligible(self.project, s)
            if not ok:
                skipped.append((s.id, reason))
                continue
            if self.project.get_scene_state(s.id)["video"]["status"] == "ready":
                already_ready.append(s.id)
                continue
            eligible.append(s)
            if s.visual_type == "video_grok" and not s.videoPrompt:
                no_prompt_warn.append(s.id)

        if not eligible:
            msg = "Không có scene nào đủ điều kiện gen video."
            if skipped:
                msg += "\n\nLý do bỏ qua:\n" + "\n".join(f"  • {sid}: {r}" for sid, r in skipped[:5])
            if already_ready:
                msg += f"\n\nĐã có video sẵn ({len(already_ready)}): " + ", ".join(already_ready[:5])
            QMessageBox.information(self, "Không có gì để làm", msg)
            return

        info = self.estimator.estimate_batch("gen_video", n=len(eligible))

        n_video_grok = sum(1 for s in eligible if s.visual_type == "video_grok")
        n_slideshow = sum(1 for s in eligible if s.visual_type == "slideshow")
        breakdown = []
        if n_video_grok:
            breakdown.append(f"{n_video_grok} video_grok (I2V)")
        if n_slideshow:
            breakdown.append(f"{n_slideshow} slideshow")
        breakdown_str = " + ".join(breakdown) if breakdown else "—"

        body = [f"Sắp gen {len(eligible)} animation ({breakdown_str})."]
        if no_prompt_warn:
            body.append(
                f"\n⚠ {len(no_prompt_warn)} scene video_grok không có videoPrompt "
                f"(Grok sẽ suy luận từ ref image): {', '.join(no_prompt_warn[:5])}"
            )
        if skipped:
            body.append("\nBỏ qua:\n" + "\n".join(f"  • {sid}: {r}" for sid, r in skipped[:5]))
        if already_ready:
            body.append(f"\nĐã có video sẵn ({len(already_ready)}): " + ", ".join(already_ready[:5]))
        body.append(f"\nƯớc tính: {info['formatted_avg']}\n{info['formatted_p90']}\n\nBắt đầu?")

        confirm = QMessageBox.question(
            self,
            "Xác nhận batch animation",
            "\n".join(body),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._batch_video_worker = BatchVideoWorker(
            self.project, self.video_engine, estimator=self.estimator,
            scene_ids=list(selected_ids),
            connection=self.connection_panel.connection,
        )
        self._batch_video_worker.scene_started.connect(self._on_scene_started)
        self._batch_video_worker.scene_finished.connect(self._on_scene_finished)
        self._batch_video_worker.scene_failed.connect(self._on_scene_failed)
        self._batch_video_worker.scene_skipped.connect(
            lambda sid, r: self._append_log(f"⊘ {sid}: bỏ qua ({r})")
        )
        self._batch_video_worker.batch_progress.connect(self._on_progress)
        self._batch_video_worker.batch_done.connect(self._on_batch_video_done)
        self._batch_video_worker.log_message.connect(self._append_log)
        self._batch_video_worker.browser_disconnected.connect(self._on_browser_disconnected)
        self._batch_video_worker.scene_needs_user_decision.connect(
            lambda sid, n: self._ask_user_decision(self._batch_video_worker, sid, n)
        )
        self._batch_video_worker.finished.connect(self._batch_video_worker.deleteLater)
        self.btn_batch_image.setEnabled(False)
        self.btn_batch_video.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._append_log("▶ Bắt đầu batch video (I2V)...")
        self._batch_video_worker.start()
        self._register_worker(self._batch_video_worker)

    def _on_batch_video_done(self, success: int, total: int) -> None:
        self.btn_stop.setEnabled(False)
        self._refresh_batch_buttons()
        self._append_log(f"✓ Batch video xong: {success}/{total}")

    # ------------------------------------------------------------------
    # User-decision popup after retry exhausts
    # ------------------------------------------------------------------

    def _ask_user_decision(self, worker, scene_id: str, attempts: int) -> None:
        """Modal popup → set worker.set_user_decision('retry'|'skip'|'abort')."""
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(f"Scene {scene_id} fail")
        msg.setText(f"Scene {scene_id} fail {attempts} lần liên tiếp.\nBạn muốn làm gì?")
        btn_retry = msg.addButton("Retry", QMessageBox.ButtonRole.AcceptRole)
        btn_skip = msg.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
        btn_abort = msg.addButton("Abort batch", QMessageBox.ButtonRole.DestructiveRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_retry:
            decision = "retry"
        elif clicked == btn_abort:
            decision = "abort"
        else:
            decision = "skip"
        worker.set_user_decision(decision)

    # ------------------------------------------------------------------
    # Single re-gen
    # ------------------------------------------------------------------

    def _regen_one(self, scene_id: str) -> None:
        if self.project is None or self.image_engine is None:
            QMessageBox.information(self, "Chưa sẵn sàng", "Cần kết nối browser + load dự án trước")
            return
        if scene_id in self._single_workers and self._single_workers[scene_id].isRunning():
            return
        worker = SingleImageWorker(
            self.project, self.image_engine, scene_id,
            connection=self.connection_panel.connection,
        )
        worker.scene_started.connect(self._on_scene_started)
        worker.scene_finished.connect(self._on_scene_finished)
        worker.scene_failed.connect(self._on_scene_failed)
        worker.log_message.connect(self._append_log)
        worker.finished.connect(lambda sid=scene_id: self._cleanup_single(sid))
        self._single_workers[scene_id] = worker
        worker.start()
        self._register_worker(worker)

    def _cleanup_single(self, scene_id: str) -> None:
        w = self._single_workers.pop(scene_id, None)
        if w is not None:
            w.deleteLater()

    def _regen_one_video(self, scene_id: str) -> None:
        """Dispatch a one-scene video re-gen by visual_type.

        video_grok    → SingleVideoWorker (Grok I2V, needs browser)
        slideshow     → SlideshowWorker (offline, needs ready image)
        image_grok    → not animated; effect-driven motion is added at final render only.
        """
        if self.project is None:
            QMessageBox.information(self, "Chưa sẵn sàng", "Load dự án trước")
            return
        if scene_id in self._single_video_workers and self._single_video_workers[scene_id].isRunning():
            return

        scene = self.project.scene(scene_id)
        vtype = scene.visual_type

        if vtype == "video_grok":
            if self.video_engine is None:
                QMessageBox.information(self, "Chưa sẵn sàng", "Kết nối Grok trước (cần browser cho I2V)")
                return
            ok, reason = is_video_eligible(self.project, scene)
            if not ok:
                QMessageBox.warning(self, f"Không đủ điều kiện — {scene_id}", reason)
                return
            worker: AsyncQThread = SingleVideoWorker(
                self.project, self.video_engine, scene_id, estimator=self.estimator,
                connection=self.connection_panel.connection,
            )

        elif vtype == "slideshow":
            ok, reason = is_slideshow_eligible(self.project, scene_id)
            if not ok:
                QMessageBox.warning(self, f"Không đủ điều kiện — {scene_id}", reason)
                return
            worker = SlideshowWorker(self.project, scene_id, estimator=self.estimator)

        else:
            QMessageBox.information(
                self, "Không phải video",
                f"Scene {scene_id} có visual_type={vtype} — không tạo video. "
                "Hiệu ứng zoom được áp dụng lúc render final.",
            )
            return

        worker.scene_started.connect(self._on_scene_started)
        worker.scene_finished.connect(self._on_scene_finished)
        worker.scene_failed.connect(self._on_scene_failed)
        worker.log_message.connect(self._append_log)
        worker.finished.connect(lambda sid=scene_id: self._cleanup_single_video(sid))
        self._single_video_workers[scene_id] = worker
        worker.start()
        self._register_worker(worker)

    def _cleanup_single_video(self, scene_id: str) -> None:
        w = self._single_video_workers.pop(scene_id, None)
        if w is not None:
            w.deleteLater()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _on_batch_selection_changed(self, selected: int, total: int) -> None:
        self.selection_label.setText(f"Đã chọn: {selected}/{total}")
        engines_ready_image = self.image_engine is not None and self.project is not None
        engines_ready_video = self.video_engine is not None and self.project is not None
        batch_running = (
            (self._batch_worker is not None and self._batch_worker.isRunning())
            or (self._batch_video_worker is not None and self._batch_video_worker.isRunning())
        )
        self.btn_batch_image.setEnabled(engines_ready_image and selected > 0 and not batch_running)
        self.btn_batch_video.setEnabled(engines_ready_video and selected > 0 and not batch_running)

    def _on_visual_type_changed(self, scene_id: str, new_value: str) -> None:
        if self.project is None:
            return
        try:
            self.project.update_scene_field(scene_id, "visual_type", new_value)
            self._append_log(f"{scene_id} visual_type → {new_value}")
            self.scene_list.refresh_row(scene_id)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu", f"Cập nhật visual_type fail: {e}")

    def _on_effect_changed(self, scene_id: str, new_value: str) -> None:
        if self.project is None:
            return
        try:
            self.project.update_scene_field(scene_id, "effect", new_value)
            self._append_log(f"{scene_id} effect → {new_value}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu", f"Cập nhật effect fail: {e}")

    def _resolve_asset_path(self, rel_or_abs: str | None) -> Path | None:
        if not rel_or_abs or self.project is None:
            return None
        p = Path(rel_or_abs)
        if not p.is_absolute():
            p = self.project.paths.root / p
        return p if p.exists() else p  # caller decides on missing-file UX

    def _show_preview_image(self, scene_id: str) -> None:
        if self.project is None:
            return
        st = self.project.get_scene_state(scene_id).get("image", {})
        path = self._resolve_asset_path(st.get("path"))
        if path is None or not path.exists():
            QMessageBox.information(self, "Không có ảnh", f"Scene {scene_id} chưa có ảnh để xem")
            return
        dlg = PreviewImageDialog(scene_id, path, parent=self)
        dlg.regen_requested.connect(self._regen_one)
        dlg.exec()

    def _show_preview_video(self, scene_id: str) -> None:
        if self.project is None:
            return
        st = self.project.get_scene_state(scene_id).get("video", {})
        path = self._resolve_asset_path(st.get("path"))
        if path is None or not path.exists():
            QMessageBox.information(self, "Không có video", f"Scene {scene_id} chưa có video để xem")
            return
        dlg = PreviewVideoDialog(scene_id, path, parent=self)
        dlg.regen_requested.connect(self._regen_one_video)
        dlg.exec()

    def _show_preview_dialog(self, scene_id: str) -> None:
        """Unified preview + edit (thumbnail / ✏ click). Save → atomic write scenes.json."""
        if self.project is None:
            return
        scene = self.project.scene(scene_id)
        scene_state = self.project.get_scene_state(scene_id)
        dlg = PreviewDialog(
            scene=scene,
            scene_state=scene_state,
            project_root=self.project.paths.root,
            parent=self,
        )
        dlg.save_requested.connect(self._on_preview_save)
        dlg.regen_requested.connect(self._on_preview_regen)
        dlg.exec()

    def _on_preview_save(self, scene_id: str, updates: dict) -> None:
        if self.project is None:
            return
        try:
            self.project.update_scene_fields(scene_id, updates)
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu", f"Cập nhật scene fail: {e}")
            return
        self.scene_list.refresh_row(scene_id)
        self._append_log(f"✓ Đã lưu prompts cho {scene_id}")

    def _on_preview_regen(self, scene_id: str) -> None:
        if self.project is None:
            return
        new_vtype = self.project.scene(scene_id).visual_type
        if new_vtype == "image_grok":
            self._regen_one(scene_id)
        else:
            self._regen_one_video(scene_id)

    # ------------------------------------------------------------------
    # Voice alignment (Plan D — auto-trigger, no wizard)
    # ------------------------------------------------------------------

    _VOICE_EXTS = (".mp3", ".wav", ".m4a", ".flac")

    def _scan_voice_dir(self, voice_dir: Path) -> list[Path]:
        files: list[Path] = []
        for ext in self._VOICE_EXTS:
            files.extend(voice_dir.glob(f"*{ext}"))
        return sorted(files, key=lambda p: p.name.lower())

    def _on_process_voice(self) -> None:
        """Auto-align voice/ folder against scenes (Plan D, no wizard)."""
        if self.project is None:
            return
        if self._voice_align_worker is not None and self._voice_align_worker.isRunning():
            QMessageBox.information(self, "Đang chạy", "Alignment đang chạy, đợi xong rồi thử lại.")
            return

        voice_dir = self.project.paths.voice_dir
        voice_files = self._scan_voice_dir(voice_dir)
        if not voice_files:
            QMessageBox.warning(
                self,
                "Không có voice",
                f"Folder voice/ trống. Bỏ file mp3/wav vào:\n{voice_dir}",
            )
            return

        scenes = [
            {
                "id": s.id,
                "story_en": s.story_en,
                "story_vi": s.story_vi,
                "duration": s.duration,
            }
            for s in self.project.scenes
        ]
        language = self.project.scenes_json.meta.language
        self._append_log(
            f"▶ Plan D align: {len(voice_files)} voice file(s), {len(scenes)} scene(s), "
            f"lang={language}"
        )

        worker = VoiceAlignWorker(
            voice_files=voice_files,
            scene_assignments={},  # Plan D auto-matches; legacy field
            scenes=scenes,
            work_dir=self.project.paths.temp_dir,
            project_root=self.project.paths.root,
            silent_scenes=[],  # Plan D detects silent via low score
            whisper_model="base",
            language=language,
        )
        worker.log_message.connect(self._append_log)
        worker.failed.connect(
            lambda fn, msg: self._append_log(f"❌ {fn}: {msg}")
        )
        worker.all_done.connect(self._on_voice_align_done)
        worker.finished.connect(self._cleanup_voice_align)
        self._voice_align_worker = worker
        self.btn_process_voice.setEnabled(False)
        self.btn_process_voice.setText("🎤 Processing...")
        worker.start()
        self._register_worker(worker)

    def _on_reset_to_design(self) -> None:
        if self.project is None:
            return
        reply = QMessageBox.question(
            self,
            "Reset to design?",
            "Tất cả edits trong scenes_edited.json sẽ bị mất. "
            "Restore từ scenes.json gốc?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.project.reset_to_design()
        except Exception as e:
            QMessageBox.critical(self, "Reset failed", str(e))
            return
        self.scene_list.bind_project(self.project)
        self._append_log("✓ Reset: scenes_edited.json restored from scenes.json")

    def _on_voice_align_done(self, mapping) -> None:
        from core.voice_mapping import VoiceMapping  # local import to keep top tidy
        if not isinstance(mapping, VoiceMapping):
            self._append_log("⚠ alignment trả về dữ liệu không hợp lệ")
            return
        if self.project is None:
            return
        self.project.save_voice_mapping(mapping)
        self._append_log(
            f"✓ Alignment xong: {len(mapping.voice_files)} file, "
            f"silent={len(mapping.silent_scenes)} scenes — đã lưu voice_mapping.json"
        )
        scenes_data = [
            {
                "id": s.id,
                "story_en": s.story_en,
                "story_vi": s.story_vi,
                "duration": s.duration,
            }
            for s in self.project.scenes
        ]
        whisper_words: list = []
        whisper_words_path = self.project.paths.root / "whisper_words.json"
        if whisper_words_path.exists():
            try:
                import json as _json
                whisper_words = _json.loads(whisper_words_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"could not load whisper_words.json: {e}")
        dlg = VoiceAlignReviewDialog(
            voice_mapping=mapping,
            scenes_data=scenes_data,
            whisper_words=whisper_words,
            parent=self,
        )
        dlg.save_requested.connect(self._on_voice_mapping_saved)
        result = dlg.exec()
        # Re-align all = result code 2 (set by dialog button).
        if result == 2:
            self._on_process_voice()

    def _on_voice_mapping_saved(self, mapping) -> None:
        from core.voice_mapping import VoiceMapping
        if self.project is None:
            return
        if isinstance(mapping, dict):
            try:
                mapping = VoiceMapping.model_validate(mapping)
            except Exception as e:
                self._append_log(f"❌ voice_mapping schema invalid: {e}")
                return
        self.project.save_voice_mapping(mapping)
        self._append_log("✓ Đã lưu chỉnh sửa timestamps")
        self.btn_render.setEnabled(True)

    def _cleanup_voice_align(self) -> None:
        worker = self._voice_align_worker
        if worker is not None:
            worker.deleteLater()
        self._voice_align_worker = None
        self.btn_process_voice.setEnabled(self.project is not None)
        self.btn_process_voice.setText("🎤 Process voice")
        if self.project is not None and self.project.voice_mapping is not None:
            self.btn_render.setEnabled(True)

    # ------------------------------------------------------------------
    # Render final (Sprint 2 Phase 2B)
    # ------------------------------------------------------------------

    def _start_render(self) -> None:
        if self.project is None:
            return
        if self.project.voice_mapping is None:
            QMessageBox.warning(
                self, "Chưa có voice_mapping",
                "Import voice và alignment trước khi render final.",
            )
            return
        if self._render_worker is not None and self._render_worker.isRunning():
            return

        bgm_dir = self.project.paths.bgm_dir
        worker = RenderWorker(
            project=self.project,
            voice_mapping=self.project.voice_mapping,
            bgm_dir=bgm_dir if bgm_dir.exists() else None,
        )
        worker.log_message.connect(self._append_log)
        worker.scene_failed.connect(
            lambda sid, r: self._append_log(f"❌ {sid}: {r}")
        )
        worker.progress.connect(
            lambda i, n: self.progress_label.setText(f"{i}/{n}")
        )
        worker.finished_ok.connect(self._on_render_ok)
        worker.finished_fail.connect(self._on_render_fail)
        worker.finished.connect(self._cleanup_render)
        self._render_worker = worker
        self.btn_render.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._append_log("▶ Bắt đầu render final...")
        worker.start()
        self._register_worker(worker)

    def _on_render_ok(self, path: str) -> None:
        self._append_log(f"✓ Render xong: {path}")
        QMessageBox.information(self, "Done", f"Final video:\n{path}")

    def _on_render_fail(self, reason: str) -> None:
        self._append_log(f"❌ Render fail: {reason}")
        QMessageBox.critical(self, "Render fail", reason)

    def _cleanup_render(self) -> None:
        if self._render_worker is not None:
            self._render_worker.deleteLater()
        self._render_worker = None
        self.btn_render.setEnabled(
            self.project is not None and self.project.voice_mapping is not None
        )
        self.btn_stop.setEnabled(False)

    # ------------------------------------------------------------------
    # Kdenlive XML export (Sprint 2 Phase 3)
    # ------------------------------------------------------------------

    def _on_export_kdenlive(self) -> None:
        if self.project is None:
            QMessageBox.warning(self, "Chưa load dự án", "Mở scenes.json trước.")
            return
        output_path = self.project.paths.root / "export.kdenlive"
        if output_path.exists():
            reply = QMessageBox.question(
                self, "File tồn tại",
                f"{output_path.name} đã có. Ghi đè?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        voice_dict = (
            self.project.voice_mapping.model_dump()
            if self.project.voice_mapping is not None else None
        )
        worker = ExportKdenliveWorker(
            project=self.project,
            voice_mapping=voice_dict,
            output_path=output_path,
            also_srt=True,
        )
        worker.log_message.connect(self._append_log)
        worker.export_done.connect(self._on_export_done)
        worker.export_failed.connect(self._on_export_failed)
        worker.finished.connect(self._cleanup_export)
        self._export_worker = worker
        self.btn_export_kdenlive.setEnabled(False)
        self._append_log("▶ Export Kdenlive XML...")
        worker.start()
        self._register_worker(worker)

    def _on_export_done(self, kpath: str, srt: str) -> None:
        msg = f"Đã xuất Kdenlive XML:\n{kpath}"
        if srt:
            msg += f"\n\nSubtitles SRT:\n{srt}"
        msg += (
            "\n\nMở Kdenlive → File → Open → chọn .kdenlive này.\n"
            "Lưu ý: effects/transitions/color chưa export — re-add manual nếu cần."
        )
        QMessageBox.information(self, "Export OK", msg)

    def _on_export_failed(self, reason: str) -> None:
        QMessageBox.critical(self, "Export fail", reason)

    def _cleanup_export(self) -> None:
        if self._export_worker is not None:
            self._export_worker.deleteLater()
        self._export_worker = None
        self.btn_export_kdenlive.setEnabled(self.project is not None)



def run() -> None:  # pragma: no cover (manual run)
    import asyncio

    from PyQt6.QtWidgets import QApplication
    from qasync import QEventLoop

    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = MainWindow()
    win.show()

    with loop:
        loop.run_forever()


if __name__ == "__main__":  # pragma: no cover
    run()
