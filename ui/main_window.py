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
from ui.dialogs.preview_image import PreviewImageDialog
from ui.dialogs.preview_video import PreviewVideoDialog
from ui.dialogs.prompt_editor import PromptEditorDialog
from ui.dialogs.voice_align_review import VoiceAlignReviewDialog
from ui.dialogs.voice_import import VoiceImportDialog
from ui.scene_list import SceneList
from workers._async_thread import AsyncQThread
from workers.render_worker import RenderWorker
from workers.voice_align_worker import VoiceAlignWorker
from workers.batch_image import BatchImageWorker
from workers.batch_video import BatchVideoWorker, is_eligible as is_video_eligible
from workers.ken_burns_worker import KenBurnsWorker, is_ken_burns_eligible
from workers.single_image import SingleImageWorker
from workers.single_video import SingleVideoWorker
from workers.slideshow_worker import SlideshowWorker, is_slideshow_eligible


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Story Video Maker")
        self.resize(1100, 750)

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

        self._build_ui()
        self._wire_signals()

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

        # Project header
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

        action_row.addSpacing(12)
        self.btn_import_voice = QPushButton("🎤 Import voice")
        self.btn_import_voice.clicked.connect(self._open_voice_import)
        self.btn_import_voice.setEnabled(False)
        action_row.addWidget(self.btn_import_voice)

        self.btn_render = QPushButton("🎬 Render final")
        self.btn_render.clicked.connect(self._start_render)
        self.btn_render.setEnabled(False)
        action_row.addWidget(self.btn_render)

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

        # Log panel
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

        outer.addWidget(log_box)

        # Loguru sink → log panel
        log.add(self._sink, level="INFO", format="{time:HH:mm:ss} | {level} | {message}")

    def _wire_signals(self) -> None:
        self.connection_panel.log_message.connect(self._append_log)
        self.connection_panel.page_ready.connect(self._on_page_ready)
        self.connection_panel.disconnected.connect(self._on_disconnected)

        self.scene_list.regen_image_clicked.connect(self._regen_one)
        self.scene_list.selected_visual_changed.connect(self._on_selected_visual_changed)
        self.scene_list.warnings_clicked.connect(self._show_warnings)
        self.scene_list.preview_image_clicked.connect(self._show_preview_image)
        self.scene_list.preview_video_clicked.connect(self._show_preview_video)
        self.scene_list.edit_clicked.connect(self._show_prompt_editor)
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
        self.btn_import_voice.setEnabled(True)
        self.btn_render.setEnabled(self.project.voice_mapping is not None)
        self._append_log(f"✓ Đã load dự án: {meta.title}")

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
        for s in self.project.scenes:
            if s.id not in selected_ids:
                continue
            ok, reason = is_video_eligible(self.project, s)
            if ok and self.project.get_scene_state(s.id)["video"]["status"] != "ready":
                eligible.append(s)
            elif not ok:
                skipped.append((s.id, reason))

        if not eligible:
            msg = "Không có scene nào đủ điều kiện gen video."
            if skipped:
                msg += "\n\nLý do bỏ qua:\n" + "\n".join(f"  • {sid}: {r}" for sid, r in skipped[:5])
            QMessageBox.information(self, "Không có gì để làm", msg)
            return

        info = self.estimator.estimate_batch("gen_video", n=len(eligible))
        confirm = QMessageBox.question(
            self,
            "Xác nhận batch video",
            f"Sắp gen {len(eligible)} video (image-to-video).\n\n"
            f"Ước tính: {info['formatted_avg']}\n{info['formatted_p90']}\n\n"
            f"Bắt đầu?",
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

    def _cleanup_single(self, scene_id: str) -> None:
        w = self._single_workers.pop(scene_id, None)
        if w is not None:
            w.deleteLater()

    def _regen_one_video(self, scene_id: str) -> None:
        """Dispatch a one-scene video re-gen by visual_type.

        video_grok       → SingleVideoWorker (Grok I2V, needs browser)
        slideshow     → SlideshowWorker (offline, needs ready image)
        ken_burns_self   → KenBurnsWorker (offline, needs ready image)
        ken_burns_cont   → KenBurnsWorker (offline, needs prev scene's video)
        image_grok       → not a video type — refuse politely
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

        elif vtype in ("ken_burns_self", "ken_burns_cont"):
            mode = "self" if vtype == "ken_burns_self" else "cont"
            ok, reason = is_ken_burns_eligible(self.project, scene_id, mode)
            if not ok:
                QMessageBox.warning(self, f"Không đủ điều kiện — {scene_id}", reason)
                return
            worker = KenBurnsWorker(self.project, scene_id, mode, estimator=self.estimator)

        else:
            QMessageBox.information(
                self, "Không phải video",
                f"Scene {scene_id} có visual_type={vtype} — không tạo video.",
            )
            return

        worker.scene_started.connect(self._on_scene_started)
        worker.scene_finished.connect(self._on_scene_finished)
        worker.scene_failed.connect(self._on_scene_failed)
        worker.log_message.connect(self._append_log)
        worker.finished.connect(lambda sid=scene_id: self._cleanup_single_video(sid))
        self._single_video_workers[scene_id] = worker
        worker.start()

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

    def _on_selected_visual_changed(self, scene_id: str, choice) -> None:
        if self.project is None:
            return
        self.project.set_selected_visual(scene_id, choice)

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

    def _show_prompt_editor(self, scene_id: str) -> None:
        if self.project is None:
            return
        scene = self.project.scene(scene_id)
        dlg = PromptEditorDialog(scene, parent=self)
        if dlg.exec() == 0 or dlg.result_kind == 0:
            return
        try:
            self.project.update_scene_fields(scene_id, dlg.collected_updates())
        except Exception as e:
            QMessageBox.critical(self, "Lỗi lưu", f"Cập nhật scene fail: {e}")
            return

        # Refresh row visual_type label (rebuild row since vtype is constructor-set)
        self.scene_list.bind_project(self.project)
        self._append_log(f"✓ Đã lưu prompts cho {scene_id}")

        if dlg.result_kind == PromptEditorDialog.SAVE_AND_REGEN:
            # Image scenes re-gen the image; video scenes re-gen the video.
            new_vtype = self.project.scene(scene_id).visual_type
            if new_vtype == "image_grok":
                self._regen_one(scene_id)
            else:
                self._regen_one_video(scene_id)

    # ------------------------------------------------------------------
    # Voice alignment (Sprint 2)
    # ------------------------------------------------------------------

    def _open_voice_import(self) -> None:
        if self.project is None:
            return
        scene_ids = [s.id for s in self.project.scenes]
        default_lang = self.project.scenes_json.meta.language
        dlg = VoiceImportDialog(self.project.paths.root, scene_ids, default_lang, parent=self)
        dlg.alignment_requested.connect(self._start_voice_align)
        dlg.exec()

    def _start_voice_align(
        self,
        voice_files: list,
        assignments: dict,
        silent_scenes: list,
        whisper_model: str,
        language: str,
    ) -> None:
        if self.project is None:
            return
        if self._voice_align_worker is not None and self._voice_align_worker.isRunning():
            QMessageBox.information(self, "Đang chạy", "Alignment đang chạy, đợi xong rồi thử lại.")
            return

        scenes = [
            {
                "id": s.id,
                "story_en": s.story_en,
                "story_vi": s.story_vi,
            }
            for s in self.project.scenes
        ]
        self._append_log(
            f"▶ Bắt đầu alignment: {len(voice_files)} file, model={whisper_model}, lang={language}"
        )
        worker = VoiceAlignWorker(
            voice_files=voice_files,
            scene_assignments=assignments,
            scenes=scenes,
            work_dir=self.project.paths.temp_dir,
            project_root=self.project.paths.root,
            silent_scenes=silent_scenes,
            whisper_model=whisper_model,
            language=language,
        )
        worker.log_message.connect(self._append_log)
        worker.failed.connect(
            lambda fn, msg: self._append_log(f"❌ {fn}: {msg}")
        )
        worker.all_done.connect(self._on_voice_align_done)
        worker.finished.connect(self._cleanup_voice_align)
        self._voice_align_worker = worker
        self.btn_import_voice.setEnabled(False)
        worker.start()

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
        dlg = VoiceAlignReviewDialog(mapping, parent=self)
        dlg.saved.connect(self._on_voice_mapping_saved)
        dlg.exec()

    def _on_voice_mapping_saved(self, mapping) -> None:
        if self.project is None:
            return
        self.project.save_voice_mapping(mapping)
        self._append_log("✓ Đã lưu chỉnh sửa timestamps")
        self.btn_render.setEnabled(True)

    def _cleanup_voice_align(self) -> None:
        worker = self._voice_align_worker
        if worker is not None:
            worker.deleteLater()
        self._voice_align_worker = None
        self.btn_import_voice.setEnabled(self.project is not None)
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

    def _show_warnings(self, scene_id: str) -> None:
        if self.project is None:
            return
        warnings = self.project.get_scene_state(scene_id).get("warnings") or []
        if not warnings:
            return
        text = "\n\n".join(
            f"[{w.get('code')}] {w.get('msg')}\nThời điểm: {w.get('ts')}"
            for w in warnings
        )
        QMessageBox.warning(self, f"Cảnh báo — {scene_id}", text)


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
